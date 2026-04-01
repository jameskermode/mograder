"""Hub HTTP and WebSocket reverse proxy to marimo sessions."""

from __future__ import annotations

import logging
import time

import httpx
from fastapi import APIRouter, Request, Response, WebSocket
from fastapi.responses import HTMLResponse, RedirectResponse

from mograder.core.edit_sessions import proxy_http_request, proxy_ws_relay

log = logging.getLogger("mograder.hub")

_proxy_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    global _proxy_client
    if _proxy_client is None or _proxy_client.is_closed:
        _proxy_client = httpx.AsyncClient(timeout=60)
    return _proxy_client


def create_proxy_router(session_manager) -> APIRouter:
    """Create FastAPI router for proxying to marimo edit sessions."""
    router = APIRouter()

    def _check_access(scope, username: str) -> bool:
        """Check if current user can access this username's session."""
        user = scope.get("user", {})
        if user.get("is_instructor"):
            return True
        return user.get("username") == username

    def _get_session(username: str, assignment: str):
        """Get active session or None."""
        key = (username, assignment)
        session = session_manager.sessions.get(key)
        if session is None:
            return None
        if session.process and session.process.returncode is not None:
            session_manager.sessions.pop(key, None)
            return None
        return session

    # Redirect /edit/user/assignment → /edit/user/assignment/
    @router.get("/edit/user/{username}/{assignment}")
    async def proxy_redirect(username: str, assignment: str):
        return RedirectResponse(f"/edit/user/{username}/{assignment}/")

    # Trailing-slash routes (Starlette {path:path} doesn't match empty string)
    @router.api_route(
        "/edit/user/{username}/{assignment}/",
        methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"],
    )
    async def proxy_http_root(request: Request, username: str, assignment: str):
        return await proxy_http(request, username, assignment, path="")

    @router.websocket("/edit/user/{username}/{assignment}/")
    async def proxy_ws_root(websocket: WebSocket, username: str, assignment: str):
        return await proxy_ws(websocket, username, assignment, path="")

    @router.api_route(
        "/edit/user/{username}/{assignment}/{path:path}",
        methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"],
    )
    async def proxy_http(request: Request, username: str, assignment: str, path: str):
        if not _check_access(request.scope, username):
            return Response("403 Forbidden", status_code=403)

        session = _get_session(username, assignment)
        if session is None:
            return Response("No active session", status_code=404)

        session.last_seen = time.time()

        target_path = request.url.path
        target_url = f"http://127.0.0.1:{session.port}{target_path}"
        if request.url.query:
            target_url += f"?{request.url.query}"

        try:
            return await proxy_http_request(_get_client(), request, target_url)
        except httpx.ConnectError:
            return Response("Session unavailable", status_code=502)

    @router.websocket("/edit/user/{username}/{assignment}/{path:path}")
    async def proxy_ws(websocket: WebSocket, username: str, assignment: str, path: str):
        user = websocket.scope.get("user", {})
        if not user.get("is_instructor") and user.get("username") != username:
            await websocket.close(code=1008)
            return

        session = _get_session(username, assignment)
        if session is None:
            await websocket.close(code=1008)
            return

        session.last_seen = time.time()

        target = f"ws://127.0.0.1:{session.port}{websocket.url.path}"
        if websocket.url.query:
            target += f"?{websocket.url.query}"

        await websocket.accept()
        await proxy_ws_relay(websocket, target)

    # -- Spinner page for deep links --

    def _spinner_html(title: str, start_url: str) -> HTMLResponse:
        """Return an HTML page with a spinner that starts a session via fetch.

        Uses the current page URL to derive the hub base path so that deep
        links work correctly behind a reverse proxy (e.g. ``/live/hub/``).
        The ``start_url`` should be a hub-root-relative path like
        ``/start-run/{lecture}``; it gets prefixed with the detected base.
        The response ``url`` field is also resolved relative to the base.
        """
        html = f"""\
<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>{title}</title></head>
<body style="font-family:-apple-system,BlinkMacSystemFont,sans-serif;
  display:flex;align-items:center;justify-content:center;height:100vh;
  flex-direction:column;margin:0;background:#fafafa">
<div class="spinner"></div>
<p id="msg" style="margin-top:1.5em;font-size:1.1em;color:#555">{title}</p>
<style>
.spinner{{width:48px;height:48px;border:4px solid #e0e0e0;
  border-top:4px solid #333;border-radius:50%;
  animation:spin 0.8s linear infinite}}
@keyframes spin{{to{{transform:rotate(360deg)}}}}
</style>
<script>
// Derive hub base path from current URL.
// e.g. /live/hub/run/L01/ → /live/hub, or /edit/A1/ → ""
var p = window.location.pathname;
var parts = ["/edit/", "/run/"];
var base = "";
for (var i = 0; i < parts.length; i++) {{
  var idx = p.indexOf(parts[i]);
  if (idx >= 0) {{ base = p.substring(0, idx); break; }}
}}
fetch(base + "{start_url}", {{method:"POST",credentials:"same-origin"}})
  .then(r=>r.ok?r.json():Promise.reject(r.statusText))
  .then(d=>{{window.location.href=base+d.url}})
  .catch(e=>{{
    document.getElementById("msg").textContent="Error: "+e;
    document.querySelector(".spinner").style.display="none";
  }});
</script>
</body></html>"""
        return HTMLResponse(html)

    # -- Assignment deep link: /edit/{assignment} --

    @router.get("/edit/{assignment}")
    async def edit_deep_link_no_slash(request: Request, assignment: str):
        return _spinner_html(
            f"Starting {assignment}...",
            f"/start-edit-deep/{assignment}",
        )

    @router.api_route("/edit/{assignment}/", methods=["GET"])
    async def edit_deep_link(request: Request, assignment: str):
        return _spinner_html(
            f"Starting {assignment}...",
            f"/start-edit-deep/{assignment}",
        )

    # -- Lecture deep link + per-user run proxy --
    # /run/{lecture}/ shows a spinner page that POSTs to /start-run/{lecture}
    # then redirects to /run/user/{username}/{lecture}/.

    @router.get("/run/{lecture}")
    async def run_lecture_deep_link_no_slash(request: Request, lecture: str):
        return _spinner_html(
            f"Starting {lecture}...",
            f"/start-run/{lecture}",
        )

    @router.api_route("/run/{lecture}/", methods=["GET"])
    async def run_lecture_deep_link(request: Request, lecture: str):
        return _spinner_html(
            f"Starting {lecture}...",
            f"/start-run/{lecture}",
        )

    @router.get("/run/user/{username}/{lecture}")
    async def run_redirect(username: str, lecture: str):
        return RedirectResponse(f"/run/user/{username}/{lecture}/")

    @router.api_route(
        "/run/user/{username}/{lecture}/",
        methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"],
    )
    async def run_proxy_http_root(request: Request, username: str, lecture: str):
        return await run_proxy_http(request, username, lecture, path="")

    @router.websocket("/run/user/{username}/{lecture}/")
    async def run_proxy_ws_root(websocket: WebSocket, username: str, lecture: str):
        return await run_proxy_ws(websocket, username, lecture, path="")

    @router.api_route(
        "/run/user/{username}/{lecture}/{path:path}",
        methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"],
    )
    async def run_proxy_http(request: Request, username: str, lecture: str, path: str):
        if not _check_access(request.scope, username):
            return Response("403 Forbidden", status_code=403)

        session = _get_session(username, lecture)
        if session is None:
            return Response("No active lecture session", status_code=404)

        session.last_seen = time.time()

        target_path = request.url.path
        target_url = f"http://127.0.0.1:{session.port}{target_path}"
        if request.url.query:
            target_url += f"?{request.url.query}"

        try:
            return await proxy_http_request(_get_client(), request, target_url)
        except httpx.ConnectError:
            return Response("Lecture session unavailable", status_code=502)

    @router.websocket("/run/user/{username}/{lecture}/{path:path}")
    async def run_proxy_ws(
        websocket: WebSocket, username: str, lecture: str, path: str
    ):
        user = websocket.scope.get("user", {})
        if not user.get("is_instructor") and user.get("username") != username:
            await websocket.close(code=1008)
            return

        session = _get_session(username, lecture)
        if session is None:
            await websocket.close(code=1008)
            return

        session.last_seen = time.time()

        target = f"ws://127.0.0.1:{session.port}{websocket.url.path}"
        if websocket.url.query:
            target += f"?{websocket.url.query}"

        await websocket.accept()
        await proxy_ws_relay(websocket, target)

    return router
