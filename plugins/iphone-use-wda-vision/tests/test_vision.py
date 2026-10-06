"""Regression tests for efficient screenshot-based iPhone operations."""
import base64
import copy
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch
import zlib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))
from wda_client import WDAError
from wda_vision_controller import VisualPhoneController


def png(width=780, height=1688, colour=(20, 40, 60)):
    """A real, deterministic RGB PNG with valid chunks, CRCs and scanlines."""
    def chunk(kind, body):
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body) & 0xffffffff)
    scanline = b"\0" + bytes(colour) * width
    return (b"\x89PNG\r\n\x1a\n" +
            chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)) +
            chunk(b"IDAT", zlib.compress(scanline * height)) + chunk(b"IEND", b""))


class FakeVisualWDA:
    """Fail immediately if a default operation attempts semantic UI access."""
    def __init__(self):
        self.calls = []
        self.timeouts = []
        self.session_id = None
        self.closed = 0
        self.locked = False
        self.status_ready = True
        self.app = "com.example.phone"
        self.size = {"width": 390, "height": 844}
        self.screenshot = png()
        self.screenshot_error = None
        self.screenshot_failure_after_mutation = None
        self.foreground_sequence = None
        self.foreground_error = None
        self.allow_source = False
        self.source_xml = ('<AppiumAUT><XCUIElementTypeApplication type="XCUIElementTypeApplication" '
                           'name="Example" x="0" y="0" width="390" height="844">'
                           '<XCUIElementTypeStaticText type="XCUIElementTypeStaticText" '
                           'name="row" label="Balance" value="42" x="70" y="200" width="250" height="44"/>'
                           '<XCUIElementTypeButton type="XCUIElementTypeButton" '
                           'label="Continue" x="70" y="300" width="250" height="44"/>'
                           '</XCUIElementTypeApplication></AppiumAUT>')
        self.mutation_error = None
        self.mutation_effect = None
        self.activate_effective = True
        self.home_effective = True

    def close(self):
        self.closed += 1

    def ensure_session(self):
        if not self.session_id:
            self.calls.append(("POST", "/session", None))
            self.session_id = "fake-session"
        return self.session_id

    def forbidden(self, path):
        if path.startswith("/source"):
            if self.allow_source:
                return self.source_xml
            raise AssertionError("Default visual flow attempted XML: " + path)
        if path == "/elements" or path.startswith("/element/"):
            raise AssertionError("Visual flow attempted an element endpoint: " + path)
        return None

    def request(self, method, path, payload=None, timeout=None):
        self.calls.append((method, path, copy.deepcopy(payload)))
        self.timeouts.append((method, path, timeout))
        self.forbidden(path)
        if path == "/wda/activeAppInfo":
            if self.foreground_error:
                raise self.foreground_error
            if self.foreground_sequence:
                self.app = self.foreground_sequence.pop(0)
            return {"value": {"bundleId": self.app}}
        if path == "/screenshot":
            if self.screenshot_error:
                raise self.screenshot_error
            return {"value": base64.b64encode(self.screenshot).decode("ascii")}
        if path == "/wda/locked":
            return {"value": self.locked}
        if path == "/status":
            return {"value": {"ready": self.status_ready}}
        if method == "POST" and path == "/wda/homescreen":
            self.mutate(path, payload)
            if self.home_effective:
                self.app = "com.apple.springboard"
            return {"value": None}
        raise AssertionError("Unexpected request: " + path)

    def session(self, method, path, payload=None, timeout=None):
        self.ensure_session()
        self.calls.append((method, path, copy.deepcopy(payload)))
        self.timeouts.append((method, path, timeout))
        source = self.forbidden(path)
        if source is not None:
            return source
        if path == "/window/size":
            return self.size.copy()
        if method == "POST" and path in ("/wda/tap", "/wda/touchAndHold", "/wda/dragfromtoforduration",
                                           "/wda/swipe", "/wda/keys", "/wda/pressButton", "/wda/apps/activate"):
            self.mutate(path, payload)
            if path == "/wda/apps/activate" and self.activate_effective:
                self.app = payload["bundleId"]
            return None
        raise AssertionError("Unexpected session request: " + path)

    def mutate(self, path, payload):
        if self.mutation_error:
            raise self.mutation_error
        if self.mutation_effect:
            self.mutation_effect(path, payload)
        if self.screenshot_failure_after_mutation:
            self.screenshot_error = self.screenshot_failure_after_mutation

    def actions(self):
        return [(m, p, b) for m, p, b in self.calls if m == "POST" and p != "/session"]

    def metrics(self):
        return {"retained_requests": len(self.calls), "http_seconds": 0,
                "errors": 0, "endpoints": {p: {"count": 1} for _, p, _ in self.calls}}


class VisualControllerTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.client = FakeVisualWDA()
        self.phone = VisualPhoneController(self.client, self.directory.name)

    def assert_code(self, code, operation):
        with self.assertRaises(WDAError) as caught:
            operation()
        self.assertEqual(caught.exception.code, code)
        return caught.exception

    def observation(self):
        return self.phone.observe()

    def assert_visual_result(self, result):
        self.assertTrue(result["action_executed"])
        self.assertTrue(result["action_complete"])
        self.assertFalse(result["verified"])
        self.assertTrue(result["visual_verification_required"])
        image = result["observation"]["image"]
        self.assertTrue(Path(image["path"]).is_file())
        self.assertEqual(Path(image["path"]).read_bytes(), self.client.screenshot)

    def test_observe_reads_each_screenshot_context_endpoint_exactly_once(self):
        observed = self.observation()
        self.assertEqual(observed["mode"], "screenshot")
        self.assertEqual(observed["app"], self.client.app)
        self.assertEqual(observed["viewport"]["units"], "iPhone points")
        self.assertEqual(observed["image_dimensions"], {"width": 780, "height": 1688})
        self.assertEqual(observed["pixel_to_point"], {"x": .5, "y": .5})
        self.assertEqual(observed["image"]["pixel_to_point"], {"x": .5, "y": .5})
        self.assertNotIn("nodes", observed)
        self.assertNotIn("total_nodes", observed)
        self.assertEqual(Path(observed["image"]["path"]).stat().st_mode & 0o777, 0o600)
        reads = [(method, path) for method, path, _ in self.client.calls if method == "GET"]
        self.assertCountEqual(reads, [("GET", "/screenshot"), ("GET", "/window/size"),
                                    ("GET", "/wda/activeAppInfo")])
        self.assertEqual(len(reads), 3)
        self.assertNotIn("image_signature", self.phone.snapshots[observed["observation_id"]])

    def test_foreground_metadata_failures_do_not_discard_usable_screenshot(self):
        for app, error in (("local.pid.0", None), ("", None),
                           ("com.example.phone", WDAError("wda_unreachable", "Active app info unavailable"))):
            with self.subTest(app=app, error=error):
                self.client.app = app
                self.client.foreground_error = error
                self.client.calls.clear()
                observed = self.observation()
                self.assertIsNone(observed["app"])
                self.assertTrue(observed["foreground_error"]["code"])
                self.assertTrue(observed["warnings"])
                self.assertEqual(Path(observed["image"]["path"]).read_bytes(), self.client.screenshot)
                reads = [path for method, path, _ in self.client.calls if method == "GET"]
                self.assertCountEqual(reads, ["/wda/activeAppInfo", "/window/size", "/screenshot"])
                self.assertEqual(len(self.client.actions()), 0)

    def test_nonuniform_pixel_ratios_are_explicit(self):
        self.client.screenshot = png(195, 422)
        self.client.size["height"] = 800
        observed = self.observation()
        self.assertEqual(observed["pixel_to_point"]["x"], 2)
        self.assertAlmostEqual(observed["pixel_to_point"]["y"], 800 / 422)

    def test_invalid_screenshot_header_and_dimensions_fail(self):
        for data in (b"not png", b"\x89PNG\r\n\x1a\n", png(0, 1)):
            with self.subTest(data=data[:20]):
                self.client.screenshot = data
                self.assert_code("invalid_response", self.observation)
                self.assertFalse(self.phone.snapshots)

    def test_tap_uses_cached_points_without_any_pre_action_read(self):
        observed = self.observation()
        self.client.calls.clear()
        result = self.phone.tap(100, 220, observed["observation_id"])
        self.assert_visual_result(result)
        self.assertNotEqual(result["observation"]["observation_id"], observed["observation_id"])
        self.assertEqual(self.client.calls[0], ("POST", "/wda/tap", {"x": 100, "y": 220}))
        self.assertEqual(len(self.client.calls), 4)
        self.assertCountEqual([path for method, path, _ in self.client.calls if method == "GET"],
                              ["/screenshot", "/window/size", "/wda/activeAppInfo"])

    def test_clock_caret_age_and_foreground_changes_do_not_gate_cached_actions(self):
        observed = self.observation()
        self.phone.snapshots[observed["observation_id"]]["time"] = 0
        self.client.screenshot = png(colour=(60, 40, 20))
        self.client.app = "com.example.other"
        self.client.calls.clear()
        result = self.phone.tap(100, 220, observed["observation_id"])
        self.assert_visual_result(result)
        self.assertEqual(self.client.calls[0][1], "/wda/tap")
        self.assertEqual(len(self.client.actions()), 1)

    def test_unknown_optional_id_uses_latest_cached_geometry(self):
        self.observation()
        self.client.calls.clear()
        result = self.phone.tap(100, 220, "another-process-id", observe=False)
        self.assertTrue(result["action_complete"])
        self.assertEqual(self.client.calls, [("POST", "/wda/tap", {"x": 100, "y": 220})])

    def test_no_id_and_no_cache_fetches_geometry_only_before_tap(self):
        result = self.phone.tap(100, 220, observe=False)
        self.assertTrue(result["action_executed"])
        self.assertFalse(result["verified"])
        reads = [path for method, path, _ in self.client.calls if method == "GET"]
        self.assertEqual(reads, ["/window/size"])
        self.assertEqual(self.client.actions(), [("POST", "/wda/tap", {"x": 100, "y": 220})])
        self.assertNotIn("observation", result)

    def test_same_id_can_be_reused_for_explicit_known_coordinate_sequence(self):
        observed = self.observation()
        self.phone.tap(100, 220, observed["observation_id"], observe=False)
        result = self.phone.tap(110, 240, observed["observation_id"])
        self.assert_visual_result(result)
        self.assertEqual(len(self.client.actions()), 2)

    def test_long_press_is_one_gesture_with_screenshot_afterward(self):
        observed = self.observation()
        result = self.phone.long_press(100, 220, observed["observation_id"], duration=.8)
        self.assert_visual_result(result)
        self.assertEqual(self.client.actions(), [("POST", "/wda/touchAndHold", {"x": 100, "y": 220, "duration": .8})])

    def test_swipe_runs_once_even_if_image_does_not_change(self):
        self.observation()
        result = self.phone.swipe(direction="up")
        self.assert_visual_result(result)
        self.assertEqual(len(self.client.actions()), 1)
        self.assertIn(self.client.actions()[0][1], ("/wda/dragfromtoforduration", "/wda/swipe"))

    def test_custom_swipe_region_without_screenshot_id(self):
        self.observation()
        result = self.phone.swipe(direction="down", region={"x": 40, "y": 100, "width": 300, "height": 500})
        self.assert_visual_result(result)
        self.assertEqual(len(self.client.actions()), 1)

    def test_outside_viewport_coordinate_or_region_never_mutates(self):
        self.observation()
        for operation in (lambda: self.phone.tap(400, 220),
                          lambda: self.phone.long_press(100, 900),
                          lambda: self.phone.swipe(region={"x": 300, "y": 100, "width": 200, "height": 100})):
            self.assert_code("invalid_argument", operation)
        self.assertEqual(self.client.actions(), [])

    def test_text_requires_only_text_and_uses_global_keys(self):
        result = self.phone.type_text("视觉输入 👋")
        self.assert_visual_result(result)
        self.assertEqual(self.client.actions(), [("POST", "/wda/keys", {"value": list("视觉输入 👋")})])

    def test_legacy_focus_flags_do_not_block_typing(self):
        result = self.phone.type_text("hello", focused_input_confirmed=False, multiline_confirmed=False)
        self.assert_visual_result(result)
        self.assertEqual(len(self.client.actions()), 1)

    def test_newlines_require_only_explicit_intent(self):
        for kwargs in ({}, {"multiline_confirmed": True}):
            with self.subTest(kwargs=kwargs):
                self.assert_code("newline_requires_intent", lambda: self.phone.type_text("line 1\nline 2", **kwargs))
        self.assertEqual(self.client.actions(), [])
        result = self.phone.type_text("line 1\nline 2", allow_newlines=True)
        self.assert_visual_result(result)
        self.assertEqual(self.client.actions()[0], ("POST", "/wda/keys", {"value": list("line 1\nline 2")}))

    def test_control_characters_do_not_become_keyboard_commands(self):
        for value in ("abc\x00", "abc\t", "abc\x08", "abc\x7f"):
            with self.subTest(text=repr(value)):
                self.assert_code("invalid_argument", lambda: self.phone.type_text(value))
        self.assertEqual(self.client.actions(), [])

    def test_launch_and_home_require_no_observation_or_before_reads(self):
        self.client.session_id = "fake-session"
        for operation, endpoint in ((lambda: self.phone.launch_app("com.example.other"), "/wda/apps/activate"),
                                    (lambda: self.phone.press_button("home"), "/wda/homescreen")):
            with self.subTest(endpoint=endpoint):
                self.client.calls.clear()
                result = operation()
                self.assert_visual_result(result)
                self.assertTrue(result["foreground_verified"])
                self.assertEqual(self.client.calls[0][1], endpoint)
                self.assertEqual(len(self.client.calls), 4)

    def test_launch_mismatch_reports_foreground_status_without_polling_or_error(self):
        self.client.activate_effective = False
        self.client.session_id = "fake-session"
        result = self.phone.launch_app("com.example.other")
        self.assert_visual_result(result)
        self.assertFalse(result["foreground_verified"])
        self.assertEqual(len(self.client.calls), 4)
        self.assertEqual([path for method, path, _ in self.client.calls if method == "GET"].count("/wda/activeAppInfo"), 1)

    def test_home_mismatch_reports_foreground_status_without_polling_or_error(self):
        self.client.home_effective = False
        result = self.phone.press_button("home")
        self.assert_visual_result(result)
        self.assertFalse(result["foreground_verified"])
        self.assertEqual(len(self.client.actions()), 1)

    def test_capture_can_be_skipped_for_all_mutation_kinds(self):
        self.observation()
        operations = (lambda: self.phone.tap(100, 220, observe=False),
                      lambda: self.phone.long_press(100, 220, observe=False),
                      lambda: self.phone.swipe(observe=False),
                      lambda: self.phone.type_text("text", observe=False),
                      lambda: self.phone.launch_app("com.example.other", observe=False),
                      lambda: self.phone.press_button("home", observe=False))
        for operation in operations:
            self.client.calls.clear()
            result = operation()
            self.assertTrue(result["action_executed"])
            self.assertTrue(result["action_complete"])
            self.assertFalse(result["verified"])
            self.assertNotIn("observation", result)
            self.assertEqual(len(self.client.calls), 1)
            self.assertEqual(self.client.calls[0][0], "POST")

    def test_post_action_capture_failure_preserves_dispatch_evidence(self):
        observed = self.observation()
        self.client.screenshot_failure_after_mutation = WDAError("wda_unreachable", "Screenshot failed")
        error = self.assert_code("wda_unreachable", lambda: self.phone.tap(100, 220, observed["observation_id"]))
        self.assertTrue(error.as_dict()["action_executed"])
        self.assertFalse(error.as_dict()["action_complete"])
        self.assertTrue(error.as_dict()["visual_verification_required"])
        self.assertFalse(error.as_dict()["recovery"]["replay_action"])
        self.assertEqual(len(self.client.actions()), 1)

    def test_uncertain_mutation_is_not_automatically_replayed(self):
        self.observation()
        self.client.mutation_error = WDAError("action_uncertain", "Transport timeout", uncertain=True)
        error = self.assert_code("action_uncertain", lambda: self.phone.tap(100, 220))
        self.assertTrue(error.uncertain)
        self.assertTrue(error.as_dict()["visual_verification_required"])
        self.assertEqual(len(self.client.actions()), 1)

    def test_wait_returns_a_screenshot_without_semantic_polling(self):
        with patch("wda_vision_controller.time.sleep") as sleep:
            result = self.phone.wait(seconds=.5)
        sleep.assert_called_once_with(.5)
        self.assertIn("image", result["observation"])
        self.assertEqual(self.client.actions(), [])

    def test_optional_xml_reads_compact_data_without_invalidating_screenshot(self):
        observed = self.observation()
        self.client.allow_source = True
        result = self.phone.read_page(max_nodes=100)
        self.assertEqual(result["purpose"], "data_reading_only")
        self.assertNotIn("observation_id", result)
        encoded = json.dumps(result)
        self.assertIn("Balance", encoded)
        self.assertIn("42", encoded)
        for field in ("rect", "x", "y", "width", "height", "type", "hittable", "enabled"):
            self.assertNotIn('"' + field + '"', encoded)
        self.assertIn(observed["observation_id"], self.phone.snapshots)
        self.client.allow_source = False
        self.client.calls.clear()
        self.phone.tap(100, 220, observed["observation_id"], observe=False)
        self.assertEqual(self.client.calls, [("POST", "/wda/tap", {"x": 100, "y": 220})])

    def test_xml_read_reason_is_optional_and_node_limit_is_explicit(self):
        self.client.allow_source = True
        result = self.phone.read_page(max_nodes=1)
        self.assertLessEqual(len(result["nodes"]), 1)
        self.assertTrue(result["truncated"])
        self.assertEqual([path for method, path, _ in self.client.calls if method == "GET"], ["/source?format=xml&excluded_attributes=visible"])

    def test_batch_runs_supplied_known_steps_and_captures_only_final_state(self):
        self.observation()
        self.client.calls.clear()
        result = self.phone.batch(steps=[
            {"op": "tap", "args": {"x": 100, "y": 220, "observe": False}},
            {"op": "type_text", "args": {"text": "known text", "observe": False}},
            {"op": "press_button", "args": {"name": "home", "observe": False}},
        ])
        self.assertTrue(result["complete"])
        self.assertEqual(result["completed_steps"], 3)
        self.assertEqual(len(self.client.actions()), 3)
        self.assertEqual([path for method, path, _ in self.client.calls if method == "GET"].count("/screenshot"), 1)
        images = [step.get("observation", {}).get("image") for step in result["results"]]
        self.assertTrue(result.get("observation", {}).get("image") or any(images))

    def test_batch_defaults_to_one_final_capture_and_honors_explicit_capture(self):
        self.observation()
        self.client.calls.clear()
        steps = [
            {"op": "tap", "args": {"x": 100, "y": 220}},
            {"op": "type_text", "args": {"text": "known text"}},
        ]
        result = self.phone.batch(steps)
        self.assertTrue(result["complete"])
        self.assertEqual(len(self.client.calls), 5)
        self.assertEqual([path for _, path, _ in self.client.calls],
                         ["/wda/tap", "/wda/keys", "/screenshot", "/window/size", "/wda/activeAppInfo"])
        self.assertNotIn("observe", steps[0]["args"])
        self.client.calls.clear()
        steps[0]["args"]["observe"] = True
        result = self.phone.batch(steps)
        self.assertTrue(result["complete"])
        self.assertEqual([path for _, path, _ in self.client.calls].count("/screenshot"), 2)

    def test_batch_stops_at_actual_error_without_replaying_uncertain_step(self):
        self.observation()
        def fail_keys(path, _payload):
            if path == "/wda/keys":
                raise WDAError("action_uncertain", "Timeout after typing", uncertain=True)
        self.client.mutation_effect = fail_keys
        result = self.phone.batch(steps=[
            {"op": "tap", "args": {"x": 100, "y": 220, "observe": False}},
            {"op": "type_text", "args": {"text": "text", "observe": False}},
            {"op": "press_button", "args": {"name": "home", "observe": False}},
        ])
        self.assertFalse(result["complete"])
        self.assertEqual(result["completed_steps"], 1)
        self.assertEqual(result["stopped_at"], 1)
        self.assertEqual(result["error"]["code"], "action_uncertain")
        self.assertEqual([path for _, path, _ in self.client.actions()], ["/wda/tap", "/wda/keys"])

    def test_batch_final_capture_failure_preserves_all_executed_steps(self):
        self.observation()
        self.client.screenshot_failure_after_mutation = WDAError("wda_unreachable", "Screenshot failed")
        result = self.phone.batch(steps=[
            {"op": "tap", "args": {"x": 100, "y": 220, "observe": False}},
            {"op": "press_button", "args": {"name": "home", "observe": False}},
        ])
        self.assertTrue(result["complete"])
        self.assertEqual(result["completed_steps"], 2)
        self.assertEqual(result["observation_error"]["code"], "wda_unreachable")
        self.assertTrue(result["action_executed"])
        self.assertTrue(all(step["action_executed"] for step in result["results"]))
        self.assertEqual(len(self.client.actions()), 2)


if __name__ == "__main__":
    unittest.main()
