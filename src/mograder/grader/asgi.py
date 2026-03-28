"""ASGI grader with trusted-proxy authentication middleware.

Security model:
- localhost (127.0.0.1 / ::1) → instructor (full access)
- Trusted proxy IPs → read X-Remote-User header for identity
- All other IPs → 403 Forbidden

Environment variables:
    MOGRADER_COURSE_DIR      Course directory (required)
    MOGRADER_BASE_URL        Base URL path, default "/" (e.g. "/live/grader")
    MOGRADER_INSTRUCTORS     Comma-separated instructor user IDs
    MOGRADER_TRUSTED_PROXIES Comma-separated trusted proxy IPs

Usage:
    uvicorn mograder.grader.asgi:app --host 0.0.0.0 --port 2718
"""

import os
from pathlib import Path

import marimo

from mograder.core.config import load_config
from mograder.student.api import create_student_api

LOCALHOST_IPS = {"127.0.0.1", "::1"}

TRUSTED_PROXIES = {
    ip.strip()
    for ip in os.environ.get("MOGRADER_TRUSTED_PROXIES", "").split(",")
    if ip.strip()
}

INSTRUCTOR_USERS = {
    u.strip()
    for u in os.environ.get("MOGRADER_INSTRUCTORS", "").split(",")
    if u.strip()
}


def _get_client_ip(scope):
    client = scope.get("client")
    return client[0] if client else None


def _get_header(scope, name):
    name_lower = name.lower().encode("latin-1")
    for key, value in scope.get("headers", []):
        if key == name_lower:
            return value.decode("latin-1")
    return None


class TrustedProxyAuth:
    """ASGI middleware enforcing trusted-proxy authentication.

    Callabe as a middleware factory: ``TrustedProxyAuth(app)`` wraps *app*.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        client_ip = _get_client_ip(scope)

        if client_ip in LOCALHOST_IPS:
            # Local access → instructor
            scope["user"] = {"username": "", "is_instructor": True}
        elif client_ip in TRUSTED_PROXIES:
            # Reverse proxy → trust X-Remote-User
            username = _get_header(scope, "x-remote-user") or ""
            scope["user"] = {
                "username": username,
                "is_instructor": username in INSTRUCTOR_USERS,
            }
        else:
            # Untrusted source → reject
            if scope["type"] == "http":
                await send(
                    {
                        "type": "http.response.start",
                        "status": 403,
                        "headers": [(b"content-type", b"text/plain")],
                    }
                )
                await send(
                    {
                        "type": "http.response.body",
                        "body": b"403 Forbidden",
                    }
                )
            return

        await self.app(scope, receive, send)


# --- Build the ASGI application ---

_base_url = os.environ.get("MOGRADER_BASE_URL", "/")
_app_path = str(Path(__file__).parent / "app.py")

from mograder.core.edit_sessions import (  # noqa: E402
    EditSessionManager,
    MarimoOptimizeMiddleware,
    build_edit_proxy_app,
)

from mograder._brand import FAVICON_LINK  # noqa: E402

_builder = marimo.create_asgi_app(quiet=True, html_head=FAVICON_LINK)
_builder = _builder.with_app(
    path=_base_url,
    root=_app_path,
    middleware=[TrustedProxyAuth, MarimoOptimizeMiddleware],
)
_marimo_app = _builder.build()

# --- Edit session proxy (headless marimo edit via reverse proxy) ---

_edit_manager = EditSessionManager(base_url=_base_url.rstrip("/"))
_edit_app = build_edit_proxy_app(_edit_manager)
_authed_edit_app = TrustedProxyAuth(_edit_app)

_edit_prefix = _base_url.rstrip("/") + "/_edit/"
_api_prefix = _base_url.rstrip("/") + "/_api/edit"

# --- Student API (read-only, no auth) ---

_course_dir = Path(os.environ.get("MOGRADER_COURSE_DIR", "."))
_student_config = load_config(_course_dir)
_student_api = create_student_api(_course_dir, _student_config)
_student_api_prefix = _base_url.rstrip("/") + "/student/api"


async def app(scope, receive, send):
    """Route requests to student API, edit proxy, or marimo grader."""
    if scope["type"] in ("http", "websocket"):
        path = scope.get("path", "")
        # Student API — no auth, before grader catch-all
        if path.startswith(_student_api_prefix):
            scope = dict(scope)
            scope["path"] = path[len(_student_api_prefix) :] or "/"
            await _student_api(scope, receive, send)
            return
        if path.startswith(_edit_prefix) or path.startswith(_api_prefix):
            await _authed_edit_app(scope, receive, send)
            return
    await _marimo_app(scope, receive, send)
