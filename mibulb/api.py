"""A small local web API, so a Stream Deck, a script or Home Assistant can control Mi Bulb.

Off unless turned on in Settings -> App. Every request needs the API key
(?key=... or an X-API-Key header). By default only this PC can connect; you
can also allow other devices on your network.

    GET /api/status                      what the light is doing
    GET /api/on | /api/off | /api/toggle
    GET /api/brightness?value=40         also value=up / value=down (±10)
    GET /api/white?kelvin=2700
    GET /api/color?hex=ff8800
    GET /api/scene?name=Relax
    GET /api/effect?name=candle          /api/effect?name=stop to stop
    GET /api/sleep?minutes=30            minutes=0 cancels
    GET /api/screen-sync | /api/music-sync   (toggle)
    GET /api/light?name=Bed              pick a bulb, or name=all

POST works the same as GET. Answers are JSON.
"""

from __future__ import annotations

import hmac
import json
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse

DEFAULT_PORT = 8765


def new_key() -> str:
    return secrets.token_urlsafe(18)


class ApiError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


class ApiServer:
    """Runs on its own thread. handle(command, params) does the work and returns a JSON-able answer."""

    def __init__(self, handle: Callable[[str, dict[str, str]], Any], key: str, port: int = DEFAULT_PORT,
                 lan: bool = False):
        self._handle = handle
        self._key = key
        self.port = port
        self.host = "0.0.0.0" if lan else "127.0.0.1"
        self._server: ThreadingHTTPServer | None = None

    def start(self) -> None:
        api = self

        class Handler(BaseHTTPRequestHandler):
            server_version = "MiBulb"

            def do_GET(self) -> None:  # noqa: N802 (name required by http.server)
                api._serve(self)

            do_POST = do_GET

            def log_message(self, *args: Any) -> None:
                pass  # keep the console quiet

        self._server = ThreadingHTTPServer((self.host, self.port), Handler)
        self.port = self._server.server_address[1]  # the real port, if 0 ("any free port") was asked for
        threading.Thread(target=self._server.serve_forever, daemon=True).start()

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None

    def _serve(self, request: BaseHTTPRequestHandler) -> None:
        url = urlparse(request.path)
        params = {k: v[-1] for k, v in parse_qs(url.query).items()}
        if request.command == "POST":
            length = int(request.headers.get("Content-Length") or 0)
            body = request.rfile.read(min(length, 10000)).decode("utf-8", "replace") if length else ""
            if body.strip().startswith("{"):
                try:
                    params.update({k: str(v) for k, v in json.loads(body).items()})
                except (ValueError, AttributeError):
                    pass
            else:
                params.update({k: v[-1] for k, v in parse_qs(body).items()})
        key = request.headers.get("X-API-Key") or params.pop("key", "")
        try:
            if not hmac.compare_digest(key.encode(), self._key.encode()):
                raise ApiError(401, "Missing or wrong API key")
            if not url.path.startswith("/api/"):
                raise ApiError(404, "Unknown address; see /api/status")
            answer = self._handle(url.path[len("/api/"):].strip("/"), params)
            status, payload = 200, {"ok": True, **(answer or {})}
        except ApiError as exc:
            status, payload = exc.status, {"ok": False, "error": str(exc)}
        except Exception as exc:  # never let a request crash the server
            status, payload = 500, {"ok": False, "error": str(exc)}
        data = json.dumps(payload).encode("utf-8")
        request.send_response(status)
        request.send_header("Content-Type", "application/json")
        request.send_header("Content-Length", str(len(data)))
        request.end_headers()
        request.wfile.write(data)
