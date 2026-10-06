"""Persistent CLI, screenshot retention, and dispatched-error regression tests."""
import contextlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import io
import json
from pathlib import Path
import select
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))
from iphone_wda import Runtime
from wda_client import WDAError
from wda_vision_controller import VisualPhoneController
from test_vision import FakeVisualWDA, png

spec = importlib.util.spec_from_file_location("vision_phone_cli", ROOT / "scripts" / "phone.py")
phone_cli = importlib.util.module_from_spec(spec)
spec.loader.exec_module(phone_cli)


class FakeHTTPPhone:
    """Real loopback HTTP transport backed by a strictly screenshot-only fake."""
    def __init__(self):
        self.client = FakeVisualWDA()
        self.client.session_id = "fake-http-session"
        self.unexpected = []
        fixture = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *_args):
                pass

            def do_GET(self):
                self.handle_request("GET")

            def do_POST(self):
                self.handle_request("POST")

            def handle_request(self, method):
                length = int(self.headers.get("Content-Length", 0))
                payload = json.loads(self.rfile.read(length)) if length else None
                status = 200
                try:
                    if method == "POST" and self.path == "/session":
                        fixture.client.calls.append((method, self.path, payload))
                        response = {"sessionId": fixture.client.session_id,
                                    "value": {"sessionId": fixture.client.session_id}}
                    elif self.path.startswith("/session/fake-http-session/"):
                        path = self.path[len("/session/fake-http-session"):]
                        response = {"value": fixture.client.session(method, path, payload)}
                    else:
                        response = fixture.client.request(method, self.path, payload)
                except WDAError as exc:
                    response = {"value": {"error": exc.code, "message": str(exc)}}
                    status = 500
                except Exception as exc:
                    fixture.unexpected.append(str(exc))
                    response = {"value": {"error": "unknown error", "message": str(exc)}}
                    status = 500
                encoded = json.dumps(response).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    @property
    def url(self):
        return "http://127.0.0.1:" + str(self.server.server_port)

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)


