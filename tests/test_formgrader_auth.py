"""Tests for formgrader instructor cookie authentication in demo_app.py."""

from __future__ import annotations

import re

import pytest
from starlette.middleware.sessions import SessionMiddleware
from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse
from starlette.routing import Route
from starlette.testclient import TestClient
from starlette.types import ASGIApp, Receive, Scope, Send

from mograder.auth import (
    INSTRUCTOR_USER,
    generate_secret,
    is_instructor,
    make_token,
    verify_token,
)


def _build_app(secret: str):
    """Build a minimal version of the demo_app auth stack for testing.

    Instead of a real marimo app, uses a stub that returns 200.
    Instead of a real API app, uses a stub that returns 200 with JSON.
    """

    _LOGIN_HTML = """\
<!DOCTYPE html>
<html><body>
<form method="post" action="/login">
  <input type="text" name="token">
  <button type="submit">Log in</button>
</form>
{error}
</body></html>"""

    async def login_get(request: Request) -> HTMLResponse:
        return HTMLResponse(_LOGIN_HTML.format(error=""))

    async def login_post(request: Request) -> RedirectResponse | HTMLResponse:
        form = await request.form()
        token = form.get("token", "").strip()
        username = verify_token(secret, token)
        if username and is_instructor(username):
            request.session["authenticated"] = True
            request.session["remember"] = bool(form.get("remember"))
            return RedirectResponse("/", status_code=303)
        return HTMLResponse(_LOGIN_HTML.format(error="Invalid"), status_code=403)

    async def logout(request: Request) -> RedirectResponse:
        request.session.clear()
        return RedirectResponse("/login", status_code=303)

    from starlette.applications import Starlette

    auth_routes = Starlette(
        routes=[
            Route("/login", login_get, methods=["GET"]),
            Route("/login", login_post, methods=["POST"]),
            Route("/logout", logout),
        ],
    )

    # Stub marimo app
    async def marimo_stub(scope: Scope, receive: Receive, send: Send):
        response = HTMLResponse("<h1>Formgrader</h1>")
        await response(scope, receive, send)

    # Stub API app
    from starlette.responses import JSONResponse

    async def api_stub(scope: Scope, receive: Receive, send: Send):
        response = JSONResponse({"ok": True})
        await response(scope, receive, send)

    class InstructorAuthMiddleware:
        def __init__(self, app: ASGIApp) -> None:
            self.app = app

        async def __call__(self, scope: Scope, receive: Receive, send: Send):
            if scope["type"] != "http":
                await self.app(scope, receive, send)
                return

            path = scope.get("path", "")
            if (
                path.startswith("/assignments")
                or path == "/register"
                or path in ("/login", "/logout")
            ):
                await self.app(scope, receive, send)
                return

            if scope.get("session", {}).get("authenticated"):
                await self.app(scope, receive, send)
                return

            response = RedirectResponse("/login", status_code=303)
            await response(scope, receive, send)

    async def router(scope: Scope, receive: Receive, send: Send):
        path = scope.get("path", "")
        if scope["type"] in ("http", "websocket"):
            if path.startswith("/assignments") or path == "/register":
                await api_stub(scope, receive, send)
                return
            if path in ("/login", "/logout"):
                await auth_routes(scope, receive, send)
                return
        await marimo_stub(scope, receive, send)

    _PERSISTENT_MAX_AGE = 90 * 24 * 60 * 60

    class RememberMeMiddleware:
        def __init__(self, app: ASGIApp) -> None:
            self.app = app

        async def __call__(self, scope: Scope, receive: Receive, send: Send):
            if scope["type"] != "http":
                await self.app(scope, receive, send)
                return

            async def send_wrapper(message):
                if message["type"] == "http.response.start":
                    session = scope.get("session", {})
                    remember = session.get("remember", False)
                    if not remember:
                        headers = list(message.get("headers", []))
                        new_headers = []
                        for k, v in headers:
                            if k == b"set-cookie" and b"session=" in v:
                                v = re.sub(rb"; Max-Age=\d+", b"", v)
                                v = re.sub(rb"; expires=[^;]+", b"", v, flags=re.I)
                            new_headers.append((k, v))
                        message = {**message, "headers": new_headers}
                await send(message)

            await self.app(scope, receive, send_wrapper)

    session_app = SessionMiddleware(
        InstructorAuthMiddleware(router),
        secret_key=secret,
        max_age=_PERSISTENT_MAX_AGE,
    )
    return RememberMeMiddleware(session_app)


