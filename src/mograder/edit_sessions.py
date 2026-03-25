"""Shared headless edit session utilities and ASGI reverse proxy.

Layer 1: spawn_headless_edit() — shared by student_app and formgrader
Layer 2: EditSessionManager — formgrader session lifecycle
Layer 3: build_edit_proxy_app() — Starlette ASGI proxy for HTTP + WebSocket
"""

from __future__ import annotations

import asyncio
import atexit
import os
import re
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from subprocess import PIPE, STDOUT
from urllib.parse import urlparse
from uuid import uuid4

# ---------------------------------------------------------------------------
# Layer 1: Shared headless spawn utility
# ---------------------------------------------------------------------------


@dataclass
class HeadlessSession:
    """Result of spawning ``marimo edit --headless``."""

    proc: subprocess.Popen
    url: str  # raw URL from marimo stdout (e.g. http://127.0.0.1:3456)
    port: int  # extracted port number


def spawn_headless_edit(
    path: str,
    *,
    sandbox: bool = True,
    base_url: str = "",
    host: str = "127.0.0.1",
    token: bool = True,
    timeout: float | None = None,
    spawn_timeout: float = 30,
    extra_env: dict[str, str] | None = None,
) -> HeadlessSession:
    """Spawn ``marimo edit --headless`` and wait for the served URL.

    Returns a :class:`HeadlessSession` with *proc*, *url*, and *port*.
    Raises :exc:`TimeoutError` if the URL is not found within *spawn_timeout*
    seconds.
    """
    cmd: list[str] = [sys.executable, "-m", "marimo", "edit"]
    if sandbox:
        cmd.append("--sandbox")
    cmd.extend(["--headless", "--host", host])
    if base_url:
        cmd.extend(["--base-url", base_url])
    if not token:
        cmd.append("--no-token")
    if timeout is not None:
        cmd.extend(["--timeout", str(timeout)])
    cmd.append(str(path))

    import logging

    log = logging.getLogger("uvicorn.error")
    log.info("spawn_headless_edit: %s", " ".join(cmd))
    env = None
    if extra_env:
        env = {**os.environ, **extra_env}
    proc = subprocess.Popen(
        cmd,
        stdout=PIPE,
        stderr=STDOUT,
        text=True,
        start_new_session=True,  # new process group so we can kill the tree
        env=env,
    )
    log.info("spawn_headless_edit: pid=%d", proc.pid)

    # Thread-based URL extraction (existing pattern from student_app.py)
    url_box: list[str] = []
    output_lines: list[str] = []
    found = threading.Event()

    def drain() -> None:
        assert proc.stdout is not None
        for line in proc.stdout:
            output_lines.append(line.rstrip())
            if not url_box:
                # Match marimo's "URL:" line specifically to avoid
                # capturing pip/uv download URLs from --sandbox
                m = re.search(r"URL:\s+(https?://\S+)", line)
                if m:
                    url_box.append(m.group(1))
                    found.set()

    threading.Thread(target=drain, daemon=True).start()
    found.wait(timeout=spawn_timeout)

    if not url_box:
        log.error(
            "spawn_headless_edit: timeout (poll=%s), output: %s",
            proc.poll(),
            output_lines,
        )
        proc.kill()
        raise TimeoutError(f"marimo edit did not produce URL within {spawn_timeout}s")

    raw_url = url_box[0]
    port = urlparse(raw_url).port or 0
    return HeadlessSession(proc=proc, url=raw_url, port=port)


def rewrite_codespaces_url(raw_url: str) -> str:
    """Rewrite a localhost URL to a Codespaces port-forwarded URL."""
    parsed = urlparse(raw_url)
    port = parsed.port
    if not port:
        return raw_url
    cs_name = os.environ["CODESPACE_NAME"]
    cs_domain = os.environ.get(
        "GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN", "app.github.dev"
    )
    url = f"https://{cs_name}-{port}.{cs_domain}"
    if parsed.query:
        url += f"?{parsed.query}"
    return url