class VisualCLITests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)

    def factory_runtime(self):
        runtime = Runtime(self.directory.name)
        runtime.client.close()
        client = FakeVisualWDA()
        runtime.client = client
        runtime.phone = VisualPhoneController(client, self.directory.name)
        return runtime, client

    def run_main(self, argv, runtime, stdin=""):
        output = io.StringIO()
        with patch.object(phone_cli, "Runtime", return_value=runtime) as factory, \
                patch.object(sys, "argv", ["phone.py", *argv]), \
                patch.object(sys, "stdin", io.StringIO(stdin)), contextlib.redirect_stdout(output):
            code = phone_cli.main()
        return code, [json.loads(line) for line in output.getvalue().splitlines()], factory

    def read_process_line(self, process):
        readable, _, _ = select.select([process.stdout], [], [], 5)
        self.assertTrue(readable, "CLI did not emit its JSON response within five seconds")
        line = process.stdout.readline()
        self.assertTrue(line, "CLI exited without a JSON response")
        return json.loads(line)

    def test_real_interactive_process_reuses_screenshot_geometry_across_lines(self):
        fixture = FakeHTTPPhone()
        self.addCleanup(fixture.close)
        process = subprocess.Popen(
            [sys.executable, str(ROOT / "scripts" / "phone.py"), "--interactive",
             "--state-dir", self.directory.name, "--url", fixture.url],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8")
        try:
            startup = self.read_process_line(process)
            self.assertTrue(startup["cli_stream_ready"])
            self.assertEqual(startup["mode"], "persistent_json_lines")
            process.stdin.write(json.dumps({"tool": "wda_vision_observe", "arguments": {}}) + "\n")
            process.stdin.flush()
            observed = self.read_process_line(process)
            ident = observed["observation_id"]
            self.assertTrue(ident)
            self.assertEqual(Path(observed["image"]["path"]).read_bytes(), fixture.client.screenshot)

            # The very next command uses an ID learned from this live process.
            process.stdin.write(json.dumps({"tool": "wda_vision_tap", "arguments": {
                "x": 100, "y": 220, "observation_id": ident}}) + "\n")
            process.stdin.flush()
            tapped = self.read_process_line(process)
            self.assertTrue(tapped["action_executed"])
            self.assertTrue(tapped["action_complete"])
            self.assertFalse(tapped["verified"])
            self.assertTrue(tapped["visual_verification_required"])
            self.assertNotEqual(tapped["observation"]["observation_id"], ident)
            self.assertEqual(len(fixture.client.actions()), 1)
            self.assertEqual(fixture.client.actions()[0][1], "/wda/tap")

            # A malformed line is reported locally without ending the stream.
            process.stdin.write("{broken\n")
            process.stdin.flush()
            malformed = self.read_process_line(process)
            self.assertEqual(malformed["error"]["code"], "invalid_argument")
            process.stdin.write(json.dumps({"tool": "wda_vision_observe", "arguments": {}}) + "\n")
            process.stdin.flush()
            after_error = self.read_process_line(process)
            self.assertIn("image", after_error)
            self.assertNotEqual(after_error["observation_id"], tapped["observation"]["observation_id"])

            process.stdin.close()
            process.stdin = None
            remaining, errors = process.communicate(timeout=5)
            self.assertEqual(process.returncode, 0, errors)
            self.assertEqual(remaining, "")
            self.assertEqual(errors, "")
            self.assertEqual(fixture.unexpected, [])
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate(timeout=5)

    def test_interactive_reuses_exactly_one_runtime_and_closes_on_eof(self):
        runtime, client = self.factory_runtime()
        code, results, factory = self.run_main(["--interactive"], runtime,
                                               json.dumps({"tool": "wda_vision_observe", "arguments": {}}) + "\n")
        self.assertEqual(code, 0)
        self.assertEqual(len(results), 2)
        self.assertTrue(results[0]["cli_stream_ready"])
        self.assertIn("observation_id", results[1])
        factory.assert_called_once_with(None, None)
        self.assertEqual(client.closed, 1)

    def test_interactive_request_shape_is_closed_and_errors_do_not_kill_stream(self):
        runtime, client = self.factory_runtime()
        invalid = [
            {"tool": "wda_vision_observe", "arguments": {}, "extra": True},
            {"tool": "wda_vision_observe"},
            ["wda_vision_observe", {}],
            {"name": "wda_vision_observe", "arguments": {}},
        ]
        lines = "".join(json.dumps(item) + "\n" for item in invalid)
        lines += '{"tool":"wda_vision_wait","arguments":{"seconds":NaN}}\n'
        lines += json.dumps({"tool": "wda_vision_observe", "arguments": {}}) + "\n"
        code, results, _ = self.run_main(["--interactive"], runtime, lines)
        self.assertEqual(code, 0)
        self.assertTrue(results[0]["cli_stream_ready"])
        for result in results[1:-1]:
            self.assertEqual(result["error"]["code"], "invalid_argument")
        self.assertIn("observation_id", results[-1])
        self.assertEqual([p for _, p, _ in client.calls].count("/screenshot"), 1)
        self.assertEqual(client.closed, 1)

    def test_one_shot_recovering_ready_exits_nonzero_and_closes_runtime(self):
        runtime = Mock()
        runtime.call.return_value = {"ready": False, "state": "recovering", "recovery": {"job_id": "job"}}
        code, results, _ = self.run_main(["wda_vision_ready", "{}"], runtime)
        self.assertEqual(code, 1)
        self.assertFalse(results[0]["ready"])
        runtime.call.assert_called_once_with("wda_vision_ready", {})
        runtime.close.assert_called_once_with()

    def test_one_shot_ready_success_exits_zero(self):
        runtime = Mock()
        runtime.call.return_value = {"ready": True, "state": "ready"}
        code, results, _ = self.run_main(["wda_vision_ready", "{}"], runtime)
        self.assertEqual(code, 0)
        self.assertTrue(results[0]["ready"])
        runtime.close.assert_called_once_with()

    def test_one_shot_cli_accepts_another_process_screenshot_id(self):
        fixture = FakeHTTPPhone()
        self.addCleanup(fixture.close)
        common = [sys.executable, str(ROOT / "scripts" / "phone.py"),
                  "--state-dir", self.directory.name, "--url", fixture.url]
        first = subprocess.run([*common, "wda_vision_observe", "{}"], capture_output=True,
                               text=True, timeout=5)
        self.assertEqual(first.returncode, 0, first.stderr)
        observed = json.loads(first.stdout)
        fixture.client.calls.clear()
        second = subprocess.run([*common, "wda_vision_tap", json.dumps({
            "x": 100, "y": 220, "observation_id": observed["observation_id"], "observe": False})],
            capture_output=True, text=True, timeout=5)
        self.assertEqual(second.returncode, 0, second.stderr)
        result = json.loads(second.stdout)
        self.assertTrue(result["action_complete"])
        self.assertFalse(result["verified"])
        self.assertNotIn("observation", result)
        self.assertEqual(fixture.client.actions(), [("POST", "/wda/tap", {"x": 100, "y": 220})])
        self.assertNotIn("/screenshot", [path for _, path, _ in fixture.client.calls])
        self.assertEqual(fixture.unexpected, [])

    def test_one_shot_invalid_json_exits_nonzero_and_closes_runtime(self):
        runtime = Mock()
        code, results, _ = self.run_main(["wda_vision_observe", "{broken"], runtime)
        self.assertEqual(code, 1)
        self.assertEqual(results[0]["error"]["code"], "invalid_argument")
        runtime.call.assert_not_called()
        runtime.close.assert_called_once_with()


class VisualArtifactAndEnvelopeTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.client = FakeVisualWDA()
        self.phone = VisualPhoneController(self.client, self.directory.name)

    def test_visual_retention_preserves_original_plugin_screenshots(self):
        artifacts = Path(self.directory.name) / "artifacts"
        artifacts.mkdir()
        originals = [artifacts / "20200101T000000000000Z-original.png", artifacts / "original-phone.png"]
        for original in originals:
            original.write_bytes(b"original plugin evidence")
        old_vision = []
        for index in range(101):
            artifact = artifacts / ("vision-20000101T000000000000Z-" + str(index).zfill(8) + ".png")
            artifact.write_bytes(b"old visual evidence")
            old_vision.append(artifact)
        observed = self.phone.observe()
        image = Path(observed["image"]["path"])
        self.assertTrue(image.name.startswith("vision-"))
        self.assertTrue(image.is_file())
        self.assertEqual(image.read_bytes(), self.client.screenshot)
        self.assertEqual(len(list(artifacts.glob("vision-*.png"))), 100)
        self.assertFalse(old_vision[0].exists())
        self.assertFalse(old_vision[1].exists())
        for original in originals:
            self.assertEqual(original.read_bytes(), b"original plugin evidence")

    def test_native_unknown_error_preserves_partial_effect_without_automatic_replay(self):
        observed = self.phone.observe()

        def partial_effect(_path, _payload):
            self.client.screenshot = png(colour=(99, 22, 33))
            raise WDAError("unknown error", "XCTest failed after entering part of the text")

        with patch.object(self.client, "mutate", side_effect=partial_effect), self.assertRaises(WDAError) as caught:
            self.phone.type_text("partial input", observed["observation_id"])
        error = caught.exception
        self.assertEqual(error.code, "unknown error")
        self.assertTrue(error.uncertain)
        self.assertIsNone(error.as_dict()["action_executed"])
        self.assertFalse(error.as_dict()["action_complete"])
        self.assertTrue(error.as_dict()["visual_verification_required"])
        self.assertEqual(Path(error.as_dict()["observation"]["image"]["path"]).read_bytes(), self.client.screenshot)
        self.assertFalse(error.as_dict()["recovery"]["replay_action"])
        self.assertEqual(len(self.client.actions()), 1)

    def test_definitive_server_rejection_reports_nonexecution_without_replay(self):
        observed = self.phone.observe()
        self.client.mutation_error = WDAError("invalid argument", "Gesture rejected")
        with self.assertRaises(WDAError) as caught:
            self.phone.tap(100, 220, observed["observation_id"])
        error = caught.exception
        self.assertFalse(error.uncertain)
        self.assertFalse(error.as_dict()["action_executed"])
        self.assertFalse(error.as_dict()["action_complete"])
        self.assertFalse(error.as_dict()["recovery"]["replay_action"])
        self.assertEqual(len(self.client.actions()), 1)


if __name__ == "__main__":
    unittest.main()
