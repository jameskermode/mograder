"""Tests for hub authentication (Phase 3)."""

from __future__ import annotations

import asyncio
import time

import pytest

from mograder.hub.auth import (
    RemoteUserMiddleware,
    load_allowed_users,
    make_session_cookie,
    require_instructor,
    require_user,
    verify_session_cookie,
)


SECRET = "test-secret-key-for-hub"


class TestSessionCookie:
    def test_roundtrip(self):
        """make → verify returns same username."""
        cookie = make_session_cookie(SECRET, "alice")
        username = verify_session_cookie(SECRET, cookie)
        assert username == "alice"

    def test_expired(self):
        """Cookie older than max_age returns None."""
        cookie = make_session_cookie(SECRET, "alice", timestamp=time.time() - 100000)
        username = verify_session_cookie(SECRET, cookie, max_age=3600)
        assert username is None

    def test_tampered(self):
        """Modified HMAC returns None."""
        cookie = make_session_cookie(SECRET, "alice")
        tampered = cookie[:-1] + ("a" if cookie[-1] != "a" else "b")
        username = verify_session_cookie(SECRET, tampered)
        assert username is None

    def test_wrong_secret(self):
        """Cookie made with different secret fails verification."""
        cookie = make_session_cookie("secret-a", "alice")
        username = verify_session_cookie("secret-b", cookie)
        assert username is None


async def _call_middleware(middleware, headers=None, client=None):
    """Call ASGI middleware and capture response."""
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/test",
        "headers": headers or [],
        "client": client or ("127.0.0.1", 12345),
    }
    response = {}

    async def receive():
        return {"type": "http.request", "body": b""}

    async def send(message):
        if message["type"] == "http.response.start":
            response["status"] = message["status"]
            response["headers"] = dict(message.get("headers", []))
        elif message["type"] == "http.response.body":
            response["body"] = message.get("body", b"")

    await middleware(scope, receive, send)
    return response


def _echo_app():
    """ASGI app that echoes scope['user'] as response body."""

    async def app(scope, receive, send):
        user = scope.get("user", {})
        body = f"user={user.get('username', '')}".encode()
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"content-type", b"text/plain")],
            }
        )
        await send({"type": "http.response.body", "body": body})

    return app


def _make_middleware(dev=False):
    return RemoteUserMiddleware(
        _echo_app(),
        secret=SECRET,
        trusted_proxies={"10.0.0.1"},
        trusted_header="x-remote-user",
        dev=dev,
    )


class TestMiddleware:
    def test_trusted_proxy_sets_cookie(self):
        """X-Remote-User from trusted IP sets cookie and passes through."""
        mw = _make_middleware()
        resp = asyncio.run(
            _call_middleware(
                mw,
                headers=[(b"x-remote-user", b"alice")],
                client=("10.0.0.1", 9999),
            )
        )
        assert resp["status"] == 200
        assert b"user=alice" in resp["body"]
        assert b"set-cookie" in resp["headers"]

    def test_cookie_auth(self):
        """Valid session cookie authenticates without X-Remote-User."""
        mw = _make_middleware()
        cookie = make_session_cookie(SECRET, "bob")
        resp = asyncio.run(
            _call_middleware(
                mw,
                headers=[(b"cookie", f"mograder_session={cookie}".encode())],
                client=("192.168.1.1", 9999),
            )
        )
        assert resp["status"] == 200
        assert b"user=bob" in resp["body"]

    def test_unknown_ip_403(self):
        """No cookie, untrusted IP → 403."""
        mw = _make_middleware()
        resp = asyncio.run(_call_middleware(mw, client=("192.168.1.1", 9999)))
        assert resp["status"] == 403

    def test_bearer_token_accepted(self):
        """Valid Bearer token authenticates."""
        from mograder.auth import make_token

        mw = _make_middleware()
        token = make_token(SECRET, "charlie")
        resp = asyncio.run(
            _call_middleware(
                mw,
                headers=[(b"authorization", f"Bearer {token}".encode())],
                client=("192.168.1.1", 9999),
            )
        )
        assert resp["status"] == 200
        assert b"user=charlie" in resp["body"]

    def test_bearer_token_rejected(self):
        """Tampered Bearer token → 403."""
        mw = _make_middleware()
        resp = asyncio.run(
            _call_middleware(
                mw,
                headers=[(b"authorization", b"Bearer fake:token")],
                client=("192.168.1.1", 9999),
            )
        )
        assert resp["status"] == 403

    def test_dev_mode_fallback(self):
        """Dev mode with no headers → dev-user."""
        mw = RemoteUserMiddleware(
            _echo_app(),
            secret=SECRET,
            trusted_proxies=set(),
            trusted_header="x-remote-user",
            dev=True,
        )
        resp = asyncio.run(_call_middleware(mw, client=("192.168.1.1", 9999)))
        assert resp["status"] == 200
        assert b"user=dev-user" in resp["body"]


