"""Loopback-only development bridge. Packaged Tauri uses stdio, not HTTP."""

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from . import __version__, store
from .cli import api


class Handler(BaseHTTPRequestHandler):
    def send(self, status, value):
        data = json.dumps(value, ensure_ascii=False, allow_nan=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        origin = self.headers.get("Origin")
        if origin and origin not in (
            "http://127.0.0.1:1420",
            "http://localhost:1420",
            "http://127.0.0.1:4317",
            "http://localhost:4317",
        ):
            self.send(403, dict(ok=False, error=dict(message="来源不受信任")))
            return
        path = urlsplit(self.path)
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if path.path == "/api/upload":
                if length <= 0 or length > 2 * 1024**3:
                    raise ValueError("文件大小应为 1B–2GB")
                name = parse_qs(path.query).get("name", ["upload"])[0]
                if name in (".", "..") or any(c in name for c in "/\\\0\r\n"):
                    raise ValueError("文件名无效")
                destination = store.root() / "uploads" / store.uid() / name
                destination.parent.mkdir(parents=True)
                try:
                    with destination.open("wb") as stream:
                        remaining = length
                        while remaining:
                            chunk = self.rfile.read(min(remaining, 1024 * 1024))
                            if not chunk:
                                raise ValueError("文件传输不完整")
                            stream.write(chunk)
                            remaining -= len(chunk)
                except Exception:
                    destination.unlink(missing_ok=True)
                    raise
                self.send(200, dict(ok=True, data=dict(path=str(destination))))
                return
            if (
                path.path != "/api"
                or self.headers.get("Content-Type", "").split(";")[0] != "application/json"
                or not 0 < length <= 2 * 1024**2
            ):
                self.send(400, dict(ok=False, error=dict(message="无效 API 请求")))
                return
            request = json.loads(self.rfile.read(length))
            self.send(
                200,
                dict(ok=True, data=api(request["command"], request.get("args", {}))),
            )
        except Exception as exc:
            self.send(
                200,
                dict(ok=False, error=dict(code=type(exc).__name__, message=str(exc))),
            )

    def do_GET(self):
        self.send(200, dict(version=__version__, mode="development bridge"))


def serve(port):
    print(f"ModelDock development bridge: http://127.0.0.1:{port}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
