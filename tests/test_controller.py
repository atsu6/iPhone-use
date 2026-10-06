import base64
import copy
from pathlib import Path
import re
import sys
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))
from wda_client import WDAError
from wda_controller import ELEMENT_KEY, PhoneController


def node(label="Row 1", y=200, kind="Cell", **extra):
    return {"type": "XCUIElementType" + kind, "label": label, "name": label,
            "x": 60, "y": y, "width": 250, "height": 44, **extra}


class FakeWDA:
    def __init__(self):
        self.calls = []
        self.timeouts = []
        self.session_id = None
        self.locked = False
        self.status_ready = True
        self.app = "com.example.phone"
        self.size = {"width": 390, "height": 844}
        self.nodes = [node()]
        self.source_pages = None
        self.swipe_count = 0
        self.elements = [{"id": "target", "label": "Target", "kind": "XCUIElementTypeTextField",
                          "rect": {"x": 70, "y": 200, "width": 250, "height": 44},
                          "hittable": True, "value": ""}]
        self.input_override = None
        self.click_error = None
        self.home_effective = True
        self.home_error = None
        self.screenshot = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jXuoAAAAASUVORK5CYII=")

    def request(self, method, path, payload=None, timeout=None):
        self.calls.append((method, path, payload))
        if method == "POST" and path == "/wda/homescreen":
            if self.home_error:
                raise self.home_error
            if self.home_effective:
                self.app = "com.apple.springboard"
            return {"value": None}
        if path == "/wda/activeAppInfo":
            return {"value": {"bundleId": self.app}}
        if path == "/screenshot":
            return {"value": base64.b64encode(self.screenshot).decode("ascii")}
        if path == "/wda/locked":
            return {"value": self.locked}
        if path == "/status":
            return {"value": {"ready": self.status_ready}}
        raise AssertionError("Unexpected request: " + path)

    def ensure_session(self):
        if self.session_id is None:
            self.calls.append(("POST", "/session", None))
            self.session_id = "fake-session"
        return self.session_id

    def source(self):
        nodes = self.nodes if self.source_pages is None else self.source_pages[min(self.swipe_count, len(self.source_pages)-1)]
        root = ET.Element("AppiumAUT")
        for item in nodes:
            ET.SubElement(root, item["type"], {k: str(v).lower() if isinstance(v, bool) else str(v) for k, v in item.items()})
        return ET.tostring(root, encoding="unicode")

    def session(self, method, path, payload=None, timeout=None):
        self.calls.append((method, path, copy.deepcopy(payload)))
        self.timeouts.append((method, path, timeout))
        if path.startswith("/source"):
            return self.source()
        if path == "/window/size":
            return self.size.copy()
        if path == "/elements":
            value = payload["value"]
            labels = re.findall(r"label == '([^']*)'", value)
            matches = [item for item in self.elements if not labels or item["label"] == labels[0]]
            return [{ELEMENT_KEY: item["id"]} for item in matches]
        if path.startswith("/element/"):
            parts = path.split("/")
            element = next(item for item in self.elements if item["id"] == parts[2])
            suffix = "/".join(parts[3:])
            if suffix == "rect":
                return element["rect"].copy()
            if suffix == "attribute/hittable":
                return element["hittable"]
            if suffix == "attribute/type":
                return element["kind"]
            if suffix == "attribute/value":
                return element["value"]
            if suffix == "click":
                if self.click_error:
                    raise self.click_error
                return None
            if suffix == "clear":
                element["value"] = ""
                return None
            if suffix == "value":
                element["value"] = self.input_override if self.input_override is not None else element["value"] + payload["text"]
                return None
        if path in ("/wda/dragfromtoforduration", "/wda/swipe"):
            self.swipe_count += 1
            return None
        if path in ("/wda/tap", "/wda/keys", "/wda/pressButton"):
            return None
        raise AssertionError("Unexpected session request: " + path)

    def actions(self):
        return [(method, path, body) for method, path, body in self.calls if method == "POST" and path != "/elements"]


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.client = FakeWDA()
        self.phone = PhoneController(self.client, self.directory.name)

    def assert_code(self, code, operation):
        with self.assertRaises(WDAError) as caught:
            operation()
        self.assertEqual(caught.exception.code, code)
        return caught.exception

    def test_coordinate_tap_requires_fresh_observation(self):
        observed = self.phone.observe()
        result = self.phone.tap(x=100, y=220, observation_id=observed["observation_id"], observe="none")
        self.assertTrue(result["action_executed"])
        self.assertFalse(result["verified"])
        self.assertEqual(self.client.actions()[-1][1], "/wda/tap")
        self.phone.snapshots[observed["observation_id"]]["time"] -= 31
        self.client.calls.clear()
        self.assert_code("stale_observation", lambda: self.phone.tap(x=100, y=220, observation_id=observed["observation_id"], observe="none"))
        self.assertEqual(self.client.actions(), [])

    def test_changed_page_app_or_orientation_rejects_coordinate_action(self):
        for change in ("page", "app", "orientation"):
            with self.subTest(change=change):
                self.setUp()
                observed = self.phone.observe()
                if change == "page":
                    self.client.nodes = [node("Different page")]
                elif change == "app":
                    self.client.app = "com.example.other"
                else:
                    self.client.size = {"width": 844, "height": 390}
                self.client.calls.clear()
                self.assert_code("stale_observation", lambda: self.phone.tap(x=100, y=220, observation_id=observed["observation_id"], observe="none"))
                self.assertEqual(self.client.actions(), [])

    def test_screenshot_observation_skips_source_and_stores_private_artifact(self):
        result = self.phone.observe("screenshot")
        self.assertNotIn("nodes", result)
        self.assertFalse(any(path.startswith("/source") for _, path, _ in self.client.calls))
        path = Path(result["image"]["path"])
        self.assertEqual(path.parent, Path(self.directory.name) / "artifacts")
        self.assertEqual(path.read_bytes(), self.client.screenshot)
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_screenshot_coordinate_guard_allows_same_image_and_rejects_change(self):
        observed = self.phone.observe("screenshot")
        self.phone.tap(x=100, y=220, observation_id=observed["observation_id"], observe="none")
        self.assertEqual(self.client.actions()[-1][1], "/wda/tap")
        self.client.screenshot += b"changed picture"
        self.client.calls.clear()
        self.assert_code("stale_observation", lambda: self.phone.tap(x=100, y=220, observation_id=observed["observation_id"], observe="none"))
        self.assertEqual(self.client.actions(), [])
        self.assertFalse(any(path.startswith("/source") for _, path, _ in self.client.calls))

    def test_both_observation_rejects_changed_image_even_when_tree_is_identical(self):
        observed = self.phone.observe("both")
        original_nodes = copy.deepcopy(observed["nodes"])
        self.client.screenshot += b"custom-rendered content changed"
        self.client.calls.clear()
        self.assertEqual(self.phone.tree()[0], original_nodes)
        self.assert_code("stale_observation", lambda: self.phone.tap(x=100, y=220, observation_id=observed["observation_id"], observe="none"))
        self.assertEqual(self.client.actions(), [])

    def test_custom_scroll_ignores_carousel_changes_outside_region(self):
        area = {"x": 30, "y": 300, "width": 300, "height": 400}
        for mode in ("tree", "both"):
            with self.subTest(mode=mode):
                self.setUp()
                self.client.nodes = [node("Banner A", y=100), node("Row 1", y=400)]
                observed = self.phone.observe(mode)
                self.client.source_pages = [
                    [node("Banner B", y=100), node("Row 1", y=400)],
                    [node("Banner C", y=100), node("Row 2", y=400)],
                ]
                self.client.screenshot += b"changed carousel outside gesture area"
                self.client.calls.clear()
                result = self.phone.swipe(region=area, observation_id=observed["observation_id"])
                self.assertTrue(result["verified"])
                self.assertEqual(self.client.swipe_count, 1)
                self.assertEqual(self.client.actions()[0][1], "/wda/dragfromtoforduration")
                self.assertFalse(any(path == "/screenshot" for _, path, _ in self.client.calls))

    def test_custom_scroll_rejects_changed_target_region_before_gesture(self):
        area = {"x": 30, "y": 300, "width": 300, "height": 400}
        self.client.nodes = [node("Banner A", y=100), node("Row 1", y=400)]
        observed = self.phone.observe()
        self.client.nodes = [node("Banner A", y=100), node("Different list", y=400)]
        self.client.calls.clear()
        self.assert_code("stale_observation", lambda: self.phone.swipe(region=area, observation_id=observed["observation_id"]))
        self.assertEqual(self.client.actions(), [])

    def test_custom_scroll_rejects_new_modal_even_outside_gesture_region(self):
        area = {"x": 30, "y": 300, "width": 300, "height": 400}
        self.client.nodes = [node("Row 1", y=400)]
        observed = self.phone.observe()
        self.client.nodes.append(node("Blocking alert", y=100, kind="Alert"))
        self.client.calls.clear()
        self.assert_code("stale_observation", lambda: self.phone.swipe(region=area, observation_id=observed["observation_id"]))
        self.assertEqual(self.client.actions(), [])

    def test_custom_scroll_rejects_unlabeled_modal_appearing_or_disappearing(self):
        area = {"x": 30, "y": 300, "width": 300, "height": 400}
        for kind in ("Alert", "Sheet"):
            for appearing in (True, False):
                with self.subTest(kind=kind, appearing=appearing):
                    self.setUp()
                    modal = node("", y=100, kind=kind)
                    self.client.nodes = [node("Row 1", y=400)] + ([] if appearing else [modal])
                    observed = self.phone.observe("both")
                    self.client.nodes = [node("Row 1", y=400)] + ([modal] if appearing else [])
                    self.client.calls.clear()
                    self.assert_code("stale_observation", lambda: self.phone.swipe(region=area, observation_id=observed["observation_id"]))
                    self.assertEqual(self.client.actions(), [])

    def test_custom_scroll_guard_keeps_anchors_beyond_response_truncation(self):
        area = {"x": 30, "y": 300, "width": 300, "height": 400}
        self.client.nodes = [node("Banner", y=100), node("Row 1", y=400)]
        observed = self.phone.observe(max_nodes=1)
        self.assertTrue(observed["truncated"])
        self.client.source_pages = [self.client.nodes, [node("Banner", y=100), node("Row 2", y=400)]]
        result = self.phone.swipe(region=area, observation_id=observed["observation_id"])
        self.assertTrue(result["verified"])
        self.assertEqual(self.client.swipe_count, 1)

    def test_custom_scroll_rejects_expired_app_or_orientation_observation(self):
        # Keep the rectangle valid in both viewports so this exercises freshness,
        # rather than rejecting a region that falls outside the rotated screen.
        area = {"x": 30, "y": 100, "width": 300, "height": 250}
        for change in ("expired", "app", "orientation"):
            with self.subTest(change=change):
                self.setUp()
                self.client.nodes = [node("Row 1", y=200)]
                observed = self.phone.observe()
                if change == "expired":
                    self.phone.snapshots[observed["observation_id"]]["time"] -= 31
                elif change == "app":
                    self.client.app = "com.example.other"
                else:
                    self.client.size = {"width": 844, "height": 390}
                self.client.calls.clear()
                self.assert_code("stale_observation", lambda: self.phone.swipe(region=area, observation_id=observed["observation_id"]))
                self.assertEqual(self.client.actions(), [])

    def test_custom_scroll_refuses_screenshot_only_or_empty_region_anchors(self):
        area = {"x": 30, "y": 300, "width": 300, "height": 400}
        for condition in ("screenshot_only", "no_anchor"):
            with self.subTest(condition=condition):
                self.setUp()
                self.client.nodes = [node("Banner outside target", y=100)]
                observed = self.phone.observe("screenshot" if condition == "screenshot_only" else "tree")
                self.client.calls.clear()
                self.assert_code("stale_observation", lambda: self.phone.swipe(region=area, observation_id=observed["observation_id"]))
                self.assertEqual(self.client.actions(), [])

    def test_home_navigation_requires_foreground_evidence(self):
        result = self.phone.press_button("home", observe="none")
        self.assertTrue(result["action_executed"])
        self.assertTrue(result["verified"])
        self.assertTrue(result["foreground_verified"])
        self.assertEqual(self.client.app, "com.apple.springboard")
        self.assertEqual([path for _, path, _ in self.client.actions()], ["/wda/homescreen"])
        self.assertTrue(any(path == "/wda/activeAppInfo" for _, path, _ in self.client.calls))

    def test_home_http_success_without_foreground_change_is_failure(self):
        self.client.home_effective = False
        self.assert_code("postcondition_failed", lambda: self.phone.press_button("home", observe="none"))
        self.assertEqual(self.client.app, "com.example.phone")
        self.assertEqual([path for _, path, _ in self.client.actions()], ["/wda/homescreen"])

    def test_uncertain_home_navigation_is_not_replayed(self):
        self.client.home_error = WDAError("action_uncertain", "Timeout after sending Home", uncertain=True)
        error = self.assert_code("action_uncertain", lambda: self.phone.press_button("home", observe="none"))
        self.assertTrue(error.uncertain)
        self.assertEqual([path for _, path, _ in self.client.actions()], ["/wda/homescreen"])
        self.assertFalse(any(path == "/wda/activeAppInfo" for _, path, _ in self.client.calls))

    def test_home_post_action_read_failure_retains_execution_evidence(self):
        with patch.object(self.phone, "active_app", side_effect=WDAError("wda_unreachable", "read timed out")):
            error = self.assert_code("wda_unreachable", lambda: self.phone.press_button("home", observe="none"))
        self.assertTrue(error.details["action_executed"])
        self.assertFalse(error.details["home_foreground_verified"])
        self.assertEqual([path for _, path, _ in self.client.actions()], ["/wda/homescreen"])

    def test_volume_button_transport_success_remains_unverified(self):
        for name in ("volumeup", "volumedown"):
            with self.subTest(name=name):
                self.setUp()
                result = self.phone.press_button(name, observe="none")
                self.assertTrue(result["action_executed"])
                self.assertFalse(result["verified"])
                self.assertEqual(self.client.actions(), [("POST", "/wda/pressButton", {"name": name})])

    def test_exact_target_offscreen_or_occluded_is_not_clicked(self):
        for condition, code in (("offscreen", "offscreen_target"), ("occluded", "occluded_target")):
            with self.subTest(condition=condition):
                self.setUp()
                if condition == "offscreen":
                    self.client.elements[0]["rect"]["y"] = 900
                else:
                    self.client.elements[0]["hittable"] = False
                self.assert_code(code, lambda: self.phone.tap(selector={"label": "Target"}, observe="none"))
                self.assertEqual(self.client.actions(), [])

    def test_duplicate_exact_targets_require_disambiguation(self):
        second = copy.deepcopy(self.client.elements[0])
        second["id"] = "duplicate"
        self.client.elements.append(second)
        error = self.assert_code("ambiguous_target", lambda: self.phone.tap(selector={"label": "Target"}, observe="none"))
        self.assertEqual(error.details["matches"], 2)
        self.assertEqual(self.client.actions(), [])

    def test_unicode_text_round_trips_exactly_before_submit(self):
        text = "你好 👋 Café 漢字 e\u0301"
        result = self.phone.type_text({"label": "Target"}, text, submit=True, observe="none")
        self.assertTrue(result["exact_readback"])
        self.assertTrue(result["submitted"])
        self.assertFalse(result["submission_verified"])
        self.assertEqual(self.client.elements[0]["value"], text)
        paths = [call[1] for call in self.client.calls]
        self.assertLess(max(i for i, path in enumerate(paths) if path.endswith("/attribute/value")), paths.index("/wda/keys"))
        self.assertEqual(self.client.actions()[-1][2], {"value": ["\n"]})

    def test_input_mismatch_does_not_submit_or_retype(self):
        self.client.input_override = "你好 ?"
        self.assert_code("input_mismatch", lambda: self.phone.type_text({"label": "Target"}, "你好 👋", submit=True, observe="none"))
        paths = [call[1] for call in self.client.actions()]
        self.assertNotIn("/wda/keys", paths)
        self.assertEqual(paths.count("/element/target/value"), 1)

    def test_newline_in_single_line_field_is_blocked_even_with_intent(self):
        self.assert_code("newline_requires_intent", lambda: self.phone.type_text({"label": "Target"}, "a\nb", observe="none"))
        self.assert_code("newline_unsafe", lambda: self.phone.type_text({"label": "Target"}, "a\nb", allow_newlines=True, observe="none"))
        self.assertEqual(self.client.actions(), [])

    def test_explicit_multiline_text_view_round_trips(self):
        self.client.elements[0]["kind"] = "XCUIElementTypeTextView"
        result = self.phone.type_text({"label": "Target"}, "第一行\n第二行", allow_newlines=True, observe="none")
        self.assertTrue(result["exact_readback"])
        self.assertFalse(result["submitted"])

    def test_append_preserves_existing_text_and_verifies_combined_value(self):
        self.client.elements[0]["value"] = "Existing "
        result = self.phone.type_text({"label": "Target"}, "追加", replace=False, observe="none")
        self.assertTrue(result["verified"])
        self.assertEqual(self.client.elements[0]["value"], "Existing 追加")
        self.assertFalse(any(path.endswith("/clear") for _, path, _ in self.client.actions()))

    def test_no_scroll_progress_tries_only_two_distinct_strategies(self):
        error = self.assert_code("no_scroll_progress", lambda: self.phone.swipe())
        self.assertEqual(error.details["attempts"], 2)
        self.assertEqual([call[1] for call in self.client.actions()], ["/wda/dragfromtoforduration", "/wda/swipe"])

    def test_native_fallback_can_verify_progress(self):
        self.client.source_pages = [[node("Row 1")], [node("Row 1")], [node("Row 2")]]
        result = self.phone.swipe()
        self.assertTrue(result["verified"])
        self.assertEqual(result["attempts"], 2)
        self.assertEqual(result["strategy"], "native_swipe")
        self.assertEqual(result["observation"]["nodes"][0]["label"], "Row 2")

    def test_wait_caps_each_transport_request_at_two_seconds(self):
        with patch("wda_controller.time.monotonic", side_effect=[100.0, 100.1]):
            result = self.phone.wait({"label": "Target"}, timeout_seconds=8)
        self.assertTrue(result["verified"])
        self.assertEqual(self.client.timeouts, [("POST", "/elements", 2)])

    def test_wait_uses_remaining_deadline_for_later_poll(self):
        # The fake clock advances across a failed first query and the bounded sleep.
        original = self.client.session
        requests = []

        def first_missing_then_found(method, path, payload=None, timeout=None):
            requests.append(timeout)
            return [] if len(requests) == 1 else original(method, path, payload, timeout)

        with patch.object(self.client, "session", side_effect=first_missing_then_found), \
                patch("wda_controller.time.monotonic", side_effect=[100.0, 100.1, 100.2, 100.25, 100.9]), \
                patch("wda_controller.time.sleep") as sleeper:
            result = self.phone.wait({"label": "Target"}, timeout_seconds=1)
        self.assertTrue(result["verified"])
        self.assertEqual(result["polls"], 2)
        self.assertAlmostEqual(requests[0], 0.9)
        self.assertAlmostEqual(requests[1], 0.1)
        sleeper.assert_called_once_with(0.25)

    def test_zero_wait_performs_only_one_short_probe(self):
        self.client.elements.clear()
        with patch("wda_controller.time.monotonic", side_effect=[100.0, 100.0]):
            error = self.assert_code("postcondition_failed", lambda: self.phone.wait({"label": "Missing"}, timeout_seconds=0))
        self.assertEqual(error.details["polls"], 1)
        self.assertEqual(self.client.timeouts, [("POST", "/elements", 0.5)])

    def test_batch_stops_after_unverified_action(self):
        result = self.phone.batch([
            {"op": "tap", "args": {"selector": {"label": "Target"}, "observe": "none"}},
            {"op": "type_text", "args": {"selector": {"label": "Target"}, "text": "never", "observe": "none"}},
        ])
        self.assertFalse(result["complete"])
        self.assertEqual(result["completed_steps"], 1)
        self.assertEqual(result["stop_reason"], "verification_required")
        self.assertEqual([call[1] for call in self.client.actions()], ["/element/target/click"])

    def test_batch_stops_after_uncertain_error(self):
        self.client.click_error = WDAError("action_uncertain", "Timeout", uncertain=True)
        result = self.phone.batch([
            {"op": "tap", "args": {"selector": {"label": "Target"}, "observe": "none"}},
            {"op": "press_button", "args": {"name": "home", "observe": "none"}},
        ])
        self.assertFalse(result["complete"])
        self.assertEqual(result["completed_steps"], 0)
        self.assertTrue(result["error"]["uncertain"])
        self.assertEqual(result["stop_reason"], "action_uncertain")
        self.assertFalse(any(path == "/wda/pressButton" for _, path, _ in self.client.actions()))
        self.assertFalse(any(path == "/wda/homescreen" for _, path, _ in self.client.actions()))

    def test_batch_submission_is_a_verification_barrier(self):
        result = self.phone.batch([
            {"op": "type_text", "args": {"selector": {"label": "Target"}, "text": "Verified input", "submit": True, "observe": "none"}},
            {"op": "press_button", "args": {"name": "home", "observe": "none"}},
        ])
        self.assertEqual(result["stop_reason"], "submission_requires_verification")
        self.assertEqual(result["completed_steps"], 1)
        self.assertFalse(any(path == "/wda/pressButton" for _, path, _ in self.client.actions()))
        self.assertFalse(any(path == "/wda/homescreen" for _, path, _ in self.client.actions()))

    def test_batch_continues_after_verified_home_navigation(self):
        result = self.phone.batch([
            {"op": "press_button", "args": {"name": "home", "observe": "none"}},
            {"op": "observe", "args": {}},
        ])
        self.assertTrue(result["complete"])
        self.assertEqual(result["completed_steps"], 2)
        self.assertTrue(result["results"][0]["foreground_verified"])
        self.assertEqual([path for _, path, _ in self.client.actions()], ["/wda/homescreen"])

    def test_batch_completes_observation_and_verified_input_steps(self):
        result = self.phone.batch([
            {"op": "observe", "args": {}},
            {"op": "wait", "args": {"selector": {"label": "Target"}, "timeout_seconds": 0}},
            {"op": "type_text", "args": {"selector": {"label": "Target"}, "text": "Verified input", "observe": "none"}},
        ])
        self.assertTrue(result["complete"])
        self.assertEqual(result["completed_steps"], 3)
        self.assertEqual(self.client.elements[0]["value"], "Verified input")

    def test_collect_list_does_not_claim_completeness_at_page_budget(self):
        self.client.source_pages = [[node("Row 1")], [node("Row 2")]]
        result = self.phone.collect_list(max_pages=2)
        self.assertEqual([row["label"] for row in result["rows"]], ["Row 1", "Row 2"])
        self.assertEqual(len(result["pages"]), 2)
        self.assertEqual(result["stop_reason"], "page_budget")
        self.assertFalse(result["complete"])
        self.assertFalse(result["coverage_verified"])

    def test_end_marker_verifies_coverage_but_requires_business_reconciliation(self):
        self.client.elements[0]["label"] = "End"
        result = self.phone.collect_list(max_pages=3, end_selector={"label": "End"})
        self.assertTrue(result["end_marker_seen"])
        self.assertTrue(result["coverage_verified"])
        self.assertFalse(result["complete"])
        self.assertEqual(result["stop_reason"], "explicit_end_marker")
        self.assertEqual(self.client.actions(), [])

    def test_collect_list_stops_on_no_progress_without_claiming_coverage(self):
        result = self.phone.collect_list(max_pages=4)
        self.assertEqual(result["stop_reason"], "no_progress")
        self.assertEqual(len(result["pages"]), 1)
        self.assertFalse(result["complete"])
        self.assertFalse(result["coverage_verified"])
        self.assertEqual(self.client.swipe_count, 2)


if __name__ == "__main__":
    unittest.main()