@pytest.fixture()
def secret():
    return generate_secret()


@pytest.fixture()
def client(secret):
    app = _build_app(secret)
    return TestClient(app, follow_redirects=False)


class TestFormgraderAuth:
    def test_unauthenticated_redirects_to_login(self, client):
        resp = client.get("/")
        assert resp.status_code == 303
        assert resp.headers["location"] == "/login"

    def test_login_page_returns_form(self, client):
        resp = client.get("/login")
        assert resp.status_code == 200
        assert "<form" in resp.text
        assert 'name="token"' in resp.text

    def test_login_with_valid_instructor_token(self, client, secret):
        token = make_token(secret, INSTRUCTOR_USER)
        resp = client.post("/login", data={"token": token})
        assert resp.status_code == 303
        assert resp.headers["location"] == "/"

        # Follow-up request with the session cookie should succeed
        resp2 = client.get("/")
        assert resp2.status_code == 200
        assert "Formgrader" in resp2.text

    def test_login_with_student_token_rejected(self, client, secret):
        token = make_token(secret, "student1")
        resp = client.post("/login", data={"token": token})
        assert resp.status_code == 403
        assert "Invalid" in resp.text

    def test_login_with_invalid_token_rejected(self, client):
        resp = client.post("/login", data={"token": "garbage"})
        assert resp.status_code == 403

    def test_login_with_empty_token_rejected(self, client):
        resp = client.post("/login", data={"token": ""})
        assert resp.status_code == 403

    def test_api_routes_bypass_auth(self, client):
        """API routes should work without session cookie (Bearer auth only)."""
        resp = client.get("/assignments")
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}

    def test_register_bypasses_auth(self, client):
        resp = client.get("/register")
        assert resp.status_code == 200

    def test_logout_clears_session(self, client, secret):
        # Log in first
        token = make_token(secret, INSTRUCTOR_USER)
        client.post("/login", data={"token": token})

        # Verify authenticated
        resp = client.get("/")
        assert resp.status_code == 200

        # Logout
        resp = client.get("/logout")
        assert resp.status_code == 303
        assert resp.headers["location"] == "/login"

        # Should be redirected again
        resp = client.get("/")
        assert resp.status_code == 303
        assert resp.headers["location"] == "/login"

    def test_subpaths_also_protected(self, client):
        """Formgrader sub-paths (CSS, JS, etc.) should also require auth."""
        resp = client.get("/some/deep/path")
        assert resp.status_code == 303
        assert resp.headers["location"] == "/login"

    def test_login_without_remember_sets_session_cookie(self, client, secret):
        """Without 'remember', cookie should have no Max-Age (session-only)."""
        token = make_token(secret, INSTRUCTOR_USER)
        resp = client.post("/login", data={"token": token})
        cookie_header = resp.headers.get("set-cookie", "")
        assert "session=" in cookie_header
        assert "Max-Age" not in cookie_header

    def test_login_with_remember_sets_persistent_cookie(self, client, secret):
        """With 'remember' checked, cookie should have Max-Age."""
        token = make_token(secret, INSTRUCTOR_USER)
        resp = client.post("/login", data={"token": token, "remember": "1"})
        cookie_header = resp.headers.get("set-cookie", "")
        assert "session=" in cookie_header
        assert "Max-Age" in cookie_header
