"""Hub authentication — session cookies, ASGI middleware, FastAPI deps."""

from __future__ import annotations

import base64
import hashlib
import hmac
import http.cookies
import time
from pathlib import Path

from mograder.core.auth import is_instructor, verify_token


COOKIE_NAME = "mograder_session"


# -- session cookie helpers --


def make_session_cookie(
    secret: str,
    username: str,
    *,
    timestamp: float | None = None,
) -> str:
    """Create a session cookie value: ``base64(username:timestamp:hmac)``."""
    ts = str(int(timestamp if timestamp is not None else time.time()))
    payload = f"{username}:{ts}"
    mac = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    raw = f"{username}:{ts}:{mac}"
    return base64.urlsafe_b64encode(raw.encode()).decode()


def verify_session_cookie(
    secret: str,
    cookie: str,
    *,
    max_age: int = 86400,
) -> str | None:
    """Verify a session cookie, returning the username or None."""
    try:
        raw = base64.urlsafe_b64decode(cookie.encode()).decode()
    except Exception:
        return None
    parts = raw.split(":")
    if len(parts) != 3:
        return None
    username, ts_str, mac_hex = parts
    try:
        ts = int(ts_str)
    except ValueError:
        return None
    if time.time() - ts > max_age:
        return None
    expected_payload = f"{username}:{ts_str}"
    expected = hmac.new(
        secret.encode(), expected_payload.encode(), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(mac_hex, expected):
        return None
    return username


# -- ASGI helpers --


def _get_header(scope: dict, name: str) -> str | None:
    """Read a single header value from ASGI scope (case-insensitive)."""
    target = name.lower().encode("latin-1")
    for key, value in scope.get("headers", []):
        if key == target:
            return value.decode("latin-1")
    return None


def _parse_cookie(scope: dict, cookie_name: str) -> str | None:
    """Extract a specific cookie from the Cookie header."""
    raw = _get_header(scope, "cookie")
    if not raw:
        return None
    c = http.cookies.SimpleCookie()
    try:
        c.load(raw)
    except http.cookies.CookieError:
        return None
    morsel = c.get(cookie_name)
    return morsel.value if morsel else None


ALLOWED_USERS_FILE = "allowed_users.txt"

_NOT_ENROLLED_HTML = b"""<!DOCTYPE html>
<html>
<head>
    <title>Access Restricted</title>
    <style>
        body { font-family: system-ui, sans-serif; max-width: 600px; margin: 80px auto; padding: 20px; text-align: center; }
        h1 { color: #c0392b; }
        .message { background: #fdecea; border: 1px solid #e74c3c; border-radius: 8px; padding: 1.5em; margin: 2em 0; }
    </style>
</head>
<body>
    <h1>Access Restricted</h1>
    <div class="message">
        <p>You are not enrolled on this course.</p>
        <p>If you believe this is an error, please contact your instructor.</p>
    </div>
</body>
</html>"""


def load_allowed_users(path: Path) -> set[str] | None:
    """Load allowed usernames from file. Returns None if file doesn't exist."""
    if not path.is_file():
        return None
    return {
        line.strip()
        for line in path.read_text().splitlines()
        if line.strip() and not line.strip().startswith("#")
    }


class RemoteUserMiddleware:
    """ASGI middleware for hub authentication.

    Auth chain:
    1. Session cookie
    2. X-Remote-User from trusted proxy IP
    3. Authorization: Bearer token
    4. Dev mode fallback
    5. 403

    If ``allowed_users_file`` exists, only listed users (and instructors)
    may access the hub.
    """

    def __init__(
        self,
        app,
        *,
        secret: str,
        trusted_proxies: set[str] | None = None,
        trusted_header: str = "x-remote-user",
        dev: bool = False,
        allowed_users_file: Path | None = None,
    ):
        self.app = app
        self.secret = secret
        self.trusted_proxies = trusted_proxies or set()
        self.trusted_header = trusted_header.lower()
        self.dev = dev
        self.allowed_users_file = allowed_users_file

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        client_ip = scope.get("client", ("", 0))[0]
        username = None
        set_cookie = False

        # 1. Check session cookie
        cookie_val = _parse_cookie(scope, COOKIE_NAME)
        if cookie_val:
            username = verify_session_cookie(self.secret, cookie_val)

        # 2. Check trusted proxy header
        if username is None and client_ip in self.trusted_proxies:
            header_user = _get_header(scope, self.trusted_header)
            if header_user:
                username = header_user
                set_cookie = True

        # 3. Check Bearer token
        if username is None:
            auth_header = _get_header(scope, "authorization")
            if auth_header and auth_header.startswith("Bearer "):
                token = auth_header[7:]
                username = verify_token(self.secret, token)

        # 4. Dev mode fallback
        if username is None and self.dev:
            header_user = _get_header(scope, self.trusted_header)
            if header_user:
                username = header_user
                set_cookie = True
            else:
                # Assign a random guest identity and persist via cookie
                import secrets as _secrets

                username = f"guest-{_secrets.token_hex(2)}"
                set_cookie = True

        # 5. Reject unauthenticated
        if username is None:
            if scope["type"] == "http":
                await send(
                    {
                        "type": "http.response.start",
                        "status": 403,
                        "headers": [(b"content-type", b"text/plain")],
                    }
                )
                await send({"type": "http.response.body", "body": b"403 Forbidden"})
            return

        instructor = is_instructor(username)

        # 6. Check allowlist (instructors always pass)
        if not instructor and self.allowed_users_file is not None:
            allowed = load_allowed_users(self.allowed_users_file)
            if allowed is not None and username not in allowed:
                if scope["type"] == "http":
                    await send(
                        {
                            "type": "http.response.start",
                            "status": 403,
                            "headers": [(b"content-type", b"text/html")],
                        }
                    )
                    await send(
                        {"type": "http.response.body", "body": _NOT_ENROLLED_HTML}
                    )
                return

        scope["user"] = {
            "username": username,
            "is_instructor": instructor,
        }

        if not set_cookie:
            await self.app(scope, receive, send)
            return

        # Wrap send to inject Set-Cookie on first response
        cookie_value = make_session_cookie(self.secret, username)
        cookie_set = False

        async def send_with_cookie(message):
            nonlocal cookie_set
            if message["type"] == "http.response.start" and not cookie_set:
                cookie_set = True
                headers = list(message.get("headers", []))
                cookie_str = (
                    f"{COOKIE_NAME}={cookie_value}; "
                    f"Path=/; HttpOnly; SameSite=Lax; Max-Age=86400"
                )
                headers.append((b"set-cookie", cookie_str.encode()))
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_with_cookie)


# -- FastAPI dependency helpers --


def require_user(request) -> str:
    """FastAPI dependency: extract username from scope or raise 403."""
    from fastapi import HTTPException

    user = request.scope.get("user")
    if not user or not user.get("username"):
        raise HTTPException(status_code=403, detail="Authentication required")
    return user["username"]


def require_instructor(request) -> str:
    """FastAPI dependency: require instructor role or raise 403."""
    from fastapi import HTTPException

    user = request.scope.get("user")
    if not user or not user.get("is_instructor"):
        raise HTTPException(status_code=403, detail="Instructor access required")
    return user["username"]
