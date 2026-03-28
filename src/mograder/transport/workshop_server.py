"""Workshop server for instructor dashboard and WASM notebook serving.

Provides both a stdlib ``BaseHTTPRequestHandler`` (for ``mograder workshop serve``)
and a Starlette app factory (for ``demo_app.py`` ASGI integration).

Routes:
    GET  /keys.json              — current released keys (public, no-cache)
    GET  /workshop/exercises     — list exercises + release state (token-protected)
    POST /workshop/release       — toggle one exercise (token-protected)
    POST /workshop/release-all   — release or lock all exercises (token-protected)
    GET  /dashboard.html         — instructor dashboard (token-protected)
    GET  /*                      — static files from export dir (public)
"""

from __future__ import annotations

import json
import mimetypes
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from mograder.core._utils import add_cors_to_response, cors_headers as _cors_header_dict


# ---------------------------------------------------------------------------
# Shared pure-function logic (used by both stdlib and Starlette)
# ---------------------------------------------------------------------------


def _get_exercises_state(keys_all: dict, keys_path: Path) -> dict:
    """Return ``{"exercises": [...], "released": {...}}``."""
    exercises = list(keys_all.keys())
    released = {}
    if keys_path.is_file():
        current = json.loads(keys_path.read_text())
        for ex in exercises:
            released[ex] = ex in current
    return {"exercises": exercises, "released": released}


def _do_release(keys_path: Path, keys_all: dict, exercise: str, released: bool) -> dict:
    """Release or lock a single exercise. Returns updated state."""
    current = {}
    if keys_path.is_file():
        current = json.loads(keys_path.read_text())

    if released:
        current[exercise] = keys_all.get(exercise, True)
    else:
        current.pop(exercise, None)

    keys_path.write_text(json.dumps(current, indent=2) + "\n")
    return _get_exercises_state(keys_all, keys_path)


def _do_release_all(keys_path: Path, keys_all: dict, released: bool) -> dict:
    """Release or lock all exercises. Returns updated state."""
    if released:
        current = dict(keys_all)
    else:
        current = {}

    keys_path.write_text(json.dumps(current, indent=2) + "\n")
    return _get_exercises_state(keys_all, keys_path)


# ---------------------------------------------------------------------------
# Stdlib handler
# ---------------------------------------------------------------------------


class WorkshopHandler(BaseHTTPRequestHandler):
    """HTTP handler for workshop server."""

    server: WorkshopServer  # type: ignore[assignment]

    def log_message(self, format, *args):
        """Suppress default logging."""

    def _send_json(self, data, status=200):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        for k, v in _cors_header_dict(headers="Content-Type").items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path: Path, content_type: str | None = None):
        if not path.is_file():
            self._send_json({"error": "Not found"}, 404)
            return
        data = path.read_bytes()
        if content_type is None:
            content_type = (
                mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            )
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(data)

    def _check_token(self) -> bool:
        """Verify token query param. Returns True if valid."""
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)
        token = qs.get("token", [None])[0]
        if token != self.server.secret:
            self._send_json({"error": "Forbidden"}, 403)
            return False
        return True

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")

        if path == "/keys.json":
            self.send_response(200)
            keys_path = self.server.keys_path
            data = keys_path.read_bytes() if keys_path.is_file() else b"{}"
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(data)
            return

        if path == "/workshop/exercises":
            if not self._check_token():
                return
            with self.server.lock:
                state = _get_exercises_state(
                    self.server.keys_all, self.server.keys_path
                )
            self._send_json(state)
            return

        if path == "/dashboard.html":
            # No auth — the HTML is static; API endpoints check the token
            self._send_file(self.server.export_dir / "dashboard.html", "text/html")
            return

        # Static files from export dir
        if path in ("", "/"):
            # Serve index.html or first .html file
            index = self.server.export_dir / "index.html"
            if index.is_file():
                self._send_file(index, "text/html")
                return
            # Find first HTML file that's not dashboard.html
            for f in sorted(self.server.export_dir.iterdir()):
                if f.suffix == ".html" and f.name != "dashboard.html":
                    self._send_file(f, "text/html")
                    return
            self._send_json({"error": "No index file found"}, 404)
            return

        # Serve static file
        file_path = self.server.export_dir / path.lstrip("/")
        if file_path.is_file():
            self._send_file(file_path)
        else:
            self._send_json({"error": "Not found"}, 404)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")

        if path == "/workshop/release":
            if not self._check_token():
                return
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length)
            try:
                data = json.loads(body)
            except json.JSONDecodeError:
                self._send_json({"error": "Invalid JSON"}, 400)
                return
            exercise = data.get("exercise", "")
            released = data.get("released", True)
            if not exercise:
                self._send_json({"error": "Missing 'exercise' field"}, 400)
                return
            with self.server.lock:
                state = _do_release(
                    self.server.keys_path, self.server.keys_all, exercise, released
                )
            self._send_json(state)
            return

        if path == "/workshop/release-all":
            if not self._check_token():
                return
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length)
            try:
                data = json.loads(body)
            except json.JSONDecodeError:
                self._send_json({"error": "Invalid JSON"}, 400)
                return
            released = data.get("released", True)
            with self.server.lock:
                state = _do_release_all(
                    self.server.keys_path, self.server.keys_all, released
                )
            self._send_json(state)
            return

        self._send_json({"error": "Not found"}, 404)


