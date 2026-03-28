"""Hub HTTP and WebSocket reverse proxy to marimo sessions."""

from __future__ import annotations

import logging
import time

import httpx
from fastapi import APIRouter, Request, Response, WebSocket
from fastapi.responses import RedirectResponse

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
    @router.get("/edit/{username}/{assignment}")
    async def proxy_redirect(username: str, assignment: str):
        return RedirectResponse(f"/edit/{username}/{assignment}/")

    # Trailing-slash routes (Starlette {path:path} doesn't match empty string)
    @router.api_route(
        "/edit/{username}/{assignment}/",
        methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"],
    )
    async def proxy_http_root(request: Request, username: str, assignment: str):
        return await proxy_http(request, username, assignment, path="")

    @router.websocket("/edit/{username}/{assignment}/")
    async def proxy_ws_root(websocket: WebSocket, username: str, assignment: str):
        return await proxy_ws(websocket, username, assignment, path="")

    @router.api_route(
        "/edit/{username}/{assignment}/{path:path}",
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

    @router.websocket("/edit/{username}/{assignment}/{path:path}")
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

    return router
