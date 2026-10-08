import http.client
import importlib.util
import json
from pathlib import Path
import threading
import unittest
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("browser_preview", ROOT / "scripts/preview.py")
preview = importlib.util.module_from_spec(spec)
spec.loader.exec_module(preview)


class BrowserPreviewTests(unittest.TestCase):
    def setUp(self):
        self.state = {"paused": False, "pause_reason": None}
        self.runtime = Mock(base_url="http://127.0.0.1:18100")
        self.runtime.screen.pause_status.side_effect = lambda: dict(self.state)
        def pause(paused, reason):
            self.state.update(paused=paused, pause_reason=reason)
        self.runtime.screen.set_paused.side_effect = pause
        self.runtime.call.side_effect = lambda name, args: {**self.state, "frame": None if self.state["paused"] else {"seq": 1, "data": "private-frame"}}
        self.probe = Mock()
        self.probe.request.return_value = {"value": False}
        with patch.object(preview, "WDAClient", return_value=self.probe):
            self.server = preview.PreviewServer(self.runtime, token="test-key")
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.close)

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def request(self, path="/test-key/rpc", params=None, headers=None, method="POST"):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)
        body = json.dumps(params or {"name": "pua_screen_frame", "arguments": {}}) if method == "POST" else None
        connection.request(method, path, body=body, headers=headers or {})
        response = connection.getresponse()
        body = response.read()
        connection.close()
        return response.status, body

    def test_widget_is_served_but_foreign_origin_wrong_key_and_dns_rebinding_are_rejected(self):
        status, body = self.request(path="/test-key/widget", method="GET")
        self.assertEqual(status, 200)
        self.assertIn('lang="ja"'.encode(), body)
        for path, headers in (("/wrong/rpc", {}), ("/test-key/rpc", {"Origin": "https://outside.invalid"}), ("/test-key/rpc", {"Host": "outside.invalid"})):
            with self.subTest(path=path, headers=headers):
                self.assertEqual(self.request(path, headers=headers)[0], 403)
        self.runtime.call.assert_not_called()

    def test_preview_endpoint_cannot_call_phone_operations(self):
        self.assertEqual(self.request(params={"name": "pua_type_text", "arguments": {"text": "send"}})[0], 400)
        self.runtime.call.assert_not_called()

    def test_locked_phone_does_not_expose_frames_and_unlock_does_not_resume_automatically(self):
        self.probe.request.return_value = {"value": True}
        status, body = self.request()
        self.assertEqual(status, 200)
        self.assertIsNone(json.loads(body)["structuredContent"]["frame"])
        self.assertEqual(self.state["pause_reason"], "device_locked")
        self.probe.request.return_value = {"value": False}
        self.server.last_probe = 0
        self.assertIsNone(json.loads(self.request()[1])["structuredContent"]["frame"])

    def test_authentication_pause_stops_lock_probes(self):
        self.state.update(paused=True, pause_reason="authentication")
        self.request()
        self.probe.request.assert_not_called()

    def test_failed_lock_probe_never_allows_a_following_frame_request(self):
        self.probe.request.side_effect = preview.PUAError("pua_unreachable", "offline")
        for _ in range(2):
            self.assertTrue(json.loads(self.request()[1])["isError"])
        self.runtime.call.assert_not_called()
        self.assertEqual(self.probe.request.call_count, 2)


if __name__ == "__main__":
    unittest.main()
