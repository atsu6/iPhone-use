"""Memory-only WDA MJPEG preview and a small, private cross-process activity bus.

The widget supplies a short lease. No visible widget means no USB capture; opening
the tool returns immediately. This module never calls the WDA command channel.
"""
from __future__ import annotations

import atexit
import base64
import contextlib
import fcntl
import json
import math
import os
from pathlib import Path
import re
import select
import shutil
import subprocess
import tempfile
import threading
import time
import uuid

MAX_FRAME_BYTES = 4 * 1024 * 1024
FRAME_LEASE_SECONDS = 5
EVENT_AGE_MS = 10_000
BUSY_AGE_MS = 15_000
ACTIVITY_GRACE_MS = 650
SOF_MARKERS = {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
               0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}


def jpeg_dimensions(raw):
    """Read JPEG SOF dimensions without decoding pixels or trusting HTTP headers."""
    if not raw.startswith(b"\xff\xd8"):
        return None
    offset = 2
    while offset + 1 < len(raw):
        if raw[offset] != 0xFF:
            return None
        while offset < len(raw) and raw[offset] == 0xFF:
            offset += 1
        if offset >= len(raw):
            return None
        marker = raw[offset]
        offset += 1
        if marker in (0xD9, 0xDA):
            return None
        if marker == 0x01 or 0xD0 <= marker <= 0xD8:
            continue
        if offset + 2 > len(raw):
            return None
        length = int.from_bytes(raw[offset:offset + 2], "big")
        if length < 2 or offset + length > len(raw):
            return None
        if marker in SOF_MARKERS:
            if length < 8:
                return None
            height = int.from_bytes(raw[offset + 3:offset + 5], "big")
            width = int.from_bytes(raw[offset + 5:offset + 7], "big")
            return (width, height) if 0 < width <= 16384 and 0 < height <= 16384 else None
        offset += length
    return None


class MJPEGParser:
    """Bounded SOI/EOI framing, tolerant of multipart headers and split markers."""
    def __init__(self, max_bytes=MAX_FRAME_BYTES):
        self.max_bytes = max_bytes
        self.buffer = bytearray()

    def feed(self, data):
        frames = []
        incoming = memoryview(data)
        while incoming:
            room = self.max_bytes - len(self.buffer)
            if room <= 0:
                self.buffer = bytearray(b"\xff" if self.buffer[-1:] == b"\xff" else b"")
                room = self.max_bytes - len(self.buffer)
            count = min(room, len(incoming), 65536)
            self.buffer.extend(incoming[:count])
            incoming = incoming[count:]
            while self.buffer:
                start = self.buffer.find(b"\xff\xd8")
                if start < 0:
                    self.buffer = bytearray(b"\xff" if self.buffer[-1:] == b"\xff" else b"")
                    break
                if start:
                    del self.buffer[:start]
                end = self.buffer.find(b"\xff\xd9", 2)
                if end < 0:
                    break
                raw = bytes(self.buffer[:end + 2])
                del self.buffer[:end + 2]
                dimensions = jpeg_dimensions(raw)
                if dimensions:
                    frames.append((raw, dimensions))
        return frames


def _number(value, maximum=100_000):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) and 0 <= value <= maximum else None


def _point(value):
    if not isinstance(value, dict):
        return None
    x, y = _number(value.get("x")), _number(value.get("y"))
    return {"x": x, "y": y} if x is not None and y is not None else None


def _viewport(value):
    if not isinstance(value, dict):
        return None
    width, height = _number(value.get("width")), _number(value.get("height"))
    return {"width": width, "height": height} if width and height else None


