"""Bounded WDA channel recovery without repeating the user's phone actions."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))
from iphone_wda import Runtime
from wda_client import WDAError
from wda_controller import PhoneController
from test_controller import FakeWDA


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.runtime = Runtime(self.directory.name)
        self.addCleanup(self.runtime.close)
        self.client = FakeWDA()
        self.client.close = Mock()
        self.runtime.client = self.client
        self.runtime.phone = PhoneController(self.client, self.directory.name)
        self.manager = Mock()
        self.manager.mirroring_running.return_value = False
        self.manager.pending_recovery.return_value = None
        self.manager.recover.return_value = {"ok": True, "job_id": "recovery-test", "recovery": {"state": "queued"}}
        self.runtime.setup_manager = self.manager

    def assert_error(self, code, tool="wda_ready", **args):
        with self.assertRaises(WDAError) as caught:
            self.runtime.call(tool, args)
        self.assertEqual(caught.exception.code, code)
        return caught.exception.as_dict()

    def assert_no_phone_mutation(self):
        self.assertEqual([path for _, path, _ in self.client.actions() if path != "/session"], [])

    def test_transient_foreground_failure_retries_only_fresh_read_once(self):
        original = self.client.request
        attempts = []

        def request(method, path, payload=None, timeout=None):
            if path == "/wda/activeAppInfo":
                attempts.append(path)
                if len(attempts) == 1:
                    self.client.calls.append((method, path, payload))
                    return {"value": {"bundleId": "local.pid.0"}}
            return original(method, path, payload, timeout)

        with patch.object(self.client, "request", side_effect=request):
            result = self.runtime.call("wda_ready", {"screenshot": False})
        self.assertTrue(result["ready"])
        self.assertTrue(result["proof"]["foreground_resolved"])
        self.assertTrue(result["recovery"]["session_recreated"])
        self.assertFalse(result["recovery"]["replayed_action"])
        self.assertEqual(len(attempts), 2)
        self.assertEqual(sum(path == "/session" for _, path, _ in self.client.calls), 2)
        self.manager.recover.assert_not_called()
        self.assert_no_phone_mutation()

    def test_persistent_foreground_error_queues_recovery_and_explicit_poll_guidance(self):
        self.client.app = "local.pid.0"
        error = self.assert_error("wda_recovering", screenshot=False)
        self.assertFalse(error["ready"])
        self.assertFalse(error["action_executed"])
        self.assertEqual(error["category"], "channel_runtime")
        self.assertTrue(error["session_read_retried"])
        self.assertEqual(error["cause"]["code"], "wda_foreground_unavailable")
        self.assertEqual(error["recovery"]["status_tool"], "wda_setup")
        self.assertEqual(error["recovery"]["status_arguments"], {"action": "status", "job_id": "recovery-test"})
        self.assertEqual(error["recovery"]["next_tool"], "wda_ready")
        self.assertFalse(error["recovery"]["replay_action"])
        self.manager.recover.assert_called_once_with()
        self.assertEqual(sum(path == "/session" for _, path, _ in self.client.calls), 2)
        self.assert_no_phone_mutation()

    def test_local_pid_stale_error_from_source_uses_same_bounded_recovery(self):
        fault = WDAError("stale element reference", "Application local.pid.0 is not running")
        with patch.object(self.client, "source", side_effect=fault) as source:
            error = self.assert_error("wda_recovering", screenshot=False)
        self.assertEqual(source.call_count, 2)
        self.assertTrue(error["session_read_retried"])
        self.manager.recover.assert_called_once_with()
        self.assert_no_phone_mutation()

    def test_diagnose_mode_explains_runtime_failure_without_service_restart(self):
        self.client.app = "local.pid.0"
        error = self.assert_error("wda_recovery_required", screenshot=False, recover=False)
        self.assertFalse(error["ready"])
        self.assertTrue(error["session_read_retried"])
        self.assertEqual(error["category"], "channel_runtime")
        self.manager.recover.assert_not_called()
        self.assert_no_phone_mutation()

    def test_authorization_code_41_skips_session_read_retry_and_queues_recovery(self):
        fault = WDAError("unknown error", "Error Domain=XCTDaemonErrorDomain Code=41 Not authorized for performing UI testing actions")
        with patch.object(self.client, "source", side_effect=fault) as source:
            error = self.assert_error("wda_recovering", screenshot=False)
        self.assertEqual(source.call_count, 1)
        self.assertFalse(error["session_read_retried"])
        self.manager.recover.assert_called_once_with()
        self.assert_no_phone_mutation()

    def test_unproven_service_owner_never_claims_recovery_started(self):
        self.client.app = "local.pid.0"
        self.manager.recover.return_value = {"ok": False, "error": "owned service not found", "next_steps": ["Use the original owner to restart WDA"]}
        error = self.assert_error("wda_recovery_required", screenshot=False)
        self.assertFalse(error["ready"])
        self.assertIn("owned service", error["message"])
        self.assertNotIn("job_id", error["recovery"])
        self.assertFalse(error["recovery"]["replay_action"])
        self.assert_no_phone_mutation()

    def test_pending_service_recovery_handles_temporarily_unreachable_status(self):
        self.manager.pending_recovery.return_value = {"job_id": "in-flight", "state": "restarting"}
        fault = WDAError("wda_unreachable", "Service is restarting")
        with patch.object(self.client, "request", side_effect=fault):
            error = self.assert_error("wda_recovering", screenshot=False)
        self.assertEqual(error["recovery"]["job_id"], "in-flight")
        self.manager.recover.assert_not_called()
        self.assert_no_phone_mutation()

    def test_locked_phone_never_recreates_session_or_restarts_service(self):
        self.client.locked = True
        error = self.assert_error("phone_locked", screenshot=False)
        self.assertEqual(error["code"], "phone_locked")
        self.assertIsNone(self.client.session_id)
        self.manager.recover.assert_not_called()
        self.client.close.assert_not_called()
        self.assert_no_phone_mutation()

    def test_phone_lock_during_foreground_retry_stops_recovery(self):
        original = self.client.request

        def request(method, path, payload=None, timeout=None):
            result = original(method, path, payload, timeout)
            if path == "/wda/activeAppInfo":
                self.client.locked = True
                return {"value": {"bundleId": "local.pid.0"}}
            return result

        with patch.object(self.client, "request", side_effect=request):
            self.assert_error("phone_locked", screenshot=False)
        self.assertEqual(sum(path == "/session" for _, path, _ in self.client.calls), 1)
        self.assertIsNone(self.client.session_id)
        self.manager.recover.assert_not_called()
        self.assert_no_phone_mutation()

    def test_generic_stale_element_is_not_misclassified_as_channel_failure(self):
        fault = WDAError("stale element reference", "Previously found element Button 'Continue' is not present")
        with patch.object(self.client, "source", side_effect=fault) as source:
            error = self.assert_error("stale element reference", screenshot=False)
        self.assertEqual(source.call_count, 1)
        self.assertNotIn("category", error)
        self.manager.recover.assert_not_called()
        self.client.close.assert_not_called()
        self.assert_no_phone_mutation()

    def test_observe_foreground_failure_points_to_ready_without_restart(self):
        self.client.app = "local.pid.0"
        error = self.assert_error("wda_foreground_unavailable", tool="wda_observe", mode="tree")
        self.assertFalse(error["action_executed"])
        self.assertEqual(error["category"], "channel_runtime")
        self.assertEqual(error["recovery"]["tool"], "wda_ready")
        self.assertFalse(error["recovery"]["replay_action"])
        self.manager.recover.assert_not_called()
        self.client.close.assert_not_called()
        self.assert_no_phone_mutation()

    def test_successful_click_followed_by_stale_source_does_not_replay_click_or_restart(self):
        fault = WDAError("stale element reference", "Application local.pid.0 is not running")
        with patch.object(self.client, "source", side_effect=fault) as source:
            error = self.assert_error("stale element reference", tool="wda_tap", selector={"label": "Target"}, observe="tree")
        self.assertEqual(source.call_count, 1)
        self.assertEqual([path for _, path, _ in self.client.actions()], ["/element/target/click"])
        self.assertEqual(self.runtime.phone.accepted_actions, 1)
        self.assertTrue(error["action_executed"])
        self.assertFalse(error["action_complete"])
        self.assertIn("verification_required", error)
        self.manager.recover.assert_not_called()


if __name__ == "__main__":
    unittest.main()
