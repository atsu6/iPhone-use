import base64
import copy
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))
from wda_client import WDAError
from wda_controller import ELEMENT_KEY, PhoneController, predicate


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
        self.activate_effective = True
        self.activate_error = None
        self.foreground_sequence = None
        self.gesture_effects = None
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
            if self.foreground_sequence:
                self.app = self.foreground_sequence.pop(0)
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
            enabled = re.search(r"enabled == (true|false)", value)
            if enabled:
                matches = [item for item in matches if item.get("enabled", True) is (enabled[1] == "true")]
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
            if self.gesture_effects and self.swipe_count <= len(self.gesture_effects):
                effect = self.gesture_effects[self.swipe_count - 1]
                if effect:
                    effect()
            return None
        if path == "/wda/apps/activate":
            if self.activate_error:
                raise self.activate_error
            if self.activate_effective:
                self.app = payload["bundleId"]
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

    def test_stale_region_distinguishes_numeric_content_from_geometry_changes(self):
        area = {"x": 30, "y": 300, "width": 300, "height": 400}
        for change in ("content", "geometry"):
            with self.subTest(change=change):
                self.setUp()
                self.client.nodes = [node("Synthetic counter", y=350, value="100.00")]
                observed = self.phone.observe("tree")
                if change == "content":
                    self.client.nodes[0]["value"] = "100.25"
                else:
                    self.client.nodes[0]["y"] = 360
                self.client.calls.clear()
                error = self.assert_code("stale_observation", lambda: self.phone.swipe(region=area, observation_id=observed["observation_id"]))
                diagnostics = error.details["region_change_diagnostics"]
                self.assertEqual(diagnostics["previous_nodes"], 1)
                self.assertEqual(diagnostics["current_nodes"], 1)
                self.assertIsInstance(diagnostics["previous_nodes"], int)
                self.assertIsInstance(diagnostics["current_nodes"], int)
                self.assertIs(diagnostics["geometry_changed"], change == "geometry")
                self.assertIs(diagnostics["content_changed"], change == "content")
                self.assertFalse(error.details["action_executed"])
                self.assertEqual(self.client.actions(), [])

    def test_stale_region_returns_new_bounded_current_observation(self):
        area = {"x": 30, "y": 300, "width": 300, "height": 400}
        self.client.nodes = [node(f"Synthetic row {index}", y=350, value=str(index)) for index in range(120)]
        previous = self.phone.observe("tree", max_nodes=5)
        self.client.nodes[0]["value"] = "200"
        self.client.calls.clear()
        error = self.assert_code("stale_observation", lambda: self.phone.swipe(region=area, observation_id=previous["observation_id"]))
        current = error.details["observation"]
        self.assertNotEqual(current["observation_id"], previous["observation_id"])
        self.assertIn(current["observation_id"], self.phone.snapshots)
        self.assertEqual(len(current["nodes"]), 100)
        self.assertEqual(current["total_nodes"], 120)
        self.assertTrue(current["truncated"])
        self.assertEqual(current["nodes"][0]["value"], "200")
        self.assertEqual(error.details["region_change_diagnostics"]["previous_nodes"], 120)
        self.assertEqual(error.details["region_change_diagnostics"]["current_nodes"], 120)
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

    def test_default_scroll_requires_explicit_region_when_native_modal_is_present(self):
        for kind in ("Alert", "Sheet"):
            for verify in (True, False):
                with self.subTest(kind=kind, verify=verify):
                    self.setUp()
                    self.client.nodes = [node("Row 1"), node("", kind=kind, x=40, y=100, width=310, height=600)]
                    error = self.assert_code("modal_requires_region", lambda: self.phone.swipe(verify=verify))
                    self.assertFalse(error.details["action_executed"])
                    self.assertEqual(self.client.actions(), [])
                    self.assertEqual(self.client.swipe_count, 0)

    def test_fresh_explicit_region_inside_native_modal_can_scroll(self):
        area = {"x": 70, "y": 250, "width": 200, "height": 250}
        for kind in ("Alert", "Sheet"):
            with self.subTest(kind=kind):
                self.setUp()
                modal = node("", kind=kind, x=40, y=100, width=310, height=600)
                self.client.nodes = [modal, node("Row 1", y=300)]
                observed = self.phone.observe("both")
                self.client.source_pages = [self.client.nodes, [modal, node("Row 2", y=300)]]
                self.client.calls.clear()
                result = self.phone.swipe(region=area, observation_id=observed["observation_id"], observe="tree")
                self.assertTrue(result["verified"])
                self.assertTrue(result["changed"])
                self.assertEqual(result["attempts"], 1)
                self.assertEqual([path for _, path, _ in self.client.actions()], ["/wda/dragfromtoforduration"])

    def test_explicit_region_outside_or_crossing_native_modal_is_blocked(self):
        for area in ({"x": 70, "y": 200, "width": 200, "height": 150},
                     {"x": 70, "y": 400, "width": 200, "height": 200}):
            with self.subTest(area=area):
                self.setUp()
                self.client.nodes = [node("Row 1", y=area["y"] + 25),
                                     node("", kind="Sheet", x=40, y=500, width=310, height=200)]
                observed = self.phone.observe("tree")
                self.client.calls.clear()
                error = self.assert_code("blocked_scroll_region", lambda: self.phone.swipe(region=area, observation_id=observed["observation_id"]))
                self.assertFalse(error.details["action_executed"])
                self.assertEqual(self.client.actions(), [])

    def test_region_inside_sheet_but_crossing_coexisting_alert_is_blocked(self):
        area = {"x": 70, "y": 250, "width": 200, "height": 250}
        sheet = node("", kind="Sheet", x=40, y=100, width=310, height=600)
        alert = node("", kind="Alert", x=90, y=300, width=170, height=100)
        self.client.nodes = [sheet, alert, node("Synthetic row", y=350)]
        observed = self.phone.observe("tree")
        self.client.calls.clear()
        error = self.assert_code("blocked_scroll_region", lambda: self.phone.swipe(region=area, observation_id=observed["observation_id"]))
        self.assertFalse(error.details["action_executed"])
        self.assertEqual(len(error.details["native_modals"]), 2)
        self.assertEqual(self.client.actions(), [])

    def test_fresh_region_inside_all_coexisting_native_modals_can_scroll(self):
        area = {"x": 100, "y": 300, "width": 150, "height": 100}
        sheet = node("", kind="Sheet", x=40, y=100, width=310, height=600)
        alert = node("", kind="Alert", x=90, y=250, width=170, height=200)
        self.client.nodes = [sheet, alert, node("Synthetic row 1", x=100, y=325, width=150)]
        observed = self.phone.observe("tree")
        self.client.source_pages = [self.client.nodes, [sheet, alert, node("Synthetic row 2", x=100, y=325, width=150)]]
        self.client.calls.clear()
        result = self.phone.swipe(region=area, observation_id=observed["observation_id"], observe="none")
        self.assertTrue(result["verified"])
        self.assertTrue(result["changed"])
        self.assertEqual(result["attempts"], 1)
        self.assertEqual([path for _, path, _ in self.client.actions()], ["/wda/dragfromtoforduration"])

    def test_native_modal_region_without_fresh_observation_is_not_guessed(self):
        area = {"x": 70, "y": 250, "width": 200, "height": 250}
        self.client.nodes = [node("", kind="Sheet", x=40, y=100, width=310, height=600), node("Row 1", y=300)]
        error = self.assert_code("stale_observation", lambda: self.phone.swipe(region=area))
        self.assertFalse(error.details.get("action_executed", False))
        self.assertEqual(self.client.actions(), [])

    def test_modal_appearing_after_gesture_is_not_counted_as_scroll_progress(self):
        for placement in ("inside", "outside"):
            for mode in ("none", "tree", "screenshot", "both"):
                with self.subTest(placement=placement, mode=mode):
                    self.setUp()
                    modal = node("", kind="Alert", x=80,
                                 y=300 if placement == "inside" else 60, width=230, height=80)
                    self.client.source_pages = [[node("Row 1")], [node("Row 2"), modal]]
                    error = self.assert_code("scroll_context_changed", lambda: self.phone.swipe(observe=mode))
                    self.assertTrue(error.details["action_executed"])
                    self.assertFalse(error.details["verified"])
                    self.assertFalse(error.details["changed"])
                    self.assertFalse(error.details["action_complete"])
                    self.assertEqual(error.details["attempts"], 1)
                    self.assertEqual(error.details["reasons"], ["modal_changed"])
                    self.assertFalse(error.details["recovery"]["same_gesture_retry"])
                    self.assertFalse(error.details["recovery"]["replay_action"])
                    self.assertEqual(self.client.swipe_count, 1)
                    self.assertEqual([path for _, path, _ in self.client.actions()], ["/wda/dragfromtoforduration"])
                    if mode == "none":
                        self.assertNotIn("observation", error.details)
                    else:
                        observed = error.details["observation"]
                        self.assertIn(observed["observation_id"], self.phone.snapshots)
                        self.assertEqual("image" in observed, mode in ("screenshot", "both"))
                        self.assertEqual("nodes" in observed, mode in ("tree", "both"))
                        if "nodes" in observed:
                            self.assertTrue(any(n["type"] == "XCUIElementTypeAlert" for n in observed["nodes"]))

    def test_modal_disappearance_or_geometry_change_stops_intentional_modal_scroll(self):
        area = {"x": 70, "y": 250, "width": 200, "height": 250}
        modal = node("", kind="Sheet", x=40, y=100, width=310, height=600)
        for change in ("removed", "moved"):
            with self.subTest(change=change):
                self.setUp()
                self.client.nodes = [modal, node("Row 1", y=300)]
                observed = self.phone.observe("tree")
                current = [node("Row 2", y=300)]
                if change == "moved":
                    current.append({**modal, "y": 120})
                self.client.source_pages = [self.client.nodes, current]
                self.client.calls.clear()
                error = self.assert_code("scroll_context_changed", lambda: self.phone.swipe(region=area, observation_id=observed["observation_id"]))
                self.assertEqual(error.details["attempts"], 1)
                self.assertFalse(error.details["verified"])
                self.assertEqual(error.details["reasons"], ["modal_changed"])
                self.assertEqual(self.client.swipe_count, 1)
                self.assertEqual([path for _, path, _ in self.client.actions()], ["/wda/dragfromtoforduration"])

    def test_orientation_change_after_gesture_stops_before_progress_or_fallback(self):
        self.client.source_pages = [[node("Row 1")], [node("Row 2")]]
        self.client.gesture_effects = [lambda: setattr(self.client, "size", {"width": 844, "height": 390})]
        error = self.assert_code("scroll_context_changed", lambda: self.phone.swipe(observe="tree"))
        self.assertTrue(error.details["action_executed"])
        self.assertFalse(error.details["verified"])
        self.assertFalse(error.details["changed"])
        self.assertEqual(error.details["attempts"], 1)
        self.assertEqual(error.details["reasons"], ["viewport_changed"])
        self.assertEqual(error.details["observation"]["viewport"], {**self.client.size, "units": "iPhone points"})
        self.assertEqual([path for _, path, _ in self.client.actions()], ["/wda/dragfromtoforduration"])

    def test_modal_during_fallback_reports_two_executed_gestures_and_stops(self):
        self.client.source_pages = [[node("Row 1")], [node("Row 1")],
                                    [node("Row 1"), node("", kind="Alert", y=80)]]
        error = self.assert_code("scroll_context_changed", lambda: self.phone.swipe(observe="none"))
        self.assertTrue(error.details["action_executed"])
        self.assertFalse(error.details["verified"])
        self.assertEqual(error.details["attempts"], 2)
        self.assertEqual(error.details["reasons"], ["modal_changed"])
        self.assertEqual(self.client.swipe_count, 2)
        self.assertEqual([path for _, path, _ in self.client.actions()], ["/wda/dragfromtoforduration", "/wda/swipe"])

    def test_disabled_progress_verification_still_stops_on_new_native_modal(self):
        self.client.source_pages = [[node("Row 1")], [node("Row 1"), node("", kind="Alert", y=80)]]
        error = self.assert_code("scroll_context_changed", lambda: self.phone.swipe(verify=False, observe="none"))
        self.assertTrue(error.details["action_executed"])
        self.assertFalse(error.details["verified"])
        self.assertEqual(error.details["attempts"], 1)
        self.assertEqual([path for _, path, _ in self.client.actions()], ["/wda/dragfromtoforduration"])

    def test_modal_and_orientation_changes_are_both_reported_after_one_gesture(self):
        self.client.source_pages = [[node("Row 1")], [node("Row 2"), node("", kind="Sheet", y=80)]]
        self.client.gesture_effects = [lambda: setattr(self.client, "size", {"width": 844, "height": 390})]
        error = self.assert_code("scroll_context_changed", lambda: self.phone.swipe(observe="none"))
        self.assertEqual(set(error.details["reasons"]), {"viewport_changed", "modal_changed"})
        self.assertFalse(error.details["changed"])
        self.assertEqual(error.details["attempts"], 1)
        self.assertEqual([path for _, path, _ in self.client.actions()], ["/wda/dragfromtoforduration"])

    def test_arbitrary_other_nodes_are_not_treated_as_native_modals(self):
        overlay = node("Custom overlay", kind="Other", x=40, y=100, width=310, height=600)
        self.client.source_pages = [[node("Row 1"), overlay], [node("Row 2"), overlay]]
        result = self.phone.swipe(observe="none")
        self.assertTrue(result["verified"])
        self.assertEqual(self.client.swipe_count, 1)

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

    def test_launch_waits_for_foreground_transition_without_reactivating(self):
        requested = "com.example.requested"
        self.client.foreground_sequence = ["com.example.previous", "com.example.previous", requested]
        clock = [100.0]

        def sleep(seconds):
            clock[0] += seconds

        with patch("wda_controller.time.monotonic", side_effect=lambda: clock[0]), \
                patch("wda_controller.time.sleep", side_effect=sleep) as sleeper:
            result = self.phone.launch_app(requested, observe="none")
        self.assertTrue(result["foreground_verified"])
        self.assertTrue(result["action_executed"])
        self.assertEqual(self.client.app, requested)
        self.assertGreater(sleeper.call_count, 0)
        self.assertLessEqual(clock[0] - 100, 5)
        self.assertEqual(self.client.actions(), [("POST", "/wda/apps/activate", {"bundleId": requested})])
        self.assertEqual(sum(path == "/wda/activeAppInfo" for _, path, _ in self.client.calls), 3)

    def test_launch_foreground_mismatch_has_bounded_reads_and_execution_evidence(self):
        requested = "com.example.requested"
        self.client.activate_effective = False
        clock = [100.0]
        read_times = []
        original_request = self.client.request

        def sleep(seconds):
            clock[0] += seconds

        def request(method, path, payload=None, timeout=None):
            if path == "/wda/activeAppInfo":
                read_times.append(clock[0])
            return original_request(method, path, payload, timeout)

        with patch("wda_controller.time.monotonic", side_effect=lambda: clock[0]), \
                patch("wda_controller.time.sleep", side_effect=sleep), \
                patch.object(self.client, "request", side_effect=request):
            error = self.assert_code("postcondition_failed", lambda: self.phone.launch_app(requested, observe="none"))
        self.assertTrue(error.details["action_executed"])
        self.assertFalse(error.details["action_complete"])
        self.assertEqual(error.details["foreground_app"], "com.example.phone")
        self.assertEqual(error.details["requested_app"], requested)
        self.assertFalse(error.details["recovery"]["replay_action"])
        self.assertAlmostEqual(clock[0] - 100, 5)
        reads = sum(path == "/wda/activeAppInfo" for _, path, _ in self.client.calls)
        self.assertGreater(reads, 1)
        self.assertLessEqual(reads, 60)
        self.assertTrue(all(now < 105 for now in read_times))
        self.assertEqual(self.client.actions(), [("POST", "/wda/apps/activate", {"bundleId": requested})])

    def test_uncertain_launch_is_not_replayed_or_polled(self):
        self.client.activate_error = WDAError("action_uncertain", "Activation response timed out", uncertain=True)
        error = self.assert_code("action_uncertain", lambda: self.phone.launch_app("com.example.requested", observe="none"))
        self.assertTrue(error.uncertain)
        self.assertEqual(self.phone.accepted_actions, 0)
        self.assertFalse(any(path == "/wda/activeAppInfo" for _, path, _ in self.client.calls))
        self.assertEqual([path for _, path, _ in self.client.actions()], ["/wda/apps/activate"])

    def test_launch_deadline_crossing_never_sends_negative_timeout(self):
        # The deadline may pass between reads: use one remaining-time sample.
        with patch("wda_controller.time.monotonic", side_effect=[100,104.99,105.01,105.02]), \
                patch("wda_controller.time.sleep"), \
                patch.object(self.phone,"active_app",return_value="com.example.previous") as active:
            error=self.assert_code("postcondition_failed",lambda:self.phone.launch_app("com.example.requested",observe="none"))
        active.assert_called_once()
        self.assertGreater(active.call_args.kwargs["timeout"],0)
        self.assertTrue(error.details["action_executed"])
        self.assertFalse(error.details["action_complete"])
        self.assertEqual([path for _,path,_ in self.client.actions()],["/wda/apps/activate"])

    def test_launch_channel_failure_after_activation_is_not_replayed(self):
        fault = WDAError("unknown error", "XCTDaemonErrorDomain Code=41 Not authorized for performing UI testing actions")
        with patch.object(self.phone, "active_app", side_effect=fault) as read:
            error = self.assert_code("unknown error", lambda: self.phone.launch_app("com.example.requested", observe="none"))
        read.assert_called_once()
        self.assertTrue(error.details["action_executed"])
        self.assertFalse(error.details["action_complete"])
        self.assertEqual([path for _, path, _ in self.client.actions()], ["/wda/apps/activate"])

    def test_exact_target_offscreen_or_occluded_is_not_clicked(self):
        for condition, code in (("offscreen", "offscreen_target"), ("occluded", "occluded_target")):
            with self.subTest(condition=condition):
                self.setUp()
                if condition == "offscreen":
                    self.client.elements[0]["rect"]["y"] = 900
                else:
                    self.client.elements[0]["hittable"] = False
                error = self.assert_code(code, lambda: self.phone.tap(selector={"label": "Target"}, observe="none"))
                self.assertFalse(error.details["action_executed"])
                self.assertEqual(error.details["target_rect"], self.client.elements[0]["rect"])
                self.assertEqual(error.details["viewport"], {**self.client.size, "units": "iPhone points"})
                self.assertEqual(error.details["recovery"]["next_tool"], "wda_observe")
                self.assertEqual(error.details["recovery"]["next_arguments"], {"mode": "both"})
                self.assertFalse(error.details["recovery"]["replay_action"])
                if condition == "occluded":
                    self.assertFalse(error.details["recovery"]["coordinate_bypass"])
                    self.assertFalse(error.details["recovery"]["same_target_retry"])
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
        self.assertTrue(error.details["action_executed"])
        self.assertFalse(error.details["verified"])
        self.assertFalse(error.details["changed"])
        self.assertEqual(error.details["observation"]["nodes"][0]["label"], "Row 1")
        self.assertFalse(error.details["recovery"]["same_gesture_retry"])
        self.assertFalse(error.details["recovery"]["end_of_list_proven"])

    def test_swipe_observation_modes_do_not_disable_progress_verification(self):
        for mode in ("none", "tree", "screenshot", "both"):
            with self.subTest(mode=mode):
                self.setUp()
                self.client.source_pages = [[node("Row 1")], [node("Row 2")]]
                result = self.phone.swipe(observe=mode)
                self.assertTrue(result["verified"])
                self.assertEqual(result["attempts"], 1)
                self.assertEqual(self.client.swipe_count, 1)
                if mode == "none":
                    self.assertNotIn("observation", result)
                else:
                    observed = result["observation"]
                    self.assertIn("observation_id", observed)
                    self.assertEqual("image" in observed, mode in ("screenshot", "both"))
                    self.assertEqual("nodes" in observed, mode in ("tree", "both"))
                self.assertEqual(sum(path.startswith("/source") for _, path, _ in self.client.calls), 2)

    def test_no_progress_with_observe_none_still_executes_bounded_verification(self):
        error = self.assert_code("no_scroll_progress", lambda: self.phone.swipe(observe="none"))
        self.assertNotIn("observation", error.details)
        self.assertTrue(error.details["action_executed"])
        self.assertEqual(error.details["attempts"], 2)
        self.assertEqual(self.client.swipe_count, 2)

    def test_post_swipe_tree_failure_preserves_accepted_gesture_without_retry(self):
        baseline = self.client.source()
        fault = WDAError("stale element reference", "Application local.pid.0 is not running")
        with patch.object(self.client, "source", side_effect=[baseline, fault]) as source:
            error = self.assert_code("stale element reference", lambda: self.phone.swipe(observe="tree"))
        self.assertEqual(source.call_count, 2)
        self.assertEqual(self.client.swipe_count, 1)
        self.assertEqual(self.phone.accepted_actions, 1)
        self.assertEqual([path for _, path, _ in self.client.actions()], ["/wda/dragfromtoforduration"])
        self.assertTrue(error.details["action_executed"])
        self.assertFalse(error.details["action_complete"])
        self.assertIn("verification_required", error.details)

    def test_post_swipe_screenshot_failure_retains_accepted_gesture_and_stops(self):
        self.client.source_pages = [[node("Row 1")], [node("Row 2")]]
        original = self.client.request

        def request(method, path, payload=None, timeout=None):
            if path == "/screenshot":
                raise WDAError("wda_unreachable", "Screenshot channel disconnected")
            return original(method, path, payload, timeout)

        with patch.object(self.client, "request", side_effect=request):
            error = self.assert_code("wda_unreachable", lambda: self.phone.swipe(observe="both"))
        self.assertTrue(error.details["action_executed"])
        self.assertFalse(error.details["action_complete"])
        self.assertEqual(self.client.swipe_count, 1)
        self.assertEqual(self.phone.accepted_actions, 1)
        self.assertEqual([path for _, path, _ in self.client.actions()], ["/wda/dragfromtoforduration"])

    def test_uncertain_first_gesture_does_not_claim_an_accepted_action(self):
        original = self.client.session

        def session(method, path, payload=None, timeout=None):
            if path == "/wda/dragfromtoforduration":
                self.client.calls.append((method, path, payload))
                raise WDAError("action_uncertain", "Gesture response timed out", uncertain=True)
            return original(method, path, payload, timeout)

        with patch.object(self.client, "session", side_effect=session):
            error = self.assert_code("action_uncertain", lambda: self.phone.swipe())
        self.assertTrue(error.uncertain)
        self.assertFalse(error.details.get("action_executed", False))
        self.assertEqual(self.phone.accepted_actions, 0)
        self.assertEqual([path for _, path, _ in self.client.actions()], ["/wda/dragfromtoforduration"])

    def test_uncertain_fallback_preserves_known_first_gesture_without_third_attempt(self):
        original = self.client.session

        def session(method, path, payload=None, timeout=None):
            if path == "/wda/swipe":
                self.client.calls.append((method, path, payload))
                raise WDAError("action_uncertain", "Fallback response timed out", uncertain=True)
            return original(method, path, payload, timeout)

        with patch.object(self.client, "session", side_effect=session):
            error = self.assert_code("action_uncertain", lambda: self.phone.swipe())
        self.assertTrue(error.uncertain)
        self.assertTrue(error.details["action_executed"])
        self.assertFalse(error.details["action_complete"])
        self.assertEqual(self.phone.accepted_actions, 1)
        self.assertEqual(self.client.swipe_count, 1)
        self.assertEqual([path for _, path, _ in self.client.actions()], ["/wda/dragfromtoforduration", "/wda/swipe"])

    def test_no_progress_returns_requested_screenshot_for_inspection(self):
        error = self.assert_code("no_scroll_progress", lambda: self.phone.swipe(observe="both", max_attempts=1))
        observed = error.details["observation"]
        self.assertEqual(Path(observed["image"]["path"]).read_bytes(), self.client.screenshot)
        self.assertEqual(observed["nodes"][0]["label"], "Row 1")
        self.assertIn(observed["observation_id"], self.phone.snapshots)
        self.assertEqual(error.details["attempts"], 1)

    def test_explicitly_disabled_swipe_verification_is_not_reported_as_success(self):
        result = self.phone.swipe(verify=False, observe="none")
        self.assertTrue(result["action_executed"])
        self.assertFalse(result["verified"])
        self.assertIn("verification_required", result)
        self.assertEqual(self.client.swipe_count, 1)
        self.assertNotIn("observation", result)

    def test_exact_enabled_accepts_tree_strings_and_booleans_equally(self):
        self.client.elements.append({**self.client.elements[0], "id": "disabled", "enabled": False})
        for value, expected_id in ((True, "target"), ("true", "target"), (False, "disabled"), ("false", "disabled")):
            with self.subTest(value=value):
                result = self.phone.find({"label": "Target", "enabled": value})
                self.assertEqual(result["matches"], 1)
                self.assertEqual(result["elements"][0]["element_id"], expected_id)

    def test_exact_enabled_rejects_guesses_before_device_query(self):
        for value in ("TRUE", "yes", 1, None):
            with self.subTest(value=value):
                self.assert_code("invalid_selector", lambda: predicate({"label": "Target", "enabled": value}))
        self.assertEqual(self.client.calls, [])

    def test_exact_selector_rejects_nul_instead_of_silently_mismatching(self):
        self.assert_code("invalid_selector", lambda: self.phone.find({"label": "a\x00b"}))
        self.assertEqual(self.client.calls, [])

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

    def test_batch_blocked_target_preserves_failed_step_and_does_not_continue(self):
        self.client.elements[0]["hittable"] = False
        result = self.phone.batch([
            {"op": "observe", "args": {}},
            {"op": "tap", "args": {"selector": {"label": "Target"}, "observe": "none"}},
            {"op": "press_button", "args": {"name": "home", "observe": "none"}},
        ])
        self.assertFalse(result["complete"])
        self.assertEqual(result["completed_steps"], 1)
        self.assertEqual(result["stop_reason"], "occluded_target")
        self.assertFalse(result["error"]["action_executed"])
        self.assertFalse(result["error"]["recovery"]["coordinate_bypass"])
        self.assertEqual(self.client.actions(), [])

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