def _kill_tree(pid: int) -> None:
    """Kill a process and all its descendants.

    Walks ``/proc`` to find children recursively, then sends SIGTERM to the
    whole tree (leaves first).  Falls back to SIGKILL after a short wait if
    any process survives.  Silently ignores processes that have already exited.
    """
    import signal

    def _children(parent_pid: int) -> list[int]:
        """Return direct child PIDs by reading /proc/*/stat."""
        kids: list[int] = []
        try:
            for entry in os.listdir("/proc"):
                if not entry.isdigit():
                    continue
                try:
                    with open(f"/proc/{entry}/stat") as f:
                        stat = f.read()
                    # Field 4 (0-indexed 3) is PPID.  The comm field (2) may
                    # contain spaces/parens, so split from the *last* ')'.
                    rparen = stat.rfind(")")
                    fields = stat[rparen + 2 :].split()
                    ppid = int(fields[1])  # field index 1 after comm = PPID
                    if ppid == parent_pid:
                        kids.append(int(entry))
                except (OSError, ValueError, IndexError):
                    continue
        except OSError:
            pass
        return kids

    def _descendants(root: int) -> list[int]:
        """Return all descendants depth-first (leaves first for clean kill)."""
        result: list[int] = []
        stack = [root]
        while stack:
            p = stack.pop()
            kids = _children(p)
            result.append(p)
            stack.extend(kids)
        # Reverse so leaves come first
        result.reverse()
        return result

    pids = _descendants(pid)
    # SIGTERM first
    for p in pids:
        try:
            os.kill(p, signal.SIGTERM)
        except ProcessLookupError:
            pass

    # Brief wait then SIGKILL stragglers
    time.sleep(0.3)
    for p in pids:
        try:
            os.kill(p, signal.SIGKILL)
        except ProcessLookupError:
            pass


# ---------------------------------------------------------------------------
# Layer 2: Session manager (formgrader-specific)
# ---------------------------------------------------------------------------


@dataclass
class EditSession:
    """A running headless edit session."""

    session_id: str
    path: str
    port: int
    proc: subprocess.Popen
    created_at: float = field(default_factory=time.time)
    last_activity: float = field(default_factory=time.time)


class EditSessionManager:
    """Manage headless marimo edit sessions for the formgrader.

    Sessions are keyed by notebook path — starting a session for an already-
    open notebook returns the existing session.  Stale/dead sessions are
    cleaned up on each ``start()`` call and via an ``atexit`` handler.
    """

    def __init__(self, base_url: str, idle_timeout: float = 1800):
        self.sessions: dict[str, EditSession] = {}
        self.base_url = base_url.rstrip("/")
        self.idle_timeout = idle_timeout
        atexit.register(self.shutdown)
        # Also handle SIGTERM (systemd sends this on service restart)
        import signal

        signal.signal(signal.SIGTERM, self._sigterm_handler)

    def _sigterm_handler(self, signum, frame):
        self.shutdown()
        raise SystemExit(0)

    # -- public API --

    def start(self, notebook_path: str) -> EditSession:
        """Start or return an existing edit session for *notebook_path*."""
        # Reuse existing session for the same path
        for s in self.sessions.values():
            if s.path == notebook_path and s.proc.poll() is None:
                s.last_activity = time.time()
                return s

        self.cleanup_stale()

        session_id = uuid4().hex[:12]
        edit_base_url = f"{self.base_url}/_edit/{session_id}"
        hs = spawn_headless_edit(
            notebook_path,
            base_url=edit_base_url,
            host="127.0.0.1",
            token=False,  # auth handled by TrustedProxyAuth
            timeout=30,  # auto-shutdown after 30 min idle
            spawn_timeout=120,  # --sandbox dep install can be slow
        )
        session = EditSession(
            session_id=session_id,
            path=notebook_path,
            port=hs.port,
            proc=hs.proc,
        )
        self.sessions[session_id] = session
        return session

    def get(self, session_id: str) -> EditSession | None:
        """Return the session for *session_id*, or ``None``."""
        session = self.sessions.get(session_id)
        if session and session.proc.poll() is not None:
            # Process died — remove it
            del self.sessions[session_id]
            return None
        return session

    def stop(self, session_id: str) -> bool:
        """Kill and remove a session. Returns ``True`` if it existed."""
        session = self.sessions.pop(session_id, None)
        if session is None:
            return False
        _kill_tree(session.proc.pid)
        try:
            session.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass
        return True

    def cleanup_stale(self) -> None:
        """Kill sessions whose process died or that have been idle too long."""
        now = time.time()
        dead = [
            sid
            for sid, s in self.sessions.items()
            if s.proc.poll() is not None or (now - s.last_activity) > self.idle_timeout
        ]
        for sid in dead:
            self.stop(sid)

    def shutdown(self) -> None:
        """Kill all sessions (called via ``atexit``)."""
        for sid in list(self.sessions):
            self.stop(sid)

    def list_sessions(self) -> list[dict]:
        """Return JSON-serialisable list of active sessions."""
        self.cleanup_stale()
        return [
            {
                "session_id": s.session_id,
                "path": s.path,
                "port": s.port,
                "created_at": s.created_at,
                "last_activity": s.last_activity,
                "url": f"{self.base_url}/_edit/{s.session_id}/",
            }
            for s in self.sessions.values()
        ]


