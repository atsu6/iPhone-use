"""MCP/runtime contract tests for the separate visual WDA plugin."""
import base64
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))
from iphone_wda import Runtime, result_content, serve
from wda_client import WDAError
from wda_vision_controller import VisualPhoneController
from test_vision import FakeVisualWDA, png


class VisualProtocolTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)

    def runtime(self):
        runtime = Runtime(self.directory.name)
        self.addCleanup(runtime.close)
        runtime.client.close()
        client = FakeVisualWDA()
        runtime.client = client
        runtime.phone = VisualPhoneController(client, self.directory.name)
        manager = Mock()
        manager.pending_recovery.return_value = None
        manager.mirroring_running.return_value = False
        runtime.setup_manager = manager
        return runtime, client

    def exchange(self, requests):
        payload = "".join((item if isinstance(item, str) else json.dumps(item, ensure_ascii=False, allow_nan=False)) + "\n" for item in requests)
        process = subprocess.run(
            [sys.executable, str(ROOT / "server" / "iphone_wda.py"), "--state-dir", self.directory.name,
             "--url", "http://127.0.0.1:1"],
            input=payload, capture_output=True, text=True, encoding="utf-8", timeout=10)
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(process.stderr, "")
        return [json.loads(line) for line in process.stdout.splitlines()]

    def serve_call(self, runtime, name, arguments):
        request = {"jsonrpc": "2.0", "id": "visual-call", "method": "tools/call",
                   "params": {"name": name, "arguments": arguments}}
        output = io.StringIO()
        with patch.object(sys, "stdin", io.StringIO(json.dumps(request) + "\n")), contextlib.redirect_stdout(output):
            serve(runtime)
        response = json.loads(output.getvalue())
        self.assertEqual(response["id"], "visual-call")
        self.assertNotIn("error", response)
        result = response["result"]
        self.assertEqual(json.loads(result["content"][0]["text"]), result["structuredContent"])
        return result

    def assert_image(self, result, client):
        self.assertEqual([item["type"] for item in result["content"]], ["text", "image"])
        self.assertEqual(result["content"][1]["mimeType"], "image/png")
        self.assertEqual(base64.b64decode(result["content"][1]["data"]), client.screenshot)

    def test_stdio_initialization_ping_and_closed_visual_catalog(self):
        responses = self.exchange([
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18", "clientInfo": {"name": "test", "version": "1"}}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": "ping", "method": "ping"},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/list"},
        ])
        self.assertEqual([response["id"] for response in responses], [1, "ping", 3])
        initialized = responses[0]["result"]
        self.assertEqual(initialized["protocolVersion"], "2025-06-18")
        self.assertEqual(initialized["serverInfo"]["name"], "iphone-use-wda-vision")
        self.assertIn("iphone-wda-vision-use", initialized["instructions"])
        self.assertEqual(responses[1]["result"], {})
        tools = responses[2]["result"]["tools"]
        expected = {"wda_vision_" + name for name in (
            "doctor", "setup", "ready", "observe", "apps", "tap", "long_press", "swipe",
            "type_text", "launch_app", "press_button", "wait", "batch", "read_page", "metrics")}
        self.assertEqual({tool["name"] for tool in tools}, expected)
        self.assertEqual(len(tools), 15)
        for tool in tools:
            self.assertEqual(tool["inputSchema"]["type"], "object")
            self.assertFalse(tool["inputSchema"]["additionalProperties"])
        observed = next(tool for tool in tools if tool["name"] == "wda_vision_observe")
        self.assertEqual(observed["inputSchema"]["properties"], {})
        ready = next(tool for tool in tools if tool["name"] == "wda_vision_ready")
        self.assertEqual(set(ready["inputSchema"]["properties"]), {"recover"})
        self.assertTrue(ready["inputSchema"]["properties"]["recover"]["default"])
        required = {"tap": ["x", "y"], "long_press": ["x", "y"], "swipe": [],
                    "type_text": ["text"], "launch_app": ["bundle_id"], "press_button": ["name"]}
        for name, fields in required.items():
            tool = next(tool for tool in tools if tool["name"] == "wda_vision_" + name)
            self.assertEqual(tool["inputSchema"].get("required", []), fields)
            self.assertEqual(tool["inputSchema"]["properties"]["observe"]["type"], "boolean")
            self.assertTrue(tool["inputSchema"]["properties"]["observe"]["default"])
        page = next(tool for tool in tools if tool["name"] == "wda_vision_read_page")
        self.assertNotIn("reason", page["inputSchema"].get("required", []))
        self.assertEqual(initialized["serverInfo"]["version"], json.loads((ROOT / "plugin.json").read_text())["version"])

    def test_default_runtime_reuses_original_shared_backend_state(self):
        fake_home = Path(self.directory.name) / "home"
        fake_home.mkdir()
        environment = {k: v for k, v in os.environ.items() if k not in ("WDA_STATE_DIR", "WDA_URL")}
        with patch.dict(os.environ, environment, clear=True), patch("iphone_wda.Path.home", return_value=fake_home):
            runtime = Runtime()
        self.addCleanup(runtime.close)
        self.assertEqual(runtime.state_dir, (fake_home / ".local/share/iphone-use-wda").resolve())
        self.assertIsInstance(runtime.phone, VisualPhoneController)

    def test_ready_always_proves_screenshot_without_source(self):
        runtime, client = self.runtime()
        result = self.serve_call(runtime, "wda_vision_ready", {})
        self.assertFalse(result["isError"])
        data = result["structuredContent"]
        self.assertTrue(data["ready"])
        self.assertEqual(data["state"], "ready")
        self.assertTrue(data["proof"]["screenshot_readable"])
        self.assertTrue(data["proof"]["viewport_readable"])
        self.assertFalse(data["proof"]["xml_used"])
        self.assertNotIn("source_readable", data["proof"])
        self.assertTrue(data["visual_verification_required"])
        self.assert_image(result, client)
        runtime.setup_manager.recover.assert_not_called()

    def test_all_default_mutations_are_screenshot_only_and_unverified(self):
        runtime, client = self.runtime()
        cases = [
            ("tap", {"x": 100, "y": 220}),
            ("long_press", {"x": 100, "y": 220, "duration": .8}),
            ("swipe", {"direction": "up"}),
            ("type_text", {"text": "visual text"}),
            ("launch_app", {"bundle_id": "com.example.other"}),
            ("press_button", {"name": "home"}),
        ]
        for name, arguments in cases:
            with self.subTest(name=name):
                observed = runtime.call("wda_vision_observe", {})
                result = self.serve_call(runtime, "wda_vision_" + name,
                                         {**arguments, "observation_id": observed["observation_id"]})
                self.assertFalse(result["isError"])
                data = result["structuredContent"]
                self.assertTrue(data["action_executed"])
                self.assertTrue(data["action_complete"])
                self.assertFalse(data["verified"])
                self.assertTrue(data["visual_verification_required"])
                self.assert_image(result, client)
        self.assertEqual(len(client.actions()), len(cases))

    def test_schema_rejects_semantic_fields_before_any_phone_request(self):
        runtime, client = self.runtime()
        cases = [
            ("observe", {"mode": "tree"}),
            ("observe", {"include_invisible": True}),
            ("ready", {"screenshot": False}),
            ("tap", {"x": 100, "y": 220, "observation_id": "unused", "selector": {"label": "Target"}}),
            ("tap", {"x": 100, "y": 220, "observation_id": "unused", "expect": {"label": "Done"}}),
            ("swipe", {"observation_id": "unused", "observe": "tree"}),
            ("swipe", {"observation_id": "unused", "max_attempts": 2}),
            ("type_text", {"text": "text", "observation_id": "unused", "focused_input_confirmed": True, "replace": True}),
            ("type_text", {"text": "text", "observation_id": "unused", "focused_input_confirmed": True, "submit": True}),
            ("wait", {"selector": {"label": "Done"}}),
        ]
        for name, arguments in cases:
            with self.subTest(name=name, arguments=arguments), self.assertRaises(WDAError) as caught:
                runtime.call("wda_vision_" + name, arguments)
            self.assertEqual(caught.exception.code, "invalid_argument")
            self.assertFalse(caught.exception.as_dict().get("action_executed", False))
        self.assertEqual(client.calls, [])

    def test_every_mutation_accepts_optional_screenshot_id(self):
        runtime, client = self.runtime()
        cases = (("tap", {"x": 100, "y": 220}), ("long_press", {"x": 100, "y": 220}),
                 ("swipe", {}), ("type_text", {"text": "text"}),
                 ("launch_app", {"bundle_id": "com.example.phone"}), ("press_button", {"name": "home"}))
        for name, arguments in cases:
            with self.subTest(name=name):
                result = runtime.call("wda_vision_" + name, arguments)
                self.assertTrue(result["action_complete"])
                self.assertFalse(result["verified"])
        self.assertEqual(len(client.actions()), len(cases))

    def test_legacy_focus_false_is_accepted_and_capture_false_has_no_image(self):
        runtime, client = self.runtime()
        result = self.serve_call(runtime, "wda_vision_type_text", {
            "text": "text", "focused_input_confirmed": False, "observe": False})
        self.assertFalse(result["isError"])
        self.assertTrue(result["structuredContent"]["action_complete"])
        self.assertEqual([item["type"] for item in result["content"]], ["text"])
        self.assertEqual([method for method, _, _ in client.calls], ["POST", "POST"])

    def test_nested_batch_unknown_later_field_prevents_first_mutation(self):
        runtime, client = self.runtime()
        steps = [
            {"op": "tap", "args": {"x": 100, "y": 220, "observation_id": "unused"}},
            {"op": "swipe", "args": {"observation_id": "unused", "expect": {"label": "Done"}}},
        ]
        with self.assertRaises(WDAError) as caught:
            runtime.call("wda_vision_batch", {"steps": steps})
        data = caught.exception.as_dict()
        self.assertEqual(data["code"], "invalid_argument")
        self.assertEqual(data["argument_path"], "arguments.steps[1].args")
        self.assertEqual(data["unknown_fields"], ["expect"])
        self.assertEqual(client.calls, [])

    def test_nested_batch_invalid_later_semantics_prevents_first_mutation(self):
        cases = [
            {"op": "launch_app", "args": {"bundle_id": "not-a-bundle", "observation_id": "unused"}},
            {"op": "type_text", "args": {"text": "line 1\nline 2", "observation_id": "unused", "focused_input_confirmed": True}},
            {"op": "long_press", "args": {"x": 100, "y": 220, "duration": -1, "observation_id": "unused"}},
            {"op": "read_page", "args": {"reason": "Extract data"}},
        ]
        for later in cases:
            with self.subTest(later=later):
                runtime, client = self.runtime()
                with self.assertRaises(WDAError):
                    runtime.call("wda_vision_batch", {"steps": [
                        {"op": "tap", "args": {"x": 100, "y": 220, "observation_id": "unused"}}, later]})
                self.assertEqual(client.calls, [])

    def test_batch_runs_all_known_steps_and_displays_final_image(self):
        runtime, client = self.runtime()
        runtime.call("wda_vision_observe", {})
        client.calls.clear()
        result = self.serve_call(runtime, "wda_vision_batch", {"steps": [
            {"op": "tap", "args": {"x": 100, "y": 220}},
            {"op": "press_button", "args": {"name": "home"}},
        ]})
        self.assertFalse(result["isError"])
        data = result["structuredContent"]
        self.assertTrue(data["complete"])
        self.assertEqual(data["completed_steps"], 2)
        self.assert_image(result, client)
        self.assertEqual(len(client.actions()), 2)
        self.assertEqual([path for method, path, _ in client.calls if method == "GET"].count("/screenshot"), 1)

    def test_changed_image_still_executes_and_returns_native_mcp_image(self):
        runtime, client = self.runtime()
        observed = runtime.call("wda_vision_observe", {})
        runtime.phone.snapshots[observed["observation_id"]]["time"] = 0
        client.screenshot = png(colour=(65, 45, 25))
        client.calls.clear()
        result = self.serve_call(runtime, "wda_vision_tap", {"x": 100, "y": 220, "observation_id": observed["observation_id"]})
        self.assertFalse(result["isError"])
        self.assertTrue(result["structuredContent"]["action_executed"])
        self.assert_image(result, client)
        self.assertEqual(client.calls[0][1], "/wda/tap")
        self.assertEqual(len(client.calls), 4)

    def test_batch_uncertain_error_image_is_native_mcp_content(self):
        runtime, client = self.runtime()
        runtime.call("wda_vision_observe", {})
        client.mutation_error = WDAError("action_uncertain", "Transport timeout", uncertain=True)
        result = self.serve_call(runtime, "wda_vision_batch", {"steps": [
            {"op": "tap", "args": {"x": 100, "y": 220}},
            {"op": "press_button", "args": {"name": "home"}},
        ]})
        self.assertTrue(result["isError"])
        self.assertEqual(result["structuredContent"]["error"]["code"], "action_uncertain")
        self.assert_image(result, client)
        self.assertEqual(len(client.actions()), 1)

    def test_batch_screenshot_failure_does_not_display_prior_success_as_current_state(self):
        runtime, client = self.runtime()
        observed = runtime.call("wda_vision_observe", {})
        result = result_content({
            "complete": False,
            "results": [{"observation": observed}],
            "error": {"code": "wda_unreachable", "message": "Current screenshot failed",
                      "action_executed": True, "visual_verification_required": True},
        })
        self.assertTrue(result["isError"])
        self.assertEqual([item["type"] for item in result["content"]], ["text"])

    def test_wait_read_page_and_metrics_keep_separate_evidence_contracts(self):
        runtime, client = self.runtime()
        with patch("wda_vision_controller.time.sleep"):
            waited = runtime.call("wda_vision_wait", {"seconds": .5})
        self.assert_image(result_content(waited), client)
        client.allow_source = True
        read = runtime.call("wda_vision_read_page", {"reason": "Read dense text efficiently"})
        self.assertNotIn("observation_id", read)
        self.assertEqual([item["type"] for item in result_content(read)["content"]], ["text"])
        client.allow_source = False
        metrics = runtime.call("wda_vision_metrics", {})
        encoded = json.dumps(metrics)
        self.assertNotIn("Balance", encoded)
        self.assertNotIn("image", encoded)
        self.assertNotIn("artifacts", encoded)
        self.assertNotIn("com.example.phone", encoded)
        self.assertEqual([item["type"] for item in result_content(metrics)["content"]], ["text"])
        client.calls.clear()
        runtime.call("wda_vision_tap", {"x": 100, "y": 220,
                     "observation_id": waited["observation"]["observation_id"], "observe": False})
        self.assertEqual(client.calls, [("POST", "/wda/tap", {"x": 100, "y": 220})])

    def test_coordinate_action_does_not_repeat_locked_status_or_screenshot_reads(self):
        runtime, client = self.runtime()
        runtime.call("wda_vision_observe", {})
        client.calls.clear()
        runtime.call("wda_vision_tap", {"x": 100, "y": 220, "observe": False})
        self.assertEqual(client.calls, [("POST", "/wda/tap", {"x": 100, "y": 220})])

    def test_locked_ready_does_not_open_session_or_recover(self):
        runtime, client = self.runtime()
        client.locked = True
        result = self.serve_call(runtime, "wda_vision_ready", {})
        self.assertTrue(result["isError"])
        self.assertEqual(result["structuredContent"]["error"]["code"], "phone_locked")
        self.assertEqual(client.calls, [("GET", "/status", None), ("GET", "/wda/locked", None)])
        runtime.setup_manager.recover.assert_not_called()

    def test_mirroring_process_presence_does_not_refuse_a_healthy_ready(self):
        runtime, client = self.runtime()
        runtime.setup_manager.mirroring_running.return_value = True
        result = runtime.call("wda_vision_ready", {})
        self.assertTrue(result["ready"])
        self.assertEqual(client.actions(), [])

    def test_ready_session_retry_is_read_only_and_never_replays_action(self):
        runtime, client = self.runtime()
        observe = runtime.phone.observe
        attempts = []
        def fail_once_then_capture():
            attempts.append(True)
            if len(attempts) == 1:
                raise WDAError("wda_foreground_unavailable", "Screenshot channel failed")
            return observe()
        with patch.object(runtime.phone, "observe", side_effect=fail_once_then_capture):
            result = self.serve_call(runtime, "wda_vision_ready", {})
        self.assertEqual(len(attempts), 2)
        data = result["structuredContent"]
        self.assertTrue(data["ready"])
        self.assertTrue(data["recovery"]["session_recreated"])
        self.assertFalse(data["recovery"]["replayed_action"])
        self.assert_image(result, client)
        self.assertEqual(client.actions(), [])
        self.assertEqual([p for _, p, _ in client.calls].count("/session"), 2)
        runtime.setup_manager.recover.assert_not_called()

    def test_ready_uses_screenshot_even_when_foreground_metadata_is_unavailable(self):
        for app, error in (("local.pid.0", None), ("", None),
                           ("com.example.phone", WDAError("wda_unreachable", "Active app info unavailable"))):
            with self.subTest(app=app, error=error):
                runtime, client = self.runtime()
                client.app = app
                client.foreground_error = error
                result = self.serve_call(runtime, "wda_vision_ready", {})
                self.assertFalse(result["isError"])
                data = result["structuredContent"]
                self.assertTrue(data["ready"])
                self.assertFalse(data["proof"]["foreground_resolved"])
                self.assert_image(result, client)
                # Later subcases reuse the persisted session; neither case rebuilds it.
                self.assertLessEqual([path for _, path, _ in client.calls].count("/session"), 1)
                self.assertEqual([path for _, path, _ in client.calls].count("/screenshot"), 1)
                self.assertEqual(client.actions(), [])
                runtime.setup_manager.recover.assert_not_called()

    def test_ready_default_queues_owned_recovery_with_visual_tool_links(self):
        runtime, client = self.runtime()
        client.screenshot_error = WDAError("wda_foreground_unavailable", "Screenshot channel failed")
        runtime.setup_manager.recover.return_value = {"ok": True, "job_id": "vision-recovery", "recovery": {"state": "queued"}}
        result = self.serve_call(runtime, "wda_vision_ready", {})
        self.assertFalse(result["isError"])
        data = result["structuredContent"]
        self.assertFalse(data["ready"])
        self.assertEqual(data["state"], "recovering")
        self.assertEqual(data["recovery"]["status_tool"], "wda_vision_setup")
        self.assertEqual(data["recovery"]["next_tool"], "wda_vision_ready")
        self.assertEqual(data["recovery"]["next_arguments"], {"recover": True})
        self.assertFalse(data["recovery"]["replay_action"])
        runtime.setup_manager.recover.assert_called_once_with()
        self.assertEqual(client.actions(), [])

    def test_pending_ready_recovery_does_not_read_old_phone_session(self):
        runtime, client = self.runtime()
        runtime.setup_manager.pending_recovery.return_value = {"job_id": "pending-vision", "state": "restarting"}
        result = runtime.call("wda_vision_ready", {})
        self.assertFalse(result["ready"])
        self.assertEqual(result["state"], "recovering")
        self.assertEqual(result["recovery"]["next_tool"], "wda_vision_ready")
        self.assertEqual(client.calls, [])
        runtime.setup_manager.recover.assert_not_called()

    def test_ready_respects_explicit_recovery_disabled(self):
        runtime, client = self.runtime()
        client.screenshot_error = WDAError("wda_foreground_unavailable", "Screenshot channel failed")
        result = self.serve_call(runtime, "wda_vision_ready", {"recover": False})
        self.assertFalse(result["isError"])
        data = result["structuredContent"]
        self.assertFalse(data["ready"])
        self.assertEqual(data["state"], "recovery_required")
        self.assertEqual(data["reason"], "recovery_disabled")
        self.assertEqual(data["recovery"]["next_tool"], "wda_vision_ready")
        self.assertEqual(data["recovery"]["next_arguments"], {"recover": True})
        runtime.setup_manager.recover.assert_not_called()
        self.assertEqual(client.actions(), [])

    def test_action_channel_fault_proposes_ready_without_automatic_replay(self):
        runtime, client = self.runtime()
        observed = runtime.call("wda_vision_observe", {})
        client.screenshot_error = WDAError("wda_foreground_unavailable", "Screenshot channel failed")
        result = self.serve_call(runtime, "wda_vision_tap", {"x": 100, "y": 220, "observation_id": observed["observation_id"]})
        self.assertTrue(result["isError"])
        data = result["structuredContent"]["error"]
        self.assertEqual(data["category"], "channel_runtime")
        self.assertEqual(data["recovery"]["tool"], "wda_vision_ready")
        self.assertEqual(data["recovery"]["arguments"], {"recover": True})
        self.assertFalse(data["recovery"]["replay_action"])
        self.assertEqual(len(client.actions()), 1)
        self.assertTrue(data["action_executed"])
        runtime.setup_manager.recover.assert_not_called()

    def test_operation_lock_is_shared_and_refuses_all_phone_requests(self):
        runtime, client = self.runtime()
        script = "import fcntl,sys; lock=open(sys.argv[1], 'a'); fcntl.flock(lock, fcntl.LOCK_EX); print('locked', flush=True); sys.stdin.read(); lock.close()"
        worker = subprocess.Popen([sys.executable, "-c", script, str(Path(self.directory.name) / "operation.lock")],
                                  stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            self.assertEqual(worker.stdout.readline().strip(), "locked")
            with self.assertRaises(WDAError) as caught:
                runtime.call("wda_vision_observe", {})
            self.assertEqual(caught.exception.code, "device_busy")
            self.assertEqual(client.calls, [])
        finally:
            try:
                worker.communicate(input="release", timeout=3)
            except subprocess.TimeoutExpired:
                worker.kill()
                worker.communicate()
        self.assertEqual(worker.returncode, 0)

    def test_independent_runtimes_share_session_cache_without_a_new_request(self):
        first, first_client = self.runtime()
        second, second_client = self.runtime()
        first_client.session_id = "shared-session-123"
        with patch.object(first, "_call", side_effect=lambda name, args: {"session_id": first.client.session_id}):
            self.assertEqual(first.call("wda_vision_metrics", {}), {"session_id": "shared-session-123"})
        with patch.object(second, "_call", side_effect=lambda name, args: {"session_id": second.client.session_id}):
            self.assertEqual(second.call("wda_vision_metrics", {}), {"session_id": "shared-session-123"})
        self.assertEqual(first_client.calls + second_client.calls, [])
        cache = Path(self.directory.name) / "session.json"
        self.assertEqual(json.loads(cache.read_text()), {"url": first.base_url, "session_id": "shared-session-123"})
        self.assertEqual(cache.stat().st_mode & 0o777, 0o600)

    def test_catalog_and_metrics_are_available_without_phone_requests(self):
        runtime, client = self.runtime()
        client.locked = True
        catalog = runtime.call("wda_vision_apps", {"query": "招商银行", "source": "catalog"})
        self.assertTrue(catalog["ok"])
        self.assertEqual(catalog["candidates"][0]["bundle_id"], "com.cmbchina.MPBBank")
        runtime.call("wda_vision_metrics", {})
        self.assertEqual(client.calls, [])

    def test_stdio_invalid_calls_fail_locally_and_protocol_remains_usable(self):
        cases = [
            ("wda_vision_observe", {"mode": "tree"}),
            ("wda_vision_ready", {"screenshot": False}),
            ("wda_vision_tap", {"x": True, "y": 220, "observation_id": "unused"}),
            ("wda_vision_swipe", {"observe": "tree"}),
            ("wda_vision_type_text", {"text": "text", "observe": "none"}),
            ("wda_tap", {"selector": {"label": "Target"}}),
        ]
        requests = [{"jsonrpc": "2.0", "id": i, "method": "tools/call", "params": {"name": name, "arguments": args}}
                    for i, (name, args) in enumerate(cases)]
        responses = self.exchange([*requests, "{broken", {"jsonrpc": "2.0", "id": "ping", "method": "ping"}])
        for response in responses[:len(cases)]:
            result = response["result"]
            self.assertTrue(result["isError"])
            data = json.loads(result["content"][0]["text"])
            self.assertEqual(data, result["structuredContent"])
            self.assertIn(data["error"]["code"], ("invalid_argument", "unknown_tool"))
        self.assertEqual(responses[-2]["error"]["code"], -32700)
        self.assertEqual(responses[-1]["result"], {})


if __name__ == "__main__":
    unittest.main()
