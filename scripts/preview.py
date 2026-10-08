#!/usr/bin/env python3
"""Host the existing MCP App locally when the chat cannot open an MCP App panel."""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import secrets
import signal
import subprocess
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))
from iphone_use import PUAError, Runtime, tool_result
from wda_client import WDAClient


HOST_HTML = '''<!doctype html><html lang="ja"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>iPhone ライブプレビュー</title>
<style>html,body{margin:0;width:100%;height:100%;background:#111}iframe{border:0;width:100%;height:100%;display:block}</style>
<iframe id="phone" title="iPhoneのライブ画面" src="widget"></iframe>
<script>
const phone=document.getElementById('phone');
const base=location.pathname;
window.addEventListener('message', async event=>{
  if(event.source!==phone.contentWindow || event.origin!==location.origin) return;
  const request=event.data;
  if(!request || request.jsonrpc!=='2.0' || typeof request.method!=='string') return;
  let result;
  try {
    if(request.method==='ui/initialize') result={
      protocolVersion:request.params.protocolVersion,
      hostInfo:{name:'iPhone Use Browser',version:'1'},hostCapabilities:{serverTools:{}},
      hostContext:{theme:'dark',displayMode:'fullscreen',availableDisplayModes:['fullscreen'],
        platform:'desktop',locale:'ja-JP',timeZone:'Asia/Tokyo',
        containerDimensions:{width:innerWidth,height:innerHeight}}};
    else if(request.method==='ui/request-display-mode') result={mode:'fullscreen'};
    else if(request.method==='tools/call') {
      const response=await fetch(base+'rpc',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(request.params)});
      if(!response.ok) throw Error('プレビューへの接続に失敗しました');
      result=await response.json();
    } else if(request.method==='ping') result={};
    else if(!('id' in request)) return;
    else throw Error('未対応のリクエストです');
    if('id' in request) phone.contentWindow.postMessage({jsonrpc:'2.0',id:request.id,result},location.origin);
  } catch(error) {
    if('id' in request) phone.contentWindow.postMessage({jsonrpc:'2.0',id:request.id,error:{code:-32603,message:String(error)}},location.origin);
  }
});
</script></html>'''


class PreviewServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, runtime, port=0, token=None):
        self.runtime = runtime
        self.token = token or secrets.token_urlsafe(32)
        self.widget = (ROOT / "assets/phone-screen.html").read_bytes()
        self.probe = WDAClient(runtime.base_url, timeout=2)
        self.probe_lock = threading.Lock()
        self.last_probe = 0
        super().__init__(("127.0.0.1", port), PreviewHandler)
        self.origin = "http://127.0.0.1:" + str(self.server_port)
        self.url = self.origin + "/" + self.token + "/"

    def guard_lock(self):
        # Check lock state, never XML or screenshots, before exposing live frames.
        # Authentication pauses require the existing explicit resume workflow.
        with self.probe_lock:
            state = self.runtime.screen.pause_status()
            if state["paused"] and state["pause_reason"] != "device_locked":
                return
            if time.monotonic() - self.last_probe < 1:
                return
            try:
                locked = self.probe.request("GET", "/wda/locked").get("value") is not False
            except PUAError:
                self.runtime.screen.close()
                raise
            self.last_probe = time.monotonic()
            if locked and not state["paused"]:
                self.runtime.screen.set_paused(True, reason="device_locked")
            # Unlock alone does not resume. The user's Refresh button does.

    def dispatch(self, params):
        if not isinstance(params, dict) or params.get("name") not in ("pua_screen_frame", "pua_screen_action"):
            raise ValueError("Only the preview App's frame and toolbar requests are available.")
        if params["name"] == "pua_screen_frame":
            self.guard_lock()
        return tool_result(self.runtime, params)

    def server_close(self):
        super().server_close()
        self.probe.close()


class PreviewHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # URLs contain the private local access token.

    def send(self, status, data, mime="application/json"):
        self.send_response(status)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data:; connect-src 'self'; frame-src 'self'; font-src data:; base-uri 'none'; form-action 'none'; frame-ancestors 'self'")
        self.end_headers()
        self.wfile.write(data)

    def allowed(self):
        return (self.headers.get("Host") == self.server.origin.removeprefix("http://")
                and self.headers.get("Origin", self.server.origin) == self.server.origin
                and self.path.startswith("/" + self.server.token + "/"))

    def do_GET(self):
        if not self.allowed():
            self.send(403, b'{}')
        elif self.path == "/" + self.server.token + "/":
            self.send(200, HOST_HTML.encode(), "text/html; charset=utf-8")
        elif self.path == "/" + self.server.token + "/widget":
            self.send(200, self.server.widget, "text/html; charset=utf-8")
        else:
            self.send(404, b'{}')

    def do_POST(self):
        if not self.allowed() or self.path != "/" + self.server.token + "/rpc":
            self.send(403, b'{}')
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 65536:
                raise ValueError("Invalid request size")
            result = self.server.dispatch(json.loads(self.rfile.read(length)))
            self.send(200, json.dumps(result, ensure_ascii=False).encode())
        except (ValueError, TypeError):
            self.send(400, b'{"error":"invalid_preview_request"}')
        except PUAError as exc:
            self.send(200, json.dumps({"isError": True, "content": [], "structuredContent": {"error": exc.as_dict()}}).encode())


def load_registered_settings():
    """Reuse the installed MCP's external state without copying private settings."""
    try:
        registered = subprocess.run(["codex", "mcp", "get", "iphone_use", "--json"],
                                    capture_output=True, text=True, check=False)
    except FileNotFoundError:
        return
    if registered.returncode:
        return
    environment = json.loads(registered.stdout).get("transport", {}).get("env") or {}
    for key in ("IPHONE_USE_STATE_DIR", "WDA_STATE_DIR", "WDA_URL", "DEVELOPER_DIR"):
        if isinstance(environment.get(key), str):
            os.environ.setdefault(key, environment[key])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir")
    parser.add_argument("--port", type=int, default=0)
    args = parser.parse_args()
    load_registered_settings()
    runtime = Runtime(args.state_dir)
    server = PreviewServer(runtime, args.port)
    def stop(signum, frame):
        threading.Thread(target=server.shutdown, daemon=True).start()
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        runtime.call("pua_screen", {})
        print(json.dumps({"url": server.url}), flush=True)
        server.serve_forever()
    finally:
        server.server_close()
        runtime.close()


if __name__ == "__main__":
    main()
