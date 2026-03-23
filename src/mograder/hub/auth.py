"""Hub authentication — session cookies, ASGI middleware, FastAPI deps."""

from __future__ import annotations

import base64
import hashlib
import hmac
import http.cookies
import time

from mograder.auth import is_instructor, verify_token


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


class RemoteUserMiddleware:
    """ASGI middleware for hub authentication.

    Auth chain:
    1. Session cookie
    2. X-Remote-User from trusted proxy IP
    3. Authorization: Bearer token
    4. Dev mode fallback
    5. 403
    """

    def __init__(
        self,
        app,
        *,
        secret: str,
        trusted_proxies: set[str] | None = None,
        trusted_header: str = "x-remote-user",
        dev: bool = False,
    ):
        self.app = app
        self.secret = secret
        self.trusted_proxies = trusted_proxies or set()
        self.trusted_header = trusted_header.lower()
        self.dev = dev

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
            username = header_user or "dev-user"
            if header_user:
                set_cookie = True

        # 5. Reject
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

        scope["user"] = {
            "username": username,
            "is_instructor": is_instructor(username),
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