# ---------------------------------------------------------------------------
# Layer 3: ASGI proxy app (Starlette)
# ---------------------------------------------------------------------------

# Matches content-hashed asset filenames (e.g. cells-CCtxWKxf.js)
_ASSET_PATH_RE = re.compile(r"/assets/[^/]+-[A-Za-z0-9_-]{6,}\.\w+$")

_LOADING_SCREEN = (
    b'<div id="root"><div style="display:flex;align-items:center;'
    b"justify-content:center;height:100vh;font-family:'PT Sans',"
    b'system-ui,sans-serif;color:#666;flex-direction:column;gap:16px">'
    b'<svg width="48" height="48" viewBox="0 0 24 24" fill="none" '
    b'stroke="currentColor" stroke-width="1.5" stroke-linecap="round">'
    b'<path d="M21 12a9 9 0 1 1-6.219-8.56">'
    b'<animateTransform attributeName="transform" type="rotate" '
    b'from="0 12 12" to="360 12 12" dur="1s" repeatCount="indefinite"/>'
    b"</path></svg>"
    b"<span>Loading notebook...</span></div></div>"
)


def _inject_loading_screen(content: bytes) -> bytes:
    """Replace empty ``<div id="root"></div>`` with a loading spinner.

    React's ``createRoot().render()`` replaces the inner content automatically,
    so no cleanup is needed.
    """
    return content.replace(b'<div id="root"></div>', _LOADING_SCREEN)