class ScreenHub:
    def __init__(self, state_dir):
        self.state_dir = Path(state_dir).expanduser().resolve()
        self.state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._state_path = self.state_dir / "screen-state.json"
        self._lock_path = self.state_dir / ".screen-state.lock"
        self._lock = threading.RLock()
        self._thread = None
        self._child = None
        self._stop = threading.Event()
        self._lease_until = 0.0
        self._frame = None
        self._seq = 0
        self._stream_id = uuid.uuid4().hex
        atexit.register(self.close)

    @staticmethod
    def _now():
        return int(time.time() * 1000)

    def _read_state(self):
        try:
            raw = json.loads(self._state_path.read_text())
        except (OSError, ValueError):
            raw = {}
        if not isinstance(raw, dict):
            raw = {}
        now = self._now()
        actors = raw.get("actors", {})
        actors = {key: at for key, at in actors.items()
                  if isinstance(key, str) and re.fullmatch(r"[0-9a-f]{32}", key)
                  and isinstance(at, int) and 0 <= now - at < BUSY_AGE_MS} if isinstance(actors, dict) else {}
        events = []
        for event in raw.get("events", [])[-32:] if isinstance(raw.get("events"), list) else []:
            if not isinstance(event, dict) or event.get("kind") not in ("tap", "drag"):
                continue
            at, identifier = event.get("at"), event.get("id")
            if not isinstance(at, int) or not isinstance(identifier, int) or not 0 <= now - at < EVENT_AGE_MS:
                continue
            clean = {"id": identifier, "kind": event["kind"], "at": at}
            if event["kind"] == "tap":
                point = _point(event.get("point"))
                if point is None:
                    continue
                clean["point"] = point
            else:
                origin, destination = _point(event.get("from")), _point(event.get("to"))
                duration = _number(event.get("duration_ms"), maximum=5000)
                if origin is None or destination is None or duration is None:
                    continue
                clean.update({"from": origin, "to": destination, "duration_ms": duration})
            viewport = _viewport(event.get("viewport"))
            if viewport:
                clean["viewport"] = viewport
            events.append(clean)
        last_id = raw.get("last_event_id", 0)
        finished_at = raw.get("finished_at", 0)
        return {"paused": raw.get("paused") is True, "actors": dict(list(actors.items())[-32:]),
                "events": events, "last_event_id": last_id if isinstance(last_id, int) and last_id >= 0 else 0,
                "finished_at": finished_at if isinstance(finished_at, int)
                and 0 <= now - finished_at < ACTIVITY_GRACE_MS else 0,
                "viewport": _viewport(raw.get("viewport"))}

    @contextlib.contextmanager
    def _state_transaction(self):
        descriptor = os.open(self._lock_path, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            os.fchmod(descriptor, 0o600)
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            state = self._read_state()
            yield state
            fd, temporary = tempfile.mkstemp(prefix=".screen-", dir=self.state_dir)
            try:
                os.fchmod(fd, 0o600)
                with os.fdopen(fd, "w") as stream:
                    json.dump(state, stream, separators=(",", ":"), allow_nan=False)
                os.replace(temporary, self._state_path)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)

    def _wire(self, state, after_seq=0, last_event_id=0):
        with self._lock:
            frame = self._frame if not state["paused"] else None
            if frame and frame["seq"] == after_seq:
                frame = None
            return {"server_time": self._now(), "frame": dict(frame) if frame else None,
                    "stream_id": self._stream_id,
                    "frame_available": self._frame is not None and not state["paused"],
                    "viewport": state["viewport"],
                    "busy": bool(state["actors"] or state["finished_at"]) and not state["paused"],
                    "paused": state["paused"],
                    "events": [event for event in state["events"] if event["id"] > last_event_id]
                    if not state["paused"] else []}

    def start(self):
        """Fast initial widget metadata. Capture starts only on a live frame poll."""
        result = self._wire(self._read_state())
        result["frame"] = None
        return result

    def frame(self, after_seq=0, last_event_id=0):
        state = self._read_state()
        if state["paused"]:
            self.close()
        else:
            with self._lock:
                self._lease_until = time.monotonic() + FRAME_LEASE_SECONDS
                if self._thread is None or not self._thread.is_alive():
                    self._stop = threading.Event()
                    self._thread = threading.Thread(target=self._run, args=(self._stop,), daemon=True,
                                                    name="wda-screen-stream")
                    self._thread.start()
        return self._wire(state, after_seq, last_event_id)

    def close(self):
        with self._lock:
            self._lease_until = 0
            self._stop.set()
            child = self._child
            self._frame = None
        if child and child.poll() is None:
            try:
                child.terminate()
            except OSError:
                pass

    def set_paused(self, paused):
        with self._state_transaction() as state:
            state["paused"] = bool(paused)
            if paused:
                state["actors"] = {}
                state["finished_at"] = 0
                state["events"] = []
        if paused:
            self.close()
        return self._wire(self._read_state())

    def set_viewport(self, viewport):
        cleaned = _viewport(viewport)
        if cleaned:
            with self._state_transaction() as state:
                state["viewport"] = cleaned

    def begin(self, op):
        # Operation names, app IDs, text and selectors are deliberately not stored.
        token = uuid.uuid4().hex
        with self._state_transaction() as state:
            if not state["paused"]:
                state["actors"][token] = self._now()
        return token

    def end(self, token):
        with self._state_transaction() as state:
            if state["actors"].pop(token, None) is not None and not state["paused"]:
                state["finished_at"] = self._now()

    def gesture(self, kind, point=None, from_point=None, to_point=None, duration_ms=0, viewport=None):
        if kind == "tap":
            cleaned = _point(point)
            if cleaned is None:
                return
            payload = {"point": cleaned}
        elif kind == "drag":
            origin, destination = _point(from_point), _point(to_point)
            duration = _number(duration_ms, maximum=5000)
            if origin is None or destination is None or duration is None:
                return
            payload = {"from": origin, "to": destination, "duration_ms": duration}
        else:
            return
        with self._state_transaction() as state:
            if state["paused"]:
                return
            state["last_event_id"] += 1
            event = {"id": state["last_event_id"], "kind": kind, "at": self._now(), **payload}
            cleaned_viewport = _viewport(viewport) or state["viewport"]
            if cleaned_viewport:
                event["viewport"] = cleaned_viewport
            state["events"] = (state["events"] + [event])[-32:]

    def _live(self, stop):
        with self._lock:
            lease_live = time.monotonic() < self._lease_until
        return lease_live and not stop.is_set() and not self._read_state()["paused"]

    def _command(self):
        try:
            config = json.loads((self.state_dir / "config.json").read_text())
            udid = config.get("udid")
            port = config.get("mjpeg_device_port", 9100)
            if not isinstance(udid, str) or not re.fullmatch(r"[A-Za-z0-9-]{8,64}", udid):
                return None
            if isinstance(port, bool) or not isinstance(port, int) or not 1024 <= port <= 65535:
                return None
            node = shutil.which("node")
            runtime = self.state_dir / "runtime/forward"
            source = Path(__file__).resolve().parents[1] / "tooling/screen-stream.mjs"
            if not node or not (runtime / "node_modules/appium-ios-device").is_dir() or not source.is_file():
                return None
            target = runtime / "screen-stream.mjs"
            source_bytes = source.read_bytes()
            if not target.is_file() or target.read_bytes() != source_bytes:
                fd, temporary = tempfile.mkstemp(prefix=".screen-stream-", dir=runtime)
                try:
                    os.fchmod(fd, 0o600)
                    with os.fdopen(fd, "wb") as stream:
                        stream.write(source_bytes)
                    os.replace(temporary, target)
                finally:
                    if os.path.exists(temporary):
                        os.unlink(temporary)
            return [node, str(target), udid, str(port)]
        except (OSError, ValueError, AttributeError):
            return None

    @staticmethod
    def _terminate(child):
        if child is None:
            return
        try:
            if child.poll() is None:
                child.terminate()
            child.wait(timeout=0.5)
        except subprocess.TimeoutExpired:
            child.kill()
            try:
                child.wait(timeout=0.5)
            except subprocess.TimeoutExpired:
                pass
        except OSError:
            pass
        if child.stdout:
            child.stdout.close()

    def _run(self, stop):
        backoff = 0.5
        while self._live(stop):
            child = None
            received = False
            try:
                command = self._command()
                if command:
                    child = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                             stderr=subprocess.DEVNULL, bufsize=0)
                    with self._lock:
                        self._child = child
                    parser = MJPEGParser()
                    while self._live(stop) and child.poll() is None:
                        ready, _, _ = select.select([child.stdout], [], [], 0.1)
                        if not ready:
                            continue
                        chunk = os.read(child.stdout.fileno(), 65536)
                        if not chunk:
                            break
                        for raw, (width, height) in parser.feed(chunk):
                            if not self._live(stop):
                                break
                            with self._lock:
                                self._seq += 1
                                self._frame = {"seq": self._seq, "data": base64.b64encode(raw).decode("ascii"),
                                               "mimeType": "image/jpeg", "width": width, "height": height}
                            received = True
            except (OSError, ValueError):
                # A missing device/stream shows a blank screen, never a red tool error.
                pass
            finally:
                self._terminate(child)
                with self._lock:
                    if self._child is child:
                        self._child = None
                        self._frame = None
            if received:
                backoff = 0.5
            deadline = time.monotonic() + backoff
            while self._live(stop) and time.monotonic() < deadline:
                stop.wait(0.1)
            backoff = min(2, backoff * 2)
        with self._lock:
            self._frame = None
