"""ASGI grader with trusted-proxy authentication middleware.

Security model:
- localhost (127.0.0.1 / ::1) without an X-Remote-User header → instructor
  (local use, and the grader's own internal calls)
- Trusted proxy IPs → identity from the X-Remote-User header; with
  MOGRADER_TRUST_LOCAL_PROXY=1, localhost requests carrying the header too
  (a reverse proxy reaching the grader through an SSH tunnel)
- All other IPs → 403 Forbidden

Roles of a proxied user:
- in MOGRADER_INSTRUCTORS → instructor (everything)
- in MOGRADER_MARKERS → marker: the Submissions and Grading tabs only, for
  assignments the instructor has opened for marking; no Moodle actions
- anyone else → 403 when MOGRADER_MARKERS is set; otherwise a marker
- with neither list set, every proxied user is an instructor (as before
  roles existed)

Environment variables:
    MOGRADER_COURSE_DIR        Course directory (required)
    MOGRADER_BASE_URL          Base URL path, default "/" (e.g. "/live/grader")
    MOGRADER_INSTRUCTORS       Comma-separated instructor user IDs
    MOGRADER_MARKERS           Comma-separated marker (GTA) user IDs
    MOGRADER_TRUSTED_PROXIES   Comma-separated trusted proxy IPs
    MOGRADER_TRUST_LOCAL_PROXY 1 = localhost requests with X-Remote-User are proxied

Usage:
    uvicorn mograder.grader.asgi:app --host 0.0.0.0 --port 2718
"""

import os
from pathlib import Path

import marimo

from mograder.core import view_as
from mograder.core.config import load_config
from mograder.student.api import create_student_api

LOCALHOST_IPS = {"127.0.0.1", "::1"}

TRUSTED_PROXIES = {
    ip.strip()
    for ip in os.environ.get("MOGRADER_TRUSTED_PROXIES", "").split(",")
    if ip.strip()
}


def _user_set(var: str) -> set[str]:
    return {u.strip() for u in os.environ.get(var, "").split(",") if u.strip()}


INSTRUCTOR_USERS = _user_set("MOGRADER_INSTRUCTORS")
MARKER_USERS = _user_set("MOGRADER_MARKERS")
TRUST_LOCAL_PROXY = os.environ.get("MOGRADER_TRUST_LOCAL_PROXY") == "1"


def resolve_user(
    client_ip: str | None,
    remote_user: str | None,
    *,
    instructors: set[str],
    markers: set[str],
    trusted_proxies: set[str],
    trust_local_proxy: bool = False,
) -> dict | None:
    """The request's user (``username``, ``is_instructor``, ``is_marker``), or
    ``None`` to refuse it. See the module docstring for the rules."""
    local = client_ip in LOCALHOST_IPS
    if local and not (trust_local_proxy and remote_user):
        return {"username": "", "is_instructor": True, "is_marker": False}
    if not (local or client_ip in trusted_proxies):
        return None
    if not remote_user:
        return None
    if not instructors and not markers:
        return {"username": remote_user, "is_instructor": True, "is_marker": False}
    if remote_user in instructors:
        return {"username": remote_user, "is_instructor": True, "is_marker": False}
    if markers and remote_user not in markers:
        return None
    return {"username": remote_user, "is_instructor": False, "is_marker": True}


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

        user = resolve_user(
            _get_client_ip(scope),
            _get_header(scope, "x-remote-user"),
            instructors=INSTRUCTOR_USERS,
            markers=MARKER_USERS,
            trusted_proxies=TRUSTED_PROXIES,
            trust_local_proxy=TRUST_LOCAL_PROXY,
        )
        if user is not None:
            # an instructor viewing as a marker (testing): their permissions
            # drop to a marker's for every request until they switch back
            scope["user"] = view_as.apply(
                user, view_as.read_cookie(scope.get("headers", [])), {"marker"}
            )
        else:
            # Untrusted source or user without a role → reject
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


async def _forbidden(scope, send):
    if scope["type"] == "http":
        await send(
            {
                "type": "http.response.start",
                "status": 403,
                "headers": [(b"content-type", b"text/plain")],
            }
        )
        await send({"type": "http.response.body", "body": b"403 Forbidden"})


class InstructorOnly:
    """Wrap an ASGI app (behind TrustedProxyAuth) so only instructors reach it."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] in ("http", "websocket") and not scope.get("user", {}).get(
            "is_instructor"
        ):
            await _forbidden(scope, send)
            return
        await self.app(scope, receive, send)


async def _view_as_endpoint(scope, receive, send):
    """``<base>/_view_as?role=marker`` switches to the marker view;
    ``?role=`` switches back. Real instructors only."""
    if scope["type"] != "http":
        return
    if not scope.get("user", {}).get("real_is_instructor"):
        await _forbidden(scope, send)
        return
    from urllib.parse import parse_qs

    qs = parse_qs(scope.get("query_string", b"").decode("latin-1"))
    role = (qs.get("role") or [""])[0]
    role = role if role == "marker" else ""
    await send(
        {
            "type": "http.response.start",
            "status": 303,
            "headers": [
                (b"location", b"./"),
                (b"set-cookie", view_as.cookie_header(role)),
                (b"cache-control", b"no-store"),
            ],
        }
    )
    await send({"type": "http.response.body", "body": b""})


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
# Creating/stopping edit sessions (on any path) is for the grader's own
# internal calls (localhost, instructor) and instructors; a marker's editors
# are started by the app, which checks what they may open.
_instructor_edit_api = TrustedProxyAuth(InstructorOnly(_edit_app))

_edit_prefix = _base_url.rstrip("/") + "/_edit/"
_api_prefix = _base_url.rstrip("/") + "/_api/edit"

# --- Student API (read-only, no auth) ---

_course_dir = Path(os.environ.get("MOGRADER_COURSE_DIR", "."))
_student_config = load_config(_course_dir)
_student_api = create_student_api(_course_dir, _student_config)
_student_api_prefix = _base_url.rstrip("/") + "/student/api"
_view_as_path = _base_url.rstrip("/") + "/_view_as"
_authed_view_as = TrustedProxyAuth(_view_as_endpoint)


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
        if path == _view_as_path:
            await _authed_view_as(scope, receive, send)
            return
        if path.startswith(_api_prefix):
            await _instructor_edit_api(scope, receive, send)
            return
        if path.startswith(_edit_prefix):
            await _authed_edit_app(scope, receive, send)
            return
    await _marimo_app(scope, receive, send)