class MarimoOptimizeMiddleware:
    """ASGI middleware: cache headers for hashed assets + loading screen.

    Wraps any ASGI app to:
    1. Add ``Cache-Control: public, max-age=31536000, immutable`` to
       content-hashed asset responses (e.g. ``/assets/cells-CCtxWKxf.js``).
    2. Inject a loading spinner into HTML responses that contain an empty
       ``<div id="root"></div>``.

    Used by both the edit proxy and the formgrader marimo app.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        is_asset = bool(_ASSET_PATH_RE.search(path))
        is_html = False  # determined from response headers

        async def send_wrapper(message):
            nonlocal is_html
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                if is_asset:
                    # Remove any existing cache-control, add immutable
                    headers = [(k, v) for k, v in headers if k != b"cache-control"]
                    headers.append(
                        (
                            b"cache-control",
                            b"public, max-age=31536000, immutable",
                        )
                    )
                # Detect HTML for loading screen injection
                for k, v in headers:
                    if k == b"content-type" and b"text/html" in v:
                        is_html = True
                        # Remove content-length since body size will change
                        headers = [(k, v) for k, v in headers if k != b"content-length"]
                        break
                message = {**message, "headers": headers}
            elif message["type"] == "http.response.body" and is_html:
                body = message.get("body", b"")
                body = _inject_loading_screen(body)
                message = {**message, "body": body}
            await send(message)

        await self.app(scope, receive, send_wrapper)


_HOP_BY_HOP = frozenset(
    {
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailers",
        "transfer-encoding",
        "upgrade",
        "content-encoding",
        "content-length",
    }
)


def _filter_headers(headers) -> dict[str, str]:
    """Filter hop-by-hop headers from a request."""
    return {k: v for k, v in headers.items() if k.lower() not in _HOP_BY_HOP}


def _filter_response_headers(headers) -> dict[str, str]:
    """Filter hop-by-hop headers from an upstream response."""
    return {k: v for k, v in headers.items() if k.lower() not in _HOP_BY_HOP}


async def proxy_http_request(client, request, target_url: str):
    """Forward *request* to *target_url* via *client*, filtering hop-by-hop headers."""
    from starlette.responses import Response

    body = await request.body()
    resp = await client.request(
        method=request.method,
        url=target_url,
        headers=_filter_headers(request.headers),
        content=body,
        timeout=60,
    )
    return Response(
        content=resp.content,
        status_code=resp.status_code,
        headers=_filter_response_headers(resp.headers),
    )


async def proxy_ws_relay(websocket, target_url: str) -> None:
    """Relay WebSocket frames between *websocket* and upstream *target_url*.

    Caller must have already called ``await websocket.accept()``.
    """
    try:
        import websockets

        async with websockets.connect(target_url) as upstream:

            async def client_to_upstream() -> None:
                try:
                    while True:
                        data = await websocket.receive_text()
                        await upstream.send(data)
                except Exception:
                    pass

            async def upstream_to_client() -> None:
                try:
                    async for msg in upstream:
                        if isinstance(msg, str):
                            await websocket.send_text(msg)
                        else:
                            await websocket.send_bytes(msg)
                except Exception:
                    pass

            await asyncio.gather(client_to_upstream(), upstream_to_client())
    except Exception:
        pass
    finally:
        try:
            await websocket.close()
        except Exception:
            pass


def build_edit_proxy_app(
    manager: EditSessionManager,
    http_client: object | None = None,
):
    """Build a Starlette ASGI app that proxies edit sessions and exposes a REST API.

    Parameters
    ----------
    manager : EditSessionManager
        Session lifecycle manager.
    http_client : httpx.AsyncClient, optional
        Injected HTTP client (for testing).  When *None* a persistent client
        is created and closed automatically via the Starlette lifespan.

    Routes:
    - ``/_edit/{session_id}/{path:path}`` — HTTP proxy to marimo edit
    - ``/_edit/{session_id}/{path:path}`` — WebSocket proxy to marimo edit
    - ``/_api/edit`` — POST to create, GET to list, DELETE to stop
    """
    import httpx
    from contextlib import asynccontextmanager

    from starlette.applications import Starlette
    from starlette.requests import Request
    from starlette.responses import JSONResponse, Response
    from starlette.routing import Route, WebSocketRoute
    from starlette.websockets import WebSocket

    _proxy_client = http_client or httpx.AsyncClient(timeout=60)
    _owns_client = http_client is None

    @asynccontextmanager
    async def lifespan(app):
        yield
        if _owns_client:
            await _proxy_client.aclose()

    async def proxy_http(request: Request) -> Response:
        user = request.scope.get("user", {})
        if not user.get("is_instructor"):
            return Response("403 Forbidden", status_code=403)
        session_id = request.path_params["session_id"]
        session = manager.get(session_id)
        if not session:
            return Response("Not found", status_code=404)
        session.last_activity = time.time()

        # Keep full path — marimo expects it via --base-url
        target_path = request.url.path
        target_url = f"http://127.0.0.1:{session.port}{target_path}"
        if request.url.query:
            target_url += f"?{request.url.query}"

        return await proxy_http_request(_proxy_client, request, target_url)

    async def proxy_ws(websocket: WebSocket) -> None:
        user = websocket.scope.get("user", {})
        if not user.get("is_instructor"):
            await websocket.close(code=1008)
            return
        session_id = websocket.path_params["session_id"]
        session = manager.get(session_id)
        if not session:
            await websocket.close(code=1008)
            return
        session.last_activity = time.time()

        target = f"ws://127.0.0.1:{session.port}{websocket.url.path}"
        if websocket.url.query:
            target += f"?{websocket.url.query}"

        await websocket.accept()
        await proxy_ws_relay(websocket, target)

    async def create_session(request: Request) -> JSONResponse:
        user = request.scope.get("user", {})
        if not user.get("is_instructor"):
            return JSONResponse({"error": "Forbidden"}, status_code=403)
        data = await request.json()
        path = data.get("path")
        if not path:
            return JSONResponse({"error": "Missing 'path'"}, status_code=400)
        try:
            # Run in thread pool — start() blocks waiting for marimo URL
            session = await asyncio.to_thread(manager.start, path)
        except TimeoutError as exc:
            return JSONResponse({"error": str(exc)}, status_code=504)
        return JSONResponse(
            {
                "session_id": session.session_id,
                "url": f"{manager.base_url}/_edit/{session.session_id}/",
            }
        )

    async def list_sessions_endpoint(request: Request) -> JSONResponse:
        return JSONResponse(manager.list_sessions())

    async def delete_session(request: Request) -> JSONResponse:
        user = request.scope.get("user", {})
        if not user.get("is_instructor"):
            return JSONResponse({"error": "Forbidden"}, status_code=403)
        data = await request.json()
        session_id = data.get("session_id")
        if not session_id:
            return JSONResponse({"error": "Missing 'session_id'"}, status_code=400)
        removed = await asyncio.to_thread(manager.stop, session_id)
        return JSONResponse({"removed": removed})

    async def api_edit(request: Request) -> JSONResponse:
        if request.method == "POST":
            return await create_session(request)
        elif request.method == "DELETE":
            return await delete_session(request)
        else:
            return await list_sessions_endpoint(request)

    base = manager.base_url

    starlette_app = Starlette(
        routes=[
            Route(
                base + "/_api/edit",
                api_edit,
                methods=["GET", "POST", "DELETE"],
            ),
            WebSocketRoute(
                base + "/_edit/{session_id}/{path:path}",
                proxy_ws,
            ),
            Route(
                base + "/_edit/{session_id}/{path:path}",
                proxy_http,
                methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"],
            ),
        ],
        lifespan=lifespan,
    )
    return MarimoOptimizeMiddleware(starlette_app)
