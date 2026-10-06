"""Direct, persistent WDA HTTP transport. No Appium server, no action replay."""
import collections
import http.client
import json
import socket
import time
from urllib.parse import urlsplit


class WDAError(Exception):
    def __init__(self, code, message, uncertain=False, details=None):
        super().__init__(message)
        self.code, self.uncertain, self.details = code, uncertain, details or {}

    def as_dict(self):
        return {"code": self.code, "message": str(self), "uncertain": self.uncertain, **self.details}


class WDAClient:
    def __init__(self, base_url="http://127.0.0.1:18100", timeout=15):
        parsed = urlsplit(base_url)
        if parsed.scheme != "http" or parsed.hostname not in ("127.0.0.1", "localhost", "::1") or parsed.path not in ("", "/") or parsed.username or parsed.query or parsed.fragment:
            raise ValueError("WDA URL must be a local HTTP endpoint; forward USB to loopback first.")
        self.host, self.port = parsed.hostname, parsed.port or 80
        self.timeout, self.connection, self.session_id = timeout, None, None
        self.records = collections.deque(maxlen=2000)

    def close(self):
        if self.connection:
            self.connection.close()
        self.connection = None

    def request(self, method, path, payload=None, timeout=None):
        # Read retries are handled only by the session wrapper for an explicit invalid session.
        # Even a disconnected keep-alive socket is never used to replay a mutation.
        started = time.monotonic()
        status, code = None, None
        budget = timeout or self.timeout
        try:
            if self.connection is None:
                self.connection = http.client.HTTPConnection(self.host, self.port, timeout=budget)
            self.connection.timeout = budget
            if self.connection.sock:
                self.connection.sock.settimeout(budget)
            body = None if payload is None else json.dumps(payload, ensure_ascii=False, allow_nan=False).encode()
            self.connection.request(method, path, body, {"Content-Type": "application/json", "Accept": "application/json"})
            response = self.connection.getresponse()
            status = response.status
            raw = response.read(24 * 1024 * 1024 + 1)
            if len(raw) > 24 * 1024 * 1024:
                raise WDAError("response_too_large", "WDA response exceeds 24 MiB.", uncertain=method != "GET")
            try:
                result = json.loads(raw)
            except (ValueError, UnicodeDecodeError) as exc:
                raise WDAError("invalid_response", "WDA returned invalid JSON.", uncertain=method != "GET") from exc
            if not isinstance(result, dict):
                raise WDAError("invalid_response", "WDA returned a non-object.", uncertain=method != "GET")
            value = result.get("value")
            if isinstance(value, dict) and value.get("error"):
                code = value["error"]
                raise WDAError(code, value.get("message", code)[:1500])
            if status >= 400:
                raise WDAError("http_error", f"WDA returned HTTP {status}.", uncertain=method != "GET")
            return result
        except WDAError as exc:
            code = exc.code
            if exc.uncertain:
                self.close()
            raise
        except (OSError, socket.timeout, http.client.HTTPException) as exc:
            self.close()
            code = "action_uncertain" if method != "GET" else "wda_unreachable"
            raise WDAError(code, "WDA connection failed or timed out. Read fresh state before deciding whether to repeat an action.", uncertain=method != "GET") from exc
        finally:
            # No text, predicates, values, screenshots, app IDs or device identifiers in metrics.
            endpoint = path.split("?")[0]
            if endpoint.startswith("/session/"):
                endpoint = "/session/:id/" + "/".join(endpoint.split("/")[3:])
            if "/element/" in endpoint:
                parts = endpoint.split("/")
                idx = parts.index("element") + 1
                if idx < len(parts):
                    parts[idx] = ":id"
                endpoint = "/".join(parts)
            self.records.append({"method": method, "endpoint": endpoint, "seconds": round(time.monotonic()-started, 4), "status": status, "error": code})

    def ensure_session(self):
        if not self.session_id:
            result = self.request("POST", "/session", {"capabilities": {"alwaysMatch": {
                "shouldWaitForQuiescence": False, "shouldTerminateApp": False,
                "waitForIdleTimeout": 0.5, "maxTypingFrequency": 30}}}, timeout=30)
            value = result.get("value") or {}
            self.session_id = result.get("sessionId") or value.get("sessionId")
            if not self.session_id:
                raise WDAError("invalid_response", "WDA did not return a session ID.")
        return self.session_id

    def session(self, method, path, payload=None, timeout=None):
        sid = self.ensure_session()
        try:
            return self.request(method, f"/session/{sid}{path}", payload, timeout).get("value")
        except WDAError as exc:
            if exc.code == "invalid session id":
                self.session_id = None
                # A rejected invalid-session command did not execute. Nevertheless only replay reads.
                if method == "GET" and not path.startswith("/element/"):
                    sid = self.ensure_session()
                    return self.request(method, f"/session/{sid}{path}", payload, timeout).get("value")
            raise

    def metrics(self):
        endpoints = collections.defaultdict(list)
        for record in self.records:
            endpoints[record["endpoint"]].append(record["seconds"])
        return {"retained_requests": len(self.records), "http_seconds": round(sum(r["seconds"] for r in self.records),4),
                "errors": sum(bool(r["error"]) for r in self.records),
                "endpoints": {k: {"count": len(v), "seconds": round(sum(v),4), "max_seconds": max(v)} for k,v in endpoints.items()},
                "measurement": "Transport time only; model, host scheduling and user wait are outside this process."}