class WorkshopServer(HTTPServer):
    """HTTPServer subclass storing workshop state."""

    def __init__(
        self,
        server_address,
        handler_class,
        export_dir: Path,
        keys_path: Path,
        keys_all: dict,
        secret: str,
    ):
        self.export_dir = export_dir.resolve()
        self.keys_path = keys_path.resolve()
        self.keys_all = keys_all
        self.secret = secret
        self.lock = threading.Lock()
        super().__init__(server_address, handler_class)


def create_workshop_server(
    export_dir: Path,
    keys_path: Path,
    keys_all: dict,
    secret: str,
    host: str = "127.0.0.1",
    port: int = 8080,
) -> WorkshopServer:
    """Create a workshop server."""
    return WorkshopServer(
        (host, port),
        WorkshopHandler,
        export_dir=export_dir,
        keys_path=keys_path,
        keys_all=keys_all,
        secret=secret,
    )


# ---------------------------------------------------------------------------
# Starlette app factory
# ---------------------------------------------------------------------------


def create_workshop_starlette_routes(
    export_dir: Path,
    keys_path: Path,
    keys_all: dict,
    secret: str,
):
    """Create a Starlette app serving the workshop dashboard API.

    Same endpoints as ``WorkshopHandler`` but as async Starlette routes.
    Import is deferred so the stdlib server path doesn't require starlette.
    """
    from starlette.applications import Starlette
    from starlette.requests import Request
    from starlette.responses import FileResponse, JSONResponse, Response
    from starlette.routing import Mount, Route
    from starlette.staticfiles import StaticFiles

    resolved_export = export_dir.resolve()
    resolved_keys = keys_path.resolve()

    def _cors(response: Response) -> Response:
        return add_cors_to_response(response, headers="Content-Type")

    def _json(data, status=200):
        return _cors(JSONResponse(data, status_code=status))

    def _check_token(request: Request) -> Response | None:
        token = request.query_params.get("token")
        if token != secret:
            return _json({"error": "Forbidden"}, 403)
        return None

    async def keys_json(request: Request):
        if resolved_keys.is_file():
            data = resolved_keys.read_bytes()
        else:
            data = b"{}"
        resp = Response(data, media_type="application/json")
        resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        return _cors(resp)

    async def exercises(request: Request):
        err = _check_token(request)
        if err:
            return err
        state = _get_exercises_state(keys_all, resolved_keys)
        return _json(state)

    async def release(request: Request):
        err = _check_token(request)
        if err:
            return err
        body = await request.body()
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            return _json({"error": "Invalid JSON"}, 400)
        exercise = data.get("exercise", "")
        released = data.get("released", True)
        if not exercise:
            return _json({"error": "Missing 'exercise' field"}, 400)
        state = _do_release(resolved_keys, keys_all, exercise, released)
        return _json(state)

    async def release_all(request: Request):
        err = _check_token(request)
        if err:
            return err
        body = await request.body()
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            return _json({"error": "Invalid JSON"}, 400)
        released = data.get("released", True)
        state = _do_release_all(resolved_keys, keys_all, released)
        return _json(state)

    async def dashboard(request: Request):
        # No auth — the HTML is static; API endpoints check the token
        dash_path = resolved_export / "dashboard.html"
        if dash_path.is_file():
            return _cors(FileResponse(dash_path))
        return _json({"error": "Dashboard not found"}, 404)

    routes = [
        Route("/keys.json", keys_json),
        Route("/workshop/exercises", exercises),
        Route("/workshop/release", release, methods=["POST"]),
        Route("/workshop/release-all", release_all, methods=["POST"]),
        Route("/dashboard.html", dashboard),
        Mount("/", app=StaticFiles(directory=str(resolved_export), html=True)),
    ]

    return Starlette(routes=routes)
