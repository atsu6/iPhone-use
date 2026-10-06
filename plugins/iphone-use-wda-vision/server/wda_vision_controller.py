"""Fast screenshot-first iPhone operations with optional observation metadata.

Coordinates come from the model's screenshot inspection. Actions do not recapture
or compare the screen before dispatch; callers can skip intermediate captures and
inspect one final screenshot. Transport acceptance does not prove task success.
"""
import base64
import datetime as dt
import inspect
import os
import re
import struct
import time
import uuid
import xml.etree.ElementTree as ET

from wda_client import WDAError
from wda_controller import PhoneController, action_result, fail, finite, integer


class VisualPhoneController(PhoneController):
    MAX_IMAGE_PIXELS = 100_000_000
    MAX_SCREENSHOT_BYTES = 24 * 1024 * 1024

    def __init__(self, client, state_dir):
        super().__init__(client, state_dir)
        self._guard_observation = None
        self._latest_observation = None
        self._cached_viewport = None

    @staticmethod
    def _recovery():
        return {
            "next_tool": "wda_vision_observe", "next_arguments": {},
            "same_observation_retry": False, "replay_action": False,
            "next_step": "Inspect a fresh screenshot before choosing the next action.",
        }

    def _invalidate(self):
        self.snapshots.clear()
        self._guard_observation = None
        self._latest_observation = None
        self._cached_viewport = None

    def _visual_error(self, error):
        error.details.update(verified=False, visual_verification_required=True)
        error.details.setdefault("verification_required", "Inspect actual screen state; do not automatically replay the action.")
        error.details["recovery"] = self._recovery()
        return error

    def _error_observation(self, error):
        try:
            error.details["observation"] = self.observe()
        except WDAError as observation_error:
            error.details["observation_error"] = observation_error.as_dict()

    def post(self, path, payload, timeout=None, session=True):
        """Dispatch once and preserve evidence when transport outcome is uncertain."""
        try:
            result = super().post(path, payload, timeout=timeout, session=session)
        except WDAError as error:
            # An XCTest error can follow partially applied input. Clear local
            # metadata and attach actual state, without replaying the action.
            before = self._guard_observation
            self._invalidate()
            rejected = error.code in {"invalid session id", "invalid argument", "unknown command", "unsupported operation"}
            error.uncertain = error.uncertain or not rejected
            error.details.update(action_executed=None if error.uncertain else False, action_complete=False)
            if before is not None:
                error.details["before_observation"] = before
            self._visual_error(error)
            self._error_observation(error)
            raise
        return result

    @classmethod
    def _png(cls, encoded):
        if not isinstance(encoded, str) or len(encoded) > cls.MAX_SCREENSHOT_BYTES * 4 // 3 + 4:
            fail("invalid_response", "Invalid screenshot encoding or excessive screenshot size.")
        try:
            data = base64.b64decode(encoded, validate=True)
        except (ValueError, TypeError) as exc:
            raise WDAError("invalid_response", "Invalid screenshot encoding.") from exc
        if len(data) < 33 or len(data) > cls.MAX_SCREENSHOT_BYTES or data[:8] != b"\x89PNG\r\n\x1a\n":
            fail("invalid_response", "WDA screenshot is not a complete PNG header.")
        if data[8:16] != b"\x00\x00\x00\rIHDR":
            fail("invalid_response", "WDA screenshot has an invalid PNG IHDR.")
        width, height = struct.unpack(">II", data[16:24])
        if (not 1 <= width <= 10000 or not 1 <= height <= 10000
                or width * height > cls.MAX_IMAGE_PIXELS):
            fail("invalid_response", "WDA screenshot has invalid PNG dimensions.")
        return data, width, height

    def _save_image(self, data):
        artifacts = self.state_dir / "artifacts"
        try:
            if artifacts.is_symlink():
                fail("unsafe_state_directory", "Screenshot artifact directory cannot be a symlink.")
            artifacts.mkdir(mode=0o700, parents=True, exist_ok=True)
            artifacts.chmod(0o700)
            dest = artifacts / ("vision-" + dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
                                + "-" + uuid.uuid4().hex[:8] + ".png")
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
            fd = os.open(dest, flags, 0o600)
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
            # Restrict a reused artifact directory and each screenshot independently.
            dest.chmod(0o600)
            for old in sorted(artifacts.glob("vision-*.png"))[:-100]:
                old.unlink()
            return dest
        except OSError as exc:
            raise WDAError("screenshot_save_failed", "Could not save the screenshot in the private artifact directory.") from exc

    def observe(self):
        raw = self.client.request("GET", "/screenshot")
        if not isinstance(raw, dict):
            fail("invalid_response", "WDA screenshot response must be an object.")
        data, width, height = self._png(raw.get("value"))
        viewport = self.viewport()
        foreground_error = None
        try:
            context = self.client.request("GET", "/wda/activeAppInfo", timeout=2)
            metadata = context.get("value") if isinstance(context, dict) else None
            app = metadata.get("bundleId") if isinstance(metadata, dict) else None
            if not isinstance(app, str) or not app or app.startswith("local.pid."):
                fail("wda_foreground_unavailable", "Foreground app metadata is unavailable; use the screenshot to identify the page.")
        except WDAError as error:
            app = None
            foreground_error = {"code": error.code, "message": str(error)}
        dest = self._save_image(data)
        ident = uuid.uuid4().hex
        scale = {"x": viewport["width"] / width, "y": viewport["height"] / height}
        result = {
            "observation_id": ident, "observed_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "mode": "screenshot", "app": app, "viewport": viewport,
            "image_dimensions": {"width": width, "height": height}, "pixel_to_point": scale,
            "image": {"path": str(dest), "mimeType": "image/png", "width": width, "height": height,
                      "pixel_to_point": scale,
                      "coordinates": "Convert screenshot pixels to iPhone points: x * pixel_to_point.x, y * pixel_to_point.y."},
            "warnings": ["Inspect the screenshot before choosing coordinates. Screenshot differences alone do not verify task progress."],
        }
        if foreground_error:
            result["foreground_error"] = foreground_error
            result["warnings"].append("Foreground app metadata is unavailable. The screenshot and coordinate conversion remain usable.")
        self.snapshots[ident] = {
            "viewport": viewport, "app": app, "observation": result,
        }
        self._latest_observation = result
        self._cached_viewport = viewport
        while len(self.snapshots) > 32:
            self.snapshots.popitem(last=False)
        return result

    def _reference(self, observation_id=None):
        cached = self.snapshots.get(observation_id) if isinstance(observation_id, str) else None
        self._guard_observation = cached["observation"] if cached else self._latest_observation
        return self._guard_observation

    def guard(self, observation_id=None):
        """Use cached geometry; observation IDs are optional references, never gates."""
        observed = self._reference(observation_id)
        if observed is not None:
            return observed["viewport"]
        if self._cached_viewport is None:
            self._cached_viewport = self.viewport()
        return self._cached_viewport

    @staticmethod
    def _capture_argument(observe):
        if not isinstance(observe, bool):
            fail("invalid_argument", "observe must be a boolean.", action_executed=False)

    def _after_visual(self, before, observe=True, **details):
        result = {
            "action_executed": True, "action_complete": True, "verified": False,
            "visual_verification_required": True, "before_observation": before,
            "verification_required": "Inspect the resulting screenshot to confirm the intended task result.",
            **details,
        }
        if observe:
            try:
                result["observation"] = self.observe()
            except WDAError as error:
                error.details["before_observation"] = before
                self._visual_error(error)
                raise
        return result

    @action_result
    def tap(self, x, y, observation_id=None, observe=True):
        self._capture_argument(observe)
        finite(x, "x"); finite(y, "y")
        viewport = self.guard(observation_id)
        if x >= viewport["width"] or y >= viewport["height"]:
            fail("invalid_argument", "Coordinates are outside the iPhone viewport.", action_executed=False)
        before = self._guard_observation
        self.post("/wda/tap", {"x": x, "y": y})
        return self._after_visual(before, observe=observe)

    @action_result
    def long_press(self, x, y, observation_id=None, duration=0.8, observe=True):
        self._capture_argument(observe)
        finite(x, "x"); finite(y, "y"); finite(duration, "duration", .1, 2)
        viewport = self.guard(observation_id)
        if x >= viewport["width"] or y >= viewport["height"]:
            fail("invalid_argument", "Coordinates are outside the iPhone viewport.", action_executed=False)
        before = self._guard_observation
        self.post("/wda/touchAndHold", {"x": x, "y": y, "duration": duration})
        return self._after_visual(before, observe=observe)

    @action_result
    def swipe(self, observation_id=None, direction="up", region=None, observe=True):
        self._capture_argument(observe)
        if direction not in ("up", "down", "left", "right"):
            fail("invalid_argument", "Invalid direction.", action_executed=False)
        viewport = self.guard(observation_id)
        area = self.region(region, viewport)
        x, y = area["x"] + area["width"] / 2, area["y"] + area["height"] / 2
        dx, dy = area["width"] * .32, area["height"] * .32
        points = {"up": (x, y + dy, x, y - dy), "down": (x, y - dy, x, y + dy),
                  "left": (x + dx, y, x - dx, y), "right": (x - dx, y, x + dx, y)}[direction]
        before = self._guard_observation
        self.post("/wda/dragfromtoforduration", dict(zip(("fromX", "fromY", "toX", "toY"), points), duration=.1))
        return self._after_visual(before, observe=observe, attempts=1, strategy="short_drag", region=area)

    @action_result
    def type_text(self, text, observation_id=None, focused_input_confirmed=None,
                  allow_newlines=False, multiline_confirmed=None, observe=True):
        self._capture_argument(observe)
        if not isinstance(text, str) or not 1 <= len(text) <= 10000 or "\x00" in text:
            fail("invalid_argument", "text must have 1..10000 characters without NUL.", action_executed=False)
        if any((ord(character) < 32 and character not in "\n\r") or ord(character) == 127 for character in text):
            fail("invalid_argument", "Text cannot contain keyboard control characters other than explicit line breaks.", action_executed=False)
        if not isinstance(allow_newlines, bool):
            fail("invalid_argument", "allow_newlines must be a boolean.", action_executed=False)
        if "\n" in text or "\r" in text:
            if not allow_newlines:
                fail("newline_requires_intent", "Line breaks can send a message. Explicit newline intent is required.", action_executed=False)
        before = self._reference(observation_id)
        self.post("/wda/keys", {"value": list(text)})
        return self._after_visual(before, observe=observe, characters=len(text),
                                  submitted=False, exact_readback=False,
                                  newline_entered="\n" in text or "\r" in text)

    def _foreground_after(self, bundle_id, before, observe=True):
        result = self._after_visual(before, observe=observe, requested_app=bundle_id)
        observed = result.get("observation")
        if observed is not None:
            app = observed["app"]
            result.update(foreground_verified=app == bundle_id, foreground_app=app)
        return result

    @action_result
    def launch_app(self, bundle_id, observation_id=None, observe=True):
        self._capture_argument(observe)
        if not isinstance(bundle_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)+", bundle_id):
            fail("invalid_argument", "Use the app's verified bundle ID.", action_executed=False)
        before = self._reference(observation_id)
        self.post("/wda/apps/activate", {"bundleId": bundle_id}, timeout=45)
        return self._foreground_after(bundle_id, before, observe=observe)

    @action_result
    def press_button(self, name, observation_id=None, observe=True):
        self._capture_argument(observe)
        if name not in ("home", "volumeup", "volumedown"):
            fail("invalid_argument", "Supported buttons: home, volumeup, volumedown.", action_executed=False)
        before = self._reference(observation_id)
        if name == "home":
            self.post("/wda/homescreen", {}, session=False)
            return self._foreground_after("com.apple.springboard", before, observe=observe)
        self.post("/wda/pressButton", {"name": name})
        return self._after_visual(before, observe=observe)

    def wait(self, seconds=0.5):
        finite(seconds, "seconds", 0, 3)
        time.sleep(seconds)
        return {"action_executed": False, "verified": False, "waited_seconds": seconds,
                "visual_verification_required": True, "observation": self.observe()}

    def read_page(self, reason=None, max_nodes=100):
        if reason is not None and (not isinstance(reason, str) or len(reason) > 1000):
            fail("invalid_argument", "reason must be text up to 1000 characters.", action_executed=False)
        integer(max_nodes, "max_nodes", 1, 500)
        # Data-only reads do not change the screen or invalidate its metadata.
        raw = self.client.session("GET", "/source?format=xml&excluded_attributes=visible")
        if not isinstance(raw, str):
            fail("invalid_response", "WDA source is not XML text.")
        try:
            root = ET.fromstring(raw)
        except ET.ParseError as exc:
            raise WDAError("invalid_response", "WDA XML parse failed.") from exc
        nodes = []
        for element in root.iter():
            attributes = element.attrib
            node = {}
            text = attributes.get("label") or attributes.get("name")
            if text:
                node["text"] = text
            if attributes.get("value"):
                node["value"] = attributes["value"]
            if node:
                nodes.append(node)
        return {"purpose": "data_reading_only", "reason": reason, "nodes": nodes[:max_nodes],
                "total_nodes": len(nodes), "truncated": len(nodes) > max_nodes,
                "visual_observation_required": False,
                "limitations": ["Accessibility text can be incomplete or offscreen. Choose operation targets from screenshots."]}

    def batch(self, steps):
        if not isinstance(steps, list) or not 1 <= len(steps) <= 20:
            fail("invalid_argument", "steps must contain 1..20 operations.")
        allowed = {"tap": self.tap, "long_press": self.long_press, "swipe": self.swipe,
                   "type_text": self.type_text, "launch_app": self.launch_app,
                   "press_button": self.press_button, "wait": self.wait, "observe": self.observe}
        # Reject unsupported operations and bad argument shapes before any mutation.
        for step in steps:
            if (not isinstance(step, dict) or set(step) - {"op", "args"}
                    or step.get("op") not in allowed or not isinstance(step.get("args", {}), dict)):
                fail("invalid_argument", "Each batch step needs a supported visual op and args object.")
            try:
                inspect.signature(allowed[step["op"]]).bind(**step.get("args", {}))
            except TypeError as exc:
                raise WDAError("invalid_argument", "Invalid arguments for batch operation " + step["op"] + ".") from exc
        results = []
        accepted_before = self.accepted_actions
        for index, step in enumerate(steps):
            try:
                args = dict(step.get("args", {}))
                if step["op"] not in ("observe", "wait"):
                    args.setdefault("observe", False)
                result = allowed[step["op"]](**args)
                results.append(result)
            except WDAError as error:
                return {"completed_steps": len(results), "stopped_at": index,
                        "stop_reason": error.code, "error": error.as_dict(), "results": results,
                        "action_executed": True if self.accepted_actions > accepted_before
                        else error.details.get("action_executed", False),
                        "verified": False, "visual_verification_required": True,
                        "complete": False}
        response = {"completed_steps": len(results), "results": results, "complete": True,
                    "action_executed": self.accepted_actions > accepted_before,
                    "verified": False, "visual_verification_required": True,
                    "verification_required": "All supplied operations were dispatched. Inspect the final screenshot to confirm the task result."}
        last = results[-1]
        if "image" not in last and not last.get("observation", {}).get("image"):
            try:
                response["observation"] = self.observe()
            except WDAError as error:
                error.details.update(action_executed=response["action_executed"], action_complete=True)
                self._visual_error(error)
                response["observation_error"] = error.as_dict()
        return response