class TestDependencies:
    def test_require_user_extracts_username(self):
        class FakeRequest:
            scope = {"user": {"username": "alice"}}

        assert require_user(FakeRequest()) == "alice"

    def test_require_user_no_user_403(self):
        from fastapi import HTTPException

        class FakeRequest:
            scope = {}

        with pytest.raises(HTTPException) as exc_info:
            require_user(FakeRequest())
        assert exc_info.value.status_code == 403

    def test_require_instructor_rejects_student(self):
        from fastapi import HTTPException

        class FakeRequest:
            scope = {"user": {"username": "alice", "is_instructor": False}}

        with pytest.raises(HTTPException):
            require_instructor(FakeRequest())

    def test_require_instructor_accepts(self):
        class FakeRequest:
            scope = {"user": {"username": "__instructor__", "is_instructor": True}}

        assert require_instructor(FakeRequest()) == "__instructor__"


class TestAllowlist:
    def test_no_file_allows_all(self, tmp_path):
        """No allowed_users.txt → all authenticated users allowed."""
        mw = RemoteUserMiddleware(
            _echo_app(),
            secret=SECRET,
            trusted_proxies={"10.0.0.1"},
            allowed_users_file=tmp_path / "allowed_users.txt",
        )
        resp = asyncio.run(
            _call_middleware(
                mw,
                headers=[(b"x-remote-user", b"anyone")],
                client=("10.0.0.1", 9999),
            )
        )
        assert resp["status"] == 200
        assert b"user=anyone" in resp["body"]

    def test_allowed_user_passes(self, tmp_path):
        """User in allowlist gets through."""
        (tmp_path / "allowed_users.txt").write_text("alice\nbob\n")
        mw = RemoteUserMiddleware(
            _echo_app(),
            secret=SECRET,
            trusted_proxies={"10.0.0.1"},
            allowed_users_file=tmp_path / "allowed_users.txt",
        )
        resp = asyncio.run(
            _call_middleware(
                mw,
                headers=[(b"x-remote-user", b"alice")],
                client=("10.0.0.1", 9999),
            )
        )
        assert resp["status"] == 200
        assert b"user=alice" in resp["body"]

    def test_blocked_user_gets_403(self, tmp_path):
        """User not in allowlist gets friendly 403."""
        (tmp_path / "allowed_users.txt").write_text("alice\nbob\n")
        mw = RemoteUserMiddleware(
            _echo_app(),
            secret=SECRET,
            trusted_proxies={"10.0.0.1"},
            allowed_users_file=tmp_path / "allowed_users.txt",
        )
        resp = asyncio.run(
            _call_middleware(
                mw,
                headers=[(b"x-remote-user", b"eve")],
                client=("10.0.0.1", 9999),
            )
        )
        assert resp["status"] == 403
        assert b"not enrolled" in resp["body"]

    def test_instructor_bypasses_allowlist(self, tmp_path):
        """Instructor token always passes even if not in allowlist."""
        from mograder.auth import INSTRUCTOR_USER, make_token

        (tmp_path / "allowed_users.txt").write_text("alice\n")
        mw = RemoteUserMiddleware(
            _echo_app(),
            secret=SECRET,
            trusted_proxies=set(),
            allowed_users_file=tmp_path / "allowed_users.txt",
        )
        token = make_token(SECRET, INSTRUCTOR_USER)
        resp = asyncio.run(
            _call_middleware(
                mw,
                headers=[(b"authorization", f"Bearer {token}".encode())],
                client=("192.168.1.1", 9999),
            )
        )
        assert resp["status"] == 200

    def test_comments_and_blanks_ignored(self, tmp_path):
        """Comments and blank lines in allowlist are skipped."""
        (tmp_path / "allowed_users.txt").write_text(
            "# header comment\nalice\n\n# another\nbob\n"
        )
        users = load_allowed_users(tmp_path / "allowed_users.txt")
        assert users == {"alice", "bob"}