@unittest.skipUnless(sys.platform == "darwin" and shutil.which("clang"), "Apple Foundation requires macOS and clang")
class FoundationPredicateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.directory.cleanup)
        cls.probe = Path(cls.directory.name) / "predicate-probe"
        built = subprocess.run(["clang", "-framework", "Foundation", str(Path(__file__).with_name("predicate_probe.m")), "-o", str(cls.probe)],
                               capture_output=True, text=True, timeout=60)
        if built.returncode:
            raise AssertionError("Foundation predicate probe did not build: " + built.stderr)

    def evaluate(self, cases):
        result = subprocess.run([str(self.probe)], input=json.dumps(cases, ensure_ascii=False), capture_output=True,
                                text=True, encoding="utf-8", timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_exact_text_literals_preserve_controls_quotes_and_literal_escapes(self):
        values = ["第一行\n第二行", "literal\\n", "a'b", "a\\b", "a\\'b", "a\r\nb", "a\tb", "a\x01\x7fb",
                  "一\u2028二\u2029三", "你好 👋 Café e\u0301", "100%@", "a' OR TRUEPREDICATE OR label == 'b"]
        cases = []
        for value in values:
            query = predicate({"label": value})
            cases.extend([{"predicate": query, "object": {"label": value}},
                          {"predicate": query, "object": {"label": "different " + value}}])
        for index, result in enumerate(self.evaluate(cases)):
            with self.subTest(value=values[index // 2], same=index % 2 == 0):
                self.assertTrue(result["parsed"], result.get("error"))
                self.assertEqual(result["matched"], index % 2 == 0)

    def test_real_newline_and_literal_backslash_n_select_different_objects(self):
        cases = [{"predicate": predicate({"label": text}), "object": {"label": other}}
                 for text, other in (("a\nb", "a\\nb"), ("a\\nb", "a\nb"))]
        self.assertEqual(self.evaluate(cases), [{"parsed": True, "matched": False}, {"parsed": True, "matched": False}])

    def test_enabled_tree_strings_boolean_filter_and_combined_fields_match_exactly(self):
        cases = []
        for enabled in (True, "true", False, "false"):
            flag = enabled is True or enabled == "true"
            query = predicate({"label": "返回\n上一页", "name": "back", "type": "Button", "enabled": enabled})
            obj = {"label": "返回\n上一页", "name": "back", "type": "XCUIElementTypeButton", "enabled": flag}
            cases.extend([{"predicate": query, "object": obj}, {"predicate": query, "object": {**obj, "enabled": not flag}}])
        for index, result in enumerate(self.evaluate(cases)):
            self.assertTrue(result["parsed"], result.get("error"))
            self.assertEqual(result["matched"], index % 2 == 0)


if __name__ == "__main__":
    unittest.main()
