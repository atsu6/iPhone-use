import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))
from iphone_wda import Runtime
from wda_client import WDAError
from wda_controller import PhoneController
from test_controller import FakeWDA


class ProtocolTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)

    def exchange(self, requests):
        payload = "".join(json.dumps(item, ensure_ascii=False, allow_nan=False) + "\n" if not isinstance(item, str) else item + "\n" for item in requests)
        process = subprocess.run(
            [sys.executable, str(ROOT / "server" / "iphone_wda.py"), "--state-dir", self.directory.name],
            input=payload, capture_output=True, text=True, encoding="utf-8", timeout=10)
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(process.stderr, "")
        return [json.loads(line) for line in process.stdout.splitlines()]

    def runtime(self):
        runtime = Runtime(self.directory.name)
        self.addCleanup(runtime.close)
        client = FakeWDA()
        runtime.client = client
        # Restore a close method for Runtime cleanup; fake transports have no sockets.
        client.close = lambda: None
        runtime.phone = PhoneController(client, self.directory.name)
        return runtime, client

    def test_stdio_initialization_notifications_ping_and_tool_catalog(self):
        responses = self.exchange([
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18", "clientInfo": {"name": "test", "version": "1"}}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": "ping", "method": "ping"},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/list"},
        ])
        self.assertEqual([response["id"] for response in responses], [1, "ping", 3])
        self.assertEqual(responses[0]["result"]["protocolVersion"], "2025-06-18")
        self.assertEqual(responses[0]["result"]["serverInfo"]["name"], "iphone-use-wda")
        self.assertEqual(responses[1]["result"], {})
        tools = responses[2]["result"]["tools"]
        names = [tool["name"] for tool in tools]
        self.assertEqual(len(names), len(set(names)))
        for name in ("wda_ready", "wda_setup", "wda_observe", "wda_tap", "wda_type_text", "wda_batch", "wda_collect_list"):
            self.assertIn(name, names)
        for tool in tools:
            self.assertEqual(tool["inputSchema"]["type"], "object")
            self.assertFalse(tool["inputSchema"]["additionalProperties"])

    def test_stdio_invalid_arguments_return_tool_error_without_wda_access(self):
        invalid_cases = [
            ("wda_tap", {"x": True, "y": 200, "observation_id": "unused"}),
            ("wda_type_text", {"selector": {"label": "Target"}, "text": "line 1\nline 2"}),
            ("wda_find", {"selector": {"label": "Target", "predicate": "label == 'Target'"}}),
            ("wda_batch", {"steps": [{"op": "tap", "args": {"selector": {"label": "Target"}}}, {"op": "unknown", "args": {}}]}),
            ("wda_missing", {}),
        ]
        responses = self.exchange([{"jsonrpc": "2.0", "id": index, "method": "tools/call", "params": {"name": name, "arguments": args}} for index, (name, args) in enumerate(invalid_cases)])
        self.assertEqual(len(responses), len(invalid_cases))
        for response in responses:
            result = response["result"]
            self.assertTrue(result["isError"])
            content = json.loads(result["content"][0]["text"])
            self.assertEqual(content, result["structuredContent"])
            self.assertNotIn(content["error"]["code"], ("wda_unreachable", "action_uncertain", "internal_error"))

    def test_stdio_parse_error_does_not_break_following_ping(self):
        responses = self.exchange(["{broken", {"jsonrpc": "2.0", "id": 1, "method": "ping"}])
        self.assertEqual(responses[0]["error"]["code"], -32700)
        self.assertEqual(responses[1]["result"], {})

    def test_stdio_unknown_method_and_invalid_params_are_rpc_errors(self):
        responses = self.exchange([
            {"jsonrpc": "2.0", "id": 1, "method": "not/a/method"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": []},
        ])
        self.assertEqual(responses[0]["error"]["code"], -32601)
        self.assertEqual(responses[1]["error"]["code"], -32602)

    def test_nested_batch_schema_is_checked_before_any_phone_request(self):
        runtime, client = self.runtime()
        steps = [
            {"op": "type_text", "args": {"selector": {"label": "Target"}, "text": "Do not enter", "observe": "none"}},
            {"op": "tap", "args": {"selector": {"label": "Target"}, "extra": True}},
        ]
        with self.assertRaises(WDAError) as caught:
            runtime.call("wda_batch", {"steps": steps})
        self.assertEqual(caught.exception.code, "invalid_argument")
        self.assertEqual(client.calls, [])

    def test_malformed_later_selector_is_checked_before_any_phone_request(self):
        runtime, client = self.runtime()
        steps = [
            {"op": "type_text", "args": {"selector": {"label": "Target"}, "text": "Do not enter", "observe": "none"}},
            {"op": "tap", "args": {"selector": {"label": "Target", "predicate": "label == 'Target'"}, "observe": "none"}},
        ]
        with self.assertRaises(WDAError) as caught:
            runtime.call("wda_batch", {"steps": steps})
        self.assertEqual(caught.exception.code, "invalid_selector")
        self.assertEqual(client.calls, [])

    def test_later_invalid_bundle_id_is_checked_before_any_phone_request(self):
        runtime, client = self.runtime()
        steps = [
            {"op": "type_text", "args": {"selector": {"label": "Target"}, "text": "Do not enter", "observe": "none"}},
            {"op": "launch_app", "args": {"bundle_id": "not-a-bundle", "observe": "none"}},
        ]
        with self.assertRaises(WDAError) as caught:
            runtime.call("wda_batch", {"steps": steps})
        self.assertEqual(caught.exception.code, "invalid_argument")
        self.assertEqual(client.calls, [])

    def test_coordinate_and_custom_region_require_observation_before_phone_access(self):
        runtime, client = self.runtime()
        invalid = [
            ("wda_tap", {"x": 10, "y": 200}),
            ("wda_tap", {"selector": {"label": "Target"}, "x": 10}),
            ("wda_swipe", {"region": {"x": 50, "y": 200, "width": 200, "height": 200}}),
        ]
        for name, arguments in invalid:
            with self.subTest(name=name, arguments=arguments), self.assertRaises(WDAError) as caught:
                runtime.call(name, arguments)
            self.assertEqual(caught.exception.code, "invalid_argument")
        self.assertEqual(client.calls, [])

    def test_other_process_holding_operation_lock_refuses_all_phone_requests(self):
        runtime, client = self.runtime()
        script = "import fcntl,sys; lock=open(sys.argv[1], 'a'); fcntl.flock(lock, fcntl.LOCK_EX); print('locked', flush=True); sys.stdin.read(); lock.close()"
        worker = subprocess.Popen(
            [sys.executable, "-c", script, str(Path(self.directory.name) / "operation.lock")],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            self.assertEqual(worker.stdout.readline().strip(), "locked")
            with self.assertRaises(WDAError) as caught:
                runtime.call("wda_tap", {"selector": {"label": "Target"}, "observe": "none"})
            self.assertEqual(caught.exception.code, "device_busy")
            self.assertEqual(client.calls, [])
        finally:
            try:
                worker.communicate(input="release", timeout=3)
            except subprocess.TimeoutExpired:
                worker.kill()
                worker.communicate()
        self.assertEqual(worker.returncode, 0)

    def test_independent_runtimes_share_usable_session_without_new_phone_request(self):
        first, first_client = self.runtime()
        second, second_client = self.runtime()
        first_client.session_id = "shared-session-123"
        with patch.object(first, "_call", side_effect=lambda name, args: {"session_id": first.client.session_id}):
            self.assertEqual(first.call("wda_metrics", {}), {"session_id": "shared-session-123"})
        self.assertIsNone(second_client.session_id)
        with patch.object(second, "_call", side_effect=lambda name, args: {"session_id": second.client.session_id}):
            self.assertEqual(second.call("wda_metrics", {}), {"session_id": "shared-session-123"})
        self.assertEqual(first_client.calls + second_client.calls, [])
        cache = Path(self.directory.name) / "session.json"
        self.assertEqual(json.loads(cache.read_text()), {"url": first.base_url, "session_id": "shared-session-123"})
        self.assertEqual(cache.stat().st_mode & 0o777, 0o600)

    def test_locked_phone_blocks_mutations_before_semantic_lookup(self):
        runtime, client = self.runtime()
        client.locked = True
        with self.assertRaises(WDAError) as caught:
            runtime.call("wda_tap", {"selector": {"label": "Target"}, "observe": "none"})
        self.assertEqual(caught.exception.code, "phone_locked")
        self.assertEqual(client.calls, [("GET", "/wda/locked", None)])
        self.assertEqual(client.actions(), [])

    def test_ready_requires_unlocked_phone_before_session_or_observation(self):
        runtime, client = self.runtime()
        client.locked = True
        with self.assertRaises(WDAError) as caught:
            runtime.call("wda_ready", {"screenshot": False})
        self.assertEqual(caught.exception.code, "phone_locked")
        self.assertEqual(client.calls, [("GET", "/status", None), ("GET", "/wda/locked", None)])
        self.assertIsNone(client.session_id)

    def test_ready_empty_tree_with_mirroring_running_reports_conflict(self):
        runtime, client = self.runtime()
        client.nodes = []
        with patch.object(runtime.setup_manager, "mirroring_running", return_value=True), self.assertRaises(WDAError) as caught:
            runtime.call("wda_ready", {"screenshot": False})
        self.assertEqual(caught.exception.code, "mirroring_conflict")
        self.assertFalse(any(path in ("/wda/tap", "/wda/keys") for _, path, _ in client.actions()))

    def test_ready_nonempty_tree_proves_unlocked_usable_phone(self):
        runtime, client = self.runtime()
        with patch.object(runtime.setup_manager, "mirroring_running", return_value=False):
            result = runtime.call("wda_ready", {"screenshot": False})
        self.assertTrue(result["ready"])
        self.assertTrue(result["proof"]["phone_unlocked"])
        self.assertTrue(result["proof"]["session_usable"])
        self.assertGreater(result["observation"]["total_nodes"], 0)


if __name__ == "__main__":
    unittest.main()
