import os
from pathlib import Path
import signal
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))
import wda_setup


class SetupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.manager = wda_setup.SetupManager(Path(self.temp.name) / "state")

    def tearDown(self):
        self.temp.cleanup()

    def configure(self, **extra):
        return self.manager.setup("configure", udid="00008150-ABCDEF0123456789", team_id="ABCDE12345",
                                  bundle_id="com.example.wdarunner", **extra)

    def job(self, token="owned-marker", pid=12345):
        return {"id": "a" * 32, "action": "start", "state": "running", "pid": pid,
                "owner_token": token, "created_at": "2026-10-06T00:00:00Z", "config": {}}

    def test_config_requires_explicit_signing_values_and_safe_ports(self):
        self.assertFalse(self.manager.setup("configure")["ok"])
        self.assertFalse(self.configure(local_port=80)["ok"])
        self.assertFalse(self.configure(local_port=True)["ok"])
        self.assertFalse(self.configure(local_port=18101)["ok"])
        self.assertFalse(self.manager.setup("configure", udid="id; touch /tmp/pwn", team_id="ABCDE12345", bundle_id="com.example.runner")["ok"])
        self.assertFalse(self.configure(apple_password="secret")["ok"])
        result = self.configure()
        self.assertTrue(result["ok"])
        self.assertEqual(result["config"]["local_port"], 18100)
        self.assertTrue(result["config"]["source_dir"].startswith(str(self.manager.state_dir)))
        self.assertEqual((self.manager.state_dir / "config.json").stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.manager.state_dir.stat().st_mode & 0o777, 0o700)

    def test_runtime_rejects_repository_and_non_loopback_url(self):
        with self.assertRaises(ValueError):
            wda_setup.SetupManager(wda_setup.PLUGIN_ROOT / "private-runtime")
        for url in ("http://example.org:8100", "http://user:password@localhost:18100", "http://localhost:18100/path", "https://localhost:18100"):
            with self.assertRaises(ValueError):
                wda_setup.SetupManager(Path(self.temp.name) / "other", url)
        other_repository = Path(self.temp.name) / "other-repository"
        (other_repository / ".git").mkdir(parents=True)
        with self.assertRaises(ValueError):
            wda_setup.SetupManager(other_repository / "runtime")

    def test_current_and_legacy_devicectl_json(self):
        current = {"result": {"devices": [
            {"identifier": "core-device", "properties": {"hardware": {"reality": "physical", "deviceType": "iPhone", "udid": "UDID-REAL"},
             "state": {"name": "Phone", "developerModeStatus": {"enabled": {"mode": 1}}},
             "connection": {"pairingState": "paired", "state": "connected", "transportType": "wired"},
             "software": {"osVersionNumber": {"stringValue": "26.7.1"}}}},
            {"properties": {"hardware": {"reality": "simulated", "deviceType": "iPhone"}}}
        ]}}
        devices = wda_setup.SetupManager.parse_devices(current)
        self.assertEqual(len(devices), 1)
        self.assertEqual(devices[0]["udid"], "UDID-REAL")
        self.assertEqual(devices[0]["developer_mode"], "enabled")
        self.assertEqual(devices[0]["ios_version"], "26.7.1")
        legacy = {"result": {"devices": [{"identifier": "core", "hardwareProperties": {"reality": "physical", "deviceType": "iPhone", "udid": "LEGACY-UDID"},
                  "deviceProperties": {"name": "Legacy", "developerModeStatus": "disabled", "osVersionNumber": "17.0"},
                  "connectionProperties": {"pairingState": "unpaired", "tunnelState": "disconnected"}}]}}
        parsed = wda_setup.SetupManager.parse_devices(legacy)[0]
        self.assertEqual(parsed["developer_mode"], "disabled")
        self.assertEqual(parsed["pairing_state"], "unpaired")
        self.assertEqual(parsed["unlocked"], "user_check_required")

    def test_job_status_redacts_and_reports_actionable_signing_failure(self):
        job = self.job()
        job["state"] = "failed"
        log = self.manager.state_dir / "logs" / (job["id"] + ".log")
        log.write_text("Apple ID someone@example.org password=supersecret\nAuthorization: Bearer private-token\nNo profiles for app. Provisioning profile expired.\n")
        result = self.manager._job_status(job)
        self.assertNotIn("someone@example.org", result["log_tail"])
        self.assertNotIn("supersecret", result["log_tail"])
        self.assertNotIn("private-token", result["log_tail"])
        self.assertNotIn("owner_token", result)
        self.assertTrue(any("expired" in hint for hint in result["next_steps"]))

    def test_only_owned_process_group_can_be_stopped(self):
        owned, stale = self.job(), self.job(token="old-token", pid=12346)
        stale["id"] = "b" * 32
        for job in (owned, stale):
            wda_setup._write_json(self.manager._job_path(job["id"]), job)
        command = f"python {wda_setup.__file__} --worker {self.manager.state_dir} {owned['id']} {owned['owner_token']}"
        with patch.object(wda_setup.os, "getpgid", side_effect=lambda pid: pid), \
             patch.object(wda_setup, "_run", return_value={"ok": True, "stdout": command}), \
             patch.object(wda_setup.os, "killpg") as kill:
            result = self.manager.setup("stop")
        kill.assert_called_once_with(12345, signal.SIGTERM)
        self.assertEqual(result["stopped_jobs"], [owned["id"]])
        self.assertEqual(result["unverified_jobs_preserved"], [stale["id"]])

    def test_worker_ownership_survives_installation_path_change(self):
        job = self.job()
        original_entrypoint = "/private/source checkout/server/wda_setup.py"
        self.assertNotEqual(original_entrypoint, str(Path(wda_setup.__file__).resolve()))
        job["worker_entrypoint"] = original_entrypoint
        command = f"python {original_entrypoint} --worker {self.manager.state_dir} {job['id']} {job['owner_token']} --base-url http://127.0.0.1:18100"
        with patch.object(wda_setup.os, "getpgid", return_value=job["pid"]), \
             patch.object(wda_setup, "_run", return_value={"ok": True, "stdout": command}):
            self.assertTrue(self.manager._owned(job))
            job["worker_entrypoint"] = "/different/cache/server/wda_setup.py"
            self.assertFalse(self.manager._owned(job))
            job["worker_entrypoint"] = original_entrypoint
            job["owner_token"] = "different-marker"
            self.assertFalse(self.manager._owned(job))
            for invalid in ("", "server/wda_setup.py", "/private/source/other.py", None):
                job["worker_entrypoint"] = invalid
                self.assertFalse(self.manager._owned(job))
        job["worker_entrypoint"] = original_entrypoint
        job["owner_token"] = "owned-marker"
        prefixed_command = command.replace(original_entrypoint, "/different-prefix" + original_entrypoint)
        with patch.object(wda_setup.os, "getpgid", return_value=job["pid"]), \
             patch.object(wda_setup, "_run", return_value={"ok": True, "stdout": prefixed_command}):
            self.assertFalse(self.manager._owned(job))

    def test_source_reuse_checks_pin_and_preserves_checkout(self):
        source = Path(self.temp.name) / "external-source"
        (source / "WebDriverAgent.xcodeproj").mkdir(parents=True)
        (source / "WebDriverAgent.xcodeproj/project.pbxproj").write_text("fixture")
        responses = [{"ok": True, "stdout": "wrong-head\n"}]
        with patch.object(wda_setup, "_run", side_effect=responses):
            self.assertFalse(self.configure(source_dir=str(source))["ok"])
        self.assertEqual((source / "WebDriverAgent.xcodeproj/project.pbxproj").read_text(), "fixture")
        responses = [{"ok": True, "stdout": wda_setup.WDA_COMMIT + "\n"}, {"ok": True, "stdout": ""}]
        with patch.object(wda_setup, "_run", side_effect=responses):
            self.assertTrue(self.configure(source_dir=str(source))["ok"])

    def test_start_requires_matching_successful_build(self):
        self.configure()
        with patch.object(self.manager, "_source", return_value=Path(self.temp.name)), \
             patch.object(self.manager, "_probe_status", return_value={"ready": False}), \
             patch.object(wda_setup.sys, "platform", "darwin"), \
             patch.object(wda_setup.shutil, "which", return_value="/usr/bin/xcodebuild"):
            result = self.manager.setup("start")
        self.assertFalse(result["ok"])
        self.assertIn("build successfully", result["error"])

    def test_start_reuses_ready_external_service_without_spawning(self):
        self.configure()
        with patch.object(self.manager, "_source", return_value=Path(self.temp.name)), \
             patch.object(self.manager, "_probe_status", return_value={"ready": True, "reachable": True}), \
             patch.object(wda_setup.sys, "platform", "darwin"), \
             patch.object(wda_setup.shutil, "which", return_value="/usr/bin/xcodebuild"), \
             patch.object(self.manager, "_create_job") as create:
            result = self.manager.setup("start")
        self.assertTrue(result["already_ready"])
        create.assert_not_called()

    def test_build_command_uses_explicit_build_for_testing_no_shell(self):
        self.configure()
        config = self.manager.config
        command = self.manager._build_command(config, "build-for-testing")
        self.assertEqual(command[-1], "build-for-testing")
        self.assertIn("DEVELOPMENT_TEAM=ABCDE12345", command)
        self.assertIn("PRODUCT_BUNDLE_IDENTIFIER=com.example.wdarunner", command)
        self.assertIn("id=" + config["udid"], command)
        self.assertIn(str(self.manager.state_dir / "derived_data"), command)
        self.assertIn("USE_PORT=8100", command)

    def test_actual_worker_completes_failure_without_blocking_caller(self):
        # Unsupported internal action exercises a real worker, private job output,
        # ownership handshake and persistence without touching Xcode or a phone.
        started = time.monotonic()
        result = self.manager._create_job("unsupported-test-fixture", {})
        self.assertLess(time.monotonic() - started, 2)
        path = self.manager._job_path(result["job_id"])
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            job = wda_setup._read_json(path, {})
            if job.get("state") == "failed":
                break
            time.sleep(0.02)
        self.assertEqual(job["state"], "failed")
        self.assertIn("Unsupported worker action", job["error"])
        self.assertEqual(job["worker_entrypoint"], str(Path(wda_setup.__file__).resolve()))
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual((self.manager.state_dir / "logs" / (job["id"] + ".log")).stat().st_mode & 0o777, 0o600)
        # Reap this test's direct child; production callers keep jobs independent.
        self.manager._workers[job["id"]].wait(timeout=3)

    def test_status_rejects_path_traversal_job_ids(self):
        self.assertFalse(self.manager.setup("status", job_id="../../config")["ok"])
        self.assertFalse(self.manager.setup("execute", command="echo unsafe")["ok"])

    def test_completed_worker_cleans_up_its_orphan_descendant(self):
        # Emulate a command leaving a TERM-resistant child in the job group.
        # This verifies cleanup without running Xcode, touching any real device,
        # or signalling a process from outside this test's worker group.
        bin_dir = Path(self.temp.name) / "bin"
        bin_dir.mkdir()
        source = Path(self.temp.name) / "source"
        (source / "WebDriverAgent.xcodeproj").mkdir(parents=True)
        (source / "WebDriverAgent.xcodeproj/project.pbxproj").write_text("fixture")
        git = bin_dir / "git"
        git.write_text(f"#!{sys.executable}\nimport sys\nif 'rev-parse' in sys.argv: print({wda_setup.WDA_COMMIT!r})\n")
        xcode = bin_dir / "xcodebuild"
        xcode.write_text(f"#!{sys.executable}\nimport subprocess, sys, time\nfrom pathlib import Path\n"
                         "child=subprocess.Popen([sys.executable,'-c','import signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); time.sleep(120)'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)\n"
                         "Path('child.pid').write_text(str(child.pid))\ntime.sleep(0.15)\n")
        git.chmod(0o700)
        xcode.chmod(0o700)
        config = {"udid": "00008150-ABCDEF0123456789", "team_id": "ABCDE12345", "bundle_id": "com.example.runner",
                  "source_dir": str(source), "local_port": 18100, "device_port": 8100}
        with patch.dict(os.environ, {"PATH": str(bin_dir) + os.pathsep + os.environ.get("PATH", "")}):
            result = self.manager._create_job("build", config)
        process = self.manager._workers[result["job_id"]]
        process.wait(timeout=10)
        job = wda_setup._read_json(self.manager._job_path(result["job_id"]))
        self.assertEqual(job["state"], "succeeded", job.get("error"))
        child_pid = int((source / "child.pid").read_text())
        descendant = wda_setup._run(["ps", "-p", str(child_pid), "-o", "stat="], timeout=2)
        self.assertTrue(not descendant["stdout"].strip() or descendant["stdout"].strip().startswith("Z"))

    def test_node_supported_matches_locked_dependency_engines(self):
        for version in ("v20.19.0", "v20.20.1", "22.12.0", "v24.18.0", "v26.0.0"):
            self.assertTrue(wda_setup._node_supported(version))
        for version in ("v18.20.0", "v20.18.1", "v21.9.0", "v22.11.0", "v23.0.0", "unknown"):
            self.assertFalse(wda_setup._node_supported(version))


if __name__ == "__main__":
    unittest.main()
