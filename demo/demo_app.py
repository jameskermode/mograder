"""Combined ASGI app serving formgrader UI and assignment API.

Environment variables:
    MOGRADER_COURSE_DIR       — course directory for formgrader (default: ".")
    MOGRADER_ENROLLMENT_CODE  — enrollment passphrase for student self-registration
"""

from __future__ import annotations

import os
from pathlib import Path

import marimo

# Formgrader marimo app
formgrader_path = str(
    Path(__file__).parent / ".." / "src" / "mograder" / "formgrader_app.py"
)
server = marimo.create_asgi_app(include_code=True)
server = server.with_app(path="/", root=formgrader_path)

# Check if we should also serve the assignment API
course_dir = Path(os.environ.get("MOGRADER_COURSE_DIR", "."))

if (course_dir / "release").is_dir():
    from mograder.auth import is_instructor, load_or_create_secret, verify_token
    from mograder.https_server import create_starlette_routes

    _secret = load_or_create_secret(course_dir)
    _enrollment_code = os.environ.get("MOGRADER_ENROLLMENT_CODE") or None
    api_app = create_starlette_routes(
        course_dir,
        release_dir=course_dir / "release",
        submitted_dir=course_dir / "submitted",
        grades_dir=course_dir / ".mograder" / "server",
        secret=_secret,
        enrollment_code=_enrollment_code,
    )
    marimo_app = server.build()

    # --- Instructor auth via cookie session ---

    from starlette.middleware.sessions import SessionMiddleware
    from starlette.requests import Request
    from starlette.responses import HTMLResponse, RedirectResponse
    from starlette.routing import Route
    from starlette.types import ASGIApp, Receive, Scope, Send

    _LOGIN_HTML = """\
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Formgrader Login</title>
  <style>
    body {{ font-family: system-ui, sans-serif; display: flex;
           justify-content: center; align-items: center; min-height: 100vh;
           margin: 0; background: #f5f5f5; }}
    .card {{ background: white; padding: 2rem; border-radius: 8px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1); max-width: 400px;
            width: 100%; }}
    h1 {{ margin-top: 0; font-size: 1.5rem; }}
    input[type=text] {{ width: 100%; padding: 0.5rem; margin: 0.5rem 0 1rem;
                        box-sizing: border-box; font-size: 1rem; }}
    button {{ padding: 0.5rem 1.5rem; font-size: 1rem; cursor: pointer; }}
    .error {{ color: #c00; margin-bottom: 1rem; }}
  </style>
</head>
<body>
  <div class="card">
    <h1>Formgrader Login</h1>
    {error}
    <form method="post" action="/login">
      <label for="token">Instructor token:</label>
      <input type="text" id="token" name="token" required
             placeholder="__instructor__:abc123..." autocomplete="off">
      <label style="display:block; margin-bottom:1rem">
        <input type="checkbox" name="remember" value="1"> Remember me
      </label>
      <button type="submit">Log in</button>
    </form>
  </div>
</body>
</html>"""

    async def _login_get(request: Request) -> HTMLResponse:
        return HTMLResponse(_LOGIN_HTML.format(error=""))

    async def _login_post(request: Request) -> RedirectResponse | HTMLResponse:
        form = await request.form()
        token = form.get("token", "").strip()
        username = verify_token(_secret, token)
        if username and is_instructor(username):
            request.session["authenticated"] = True
            request.session["remember"] = bool(form.get("remember"))
            return RedirectResponse("/", status_code=303)
        error_msg = '<p class="error">Invalid token or not an instructor.</p>'
        return HTMLResponse(_LOGIN_HTML.format(error=error_msg), status_code=403)

    async def _logout(request: Request) -> RedirectResponse:
        request.session.clear()
        return RedirectResponse("/login", status_code=303)

    # Starlette sub-app for login/logout (no extra middleware — session
    # is provided by the outer SessionMiddleware wrapping the whole app).
    from starlette.applications import Starlette

    _auth_routes = Starlette(
        routes=[
            Route("/login", _login_get, methods=["GET"]),
            Route("/login", _login_post, methods=["POST"]),
            Route("/logout", _logout),
        ],
    )

    class _InstructorAuthMiddleware:
        """Require authenticated session for formgrader routes."""

        def __init__(self, app: ASGIApp) -> None:
            self.app = app

        async def __call__(self, scope: Scope, receive: Receive, send: Send):
            if scope["type"] != "http":
                await self.app(scope, receive, send)
                return

            path = scope.get("path", "")
            # Skip auth for API routes and login/logout
            if (
                path.startswith("/assignments")
                or path == "/register"
                or path in ("/login", "/logout")
            ):
                await self.app(scope, receive, send)
                return

            # Check session (populated by SessionMiddleware)
            if scope.get("session", {}).get("authenticated"):
                await self.app(scope, receive, send)
                return

            # Not authenticated — redirect to login
            response = RedirectResponse("/login", status_code=303)
            await response(scope, receive, send)

    async def _router(scope: Scope, receive: Receive, send: Send):
        """Route requests to API, auth, or formgrader."""
        path = scope.get("path", "")
        if scope["type"] in ("http", "websocket"):
            if path.startswith("/assignments") or path == "/register":
                await api_app(scope, receive, send)
                return
            if path in ("/login", "/logout"):
                await _auth_routes(scope, receive, send)
                return
        await marimo_app(scope, receive, send)

    _PERSISTENT_MAX_AGE = 90 * 24 * 60 * 60  # 90 days

    class _RememberMeMiddleware:
        """Strip Max-Age from session cookie when 'remember' is not set.

        When remember is set, SessionMiddleware's max_age applies (90 days).
        When not set, omitting Max-Age makes it a session cookie (expires
        when browser closes).
        """

        def __init__(self, app: ASGIApp) -> None:
            self.app = app

        async def __call__(self, scope: Scope, receive: Receive, send: Send):
            if scope["type"] != "http":
                await self.app(scope, receive, send)
                return

            remember = False

            async def send_wrapper(message):
                nonlocal remember
                if message["type"] == "http.response.start":
                    session = scope.get("session", {})
                    remember = session.get("remember", False)
                    if not remember:
                        headers = list(message.get("headers", []))
                        new_headers = []
                        for k, v in headers:
                            if k == b"set-cookie" and b"session=" in v:
                                # Remove Max-Age and Expires to make session-only
                                import re

                                v = re.sub(rb"; Max-Age=\d+", b"", v)
                                v = re.sub(rb"; expires=[^;]+", b"", v, flags=re.I)
                            new_headers.append((k, v))
                        message = {**message, "headers": new_headers}
                await send(message)

            await self.app(scope, receive, send_wrapper)

    # Stack: RememberMe → SessionMiddleware → AuthMiddleware → router
    # RememberMe must wrap SessionMiddleware so it can intercept the
    # Set-Cookie header that SessionMiddleware adds.
    _session_app = SessionMiddleware(
        _InstructorAuthMiddleware(_router),
        secret_key=_secret,
        max_age=_PERSISTENT_MAX_AGE,
    )
    app = _RememberMeMiddleware(_session_app)

else:
    app = server.build()
