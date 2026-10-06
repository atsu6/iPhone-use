import contextlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sys
import threading
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))
from wda_client import WDAClient, WDAError


@contextlib.contextmanager
def fake_server(responder):
    requests = []
    peer_ports = []

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args):
            pass

        def handle(self):
            try:
                super().handle()
            except (BrokenPipeError, ConnectionResetError):
                # The timeout test intentionally closes its client socket mid-response.
                pass

        def handle_request(self):
            size = int(self.headers.get("Content-Length", 0))
            payload = json.loads(self.rfile.read(size)) if size else None
            requests.append((self.command, self.path, payload))
            peer_ports.append(self.client_address[1])
            status, value, delay, close = responder(self.command, self.path, payload, requests)
            if delay:
                time.sleep(delay)
            raw = json.dumps(value, ensure_ascii=False).encode("utf-8")
            try:
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                if close:
                    self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.write(raw)
            except (BrokenPipeError, ConnectionResetError):
                pass
            self.close_connection = close

        do_GET = handle_request
        do_POST = handle_request

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        yield "http://127.0.0.1:%s" % server.server_port, requests, peer_ports
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=2)


class ClientTests(unittest.TestCase):
    def test_reuses_http_connection_and_obeys_server_close(self):
        def respond(method, path, body, requests):
            return 200, {"value": {"ready": True}}, 0, path == "/close"

        with fake_server(respond) as (url, requests, ports):
            client = WDAClient(url)
            try:
                for path in ("/status", "/status", "/close", "/status"):
                    self.assertTrue(client.request("GET", path)["value"]["ready"])
                self.assertEqual(ports[:3], [ports[0]] * 3)
                self.assertNotEqual(ports[2], ports[3])
                self.assertEqual(len(requests), 4)
            finally:
                client.close()

    def test_explicit_invalid_session_read_creates_one_session_and_retries_once(self):
        def respond(method, path, body, requests):
            if path == "/session":
                return 200, {"value": {"sessionId": "fresh"}}, 0, False
            if path == "/session/expired/window/size":
                return 404, {"value": {"error": "invalid session id", "message": "Expired"}}, 0, False
            return 200, {"value": {"width": 390, "height": 844}}, 0, False

        with fake_server(respond) as (url, requests, _):
            client = WDAClient(url)
            client.session_id = "expired"
            try:
                self.assertEqual(client.session("GET", "/window/size"), {"width": 390, "height": 844})
                self.assertEqual([(r[0], r[1]) for r in requests], [
                    ("GET", "/session/expired/window/size"), ("POST", "/session"),
                    ("GET", "/session/fresh/window/size")])
                self.assertEqual(client.session_id, "fresh")
            finally:
                client.close()

    def test_explicit_invalid_session_mutation_is_not_replayed(self):
        def respond(method, path, body, requests):
            return 404, {"value": {"error": "invalid session id", "message": "Expired"}}, 0, False

        with fake_server(respond) as (url, requests, _):
            client = WDAClient(url)
            client.session_id = "expired"
            try:
                with self.assertRaises(WDAError) as caught:
                    client.session("POST", "/wda/tap", {"x": 100, "y": 200})
                self.assertEqual(caught.exception.code, "invalid session id")
                self.assertFalse(caught.exception.uncertain)
                self.assertIsNone(client.session_id)
                self.assertEqual(len(requests), 1)
            finally:
                client.close()

    def test_expired_element_read_is_not_replayed_in_new_session(self):
        def respond(method, path, body, requests):
            return 404, {"value": {"error": "invalid session id", "message": "Expired"}}, 0, False

        with fake_server(respond) as (url, requests, _):
            client = WDAClient(url)
            client.session_id = "expired"
            try:
                with self.assertRaises(WDAError) as caught:
                    client.session("GET", "/element/expired-element/attribute/value")
                self.assertEqual(caught.exception.code, "invalid session id")
                self.assertIsNone(client.session_id)
                self.assertEqual([(method, path) for method, path, _ in requests], [
                    ("GET", "/session/expired/element/expired-element/attribute/value")])
            finally:
                client.close()

    def test_mutation_timeout_is_uncertain_and_never_replayed(self):
        def respond(method, path, body, requests):
            return 200, {"value": None}, 0.15, False

        with fake_server(respond) as (url, requests, _):
            client = WDAClient(url, timeout=0.025)
            client.session_id = "existing"
            try:
                with self.assertRaises(WDAError) as caught:
                    client.session("POST", "/wda/tap", {"x": 100, "y": 200})
                self.assertEqual(caught.exception.code, "action_uncertain")
                self.assertTrue(caught.exception.uncertain)
                self.assertIsNone(client.connection)
                self.assertEqual(len(requests), 1)
                self.assertEqual(client.records[-1]["endpoint"], "/session/:id/wda/tap")
            finally:
                client.close()

    def test_non_session_read_error_does_not_trigger_retry(self):
        def respond(method, path, body, requests):
            return 500, {"value": {"error": "unknown error", "message": "Backend failed"}}, 0, False

        with fake_server(respond) as (url, requests, _):
            client = WDAClient(url)
            client.session_id = "existing"
            try:
                with self.assertRaises(WDAError) as caught:
                    client.session("GET", "/source")
                self.assertEqual(caught.exception.code, "unknown error")
                self.assertEqual(client.session_id, "existing")
                self.assertEqual(len(requests), 1)
            finally:
                client.close()

    def test_utf8_payload_and_metrics_do_not_retain_user_content_or_ids(self):
        phrase = "你好 👋 Café 漢字"

        def respond(method, path, body, requests):
            return 200, {"value": phrase}, 0, False

        with fake_server(respond) as (url, requests, _):
            client = WDAClient(url)
            client.session_id = "private-device-session"
            try:
                value = client.session("POST", "/element/private-element/value", {"text": phrase})
                self.assertEqual(value, phrase)
                self.assertEqual(requests[0][2]["text"], phrase)
                metrics = json.dumps(client.metrics(), ensure_ascii=False)
                for sensitive in (phrase, "private-device-session", "private-element"):
                    self.assertNotIn(sensitive, metrics)
                self.assertIn("/session/:id/element/:id/value", metrics)
            finally:
                client.close()

    def test_rejects_remote_or_decorated_urls(self):
        for url in ("http://192.168.1.2:8100", "https://localhost:8100", "http://user@localhost", "http://localhost/api", "http://localhost?token=x"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                WDAClient(url)


if __name__ == "__main__":
    unittest.main()
