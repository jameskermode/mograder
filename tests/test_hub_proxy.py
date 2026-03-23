"""Tests for hub HTTP/WS proxy (Phase 5)."""

from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest

from mograder.hub.models import MarimoSession
from mograder.hub.proxy import create_proxy_router


@pytest.fixture
def mock_session_manager():
    sm = MagicMock()
    sm.sessions = {}
    return sm


def _make_session(username="alice", assignment="hw1", port=18000):
    proc = MagicMock()
    proc.returncode = None  # still running
    return MarimoSession(
        username=username,
        assignment=assignment,
        port=port,
        process=proc,
        notebook_path=f"/tmp/{username}/{assignment}/{assignment}.py",
        last_seen=time.time(),
    )


class TestProxyRoutes:
    def test_user_isolation(self, mock_session_manager):
        """User A requests /edit/B/hw1/ → 403."""
        from fastapi import FastAPI
        from starlette.testclient import TestClient

        app = FastAPI()
        router = create_proxy_router(mock_session_manager)
        app.include_router(router)

        # Simulate user "alice" trying to access "bob"'s session
        @app.middleware("http")
        async def inject_user(request, call_next):
            request.scope["user"] = {"username": "alice", "is_instructor": False}
            return await call_next(request)

        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/edit/bob/hw1/")
        assert resp.status_code == 403

    def test_instructor_bypass(self, mock_session_manager):
        """Instructor can access any user's session."""
        from fastapi import FastAPI
        from starlette.testclient import TestClient

        session = _make_session("alice", "hw1", 18000)
        mock_session_manager.sessions = {("alice", "hw1"): session}

        app = FastAPI()
        router = create_proxy_router(mock_session_manager)
        app.include_router(router)

        @app.middleware("http")
        async def inject_user(request, call_next):
            request.scope["user"] = {
                "username": "__instructor__",
                "is_instructor": True,
            }
            return await call_next(request)

        # This will fail to proxy (no upstream), but should not get 403
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/edit/alice/hw1/")
        # Should not be 403 — will be 502 or similar since no upstream
        assert resp.status_code != 403

    def test_no_session_404(self, mock_session_manager):
        """No active session → 404."""
        from fastapi import FastAPI
        from starlette.testclient import TestClient

        mock_session_manager.sessions = {}

        app = FastAPI()
        router = create_proxy_router(mock_session_manager)
        app.include_router(router)

        @app.middleware("http")
        async def inject_user(request, call_next):
            request.scope["user"] = {"username": "alice", "is_instructor": False}
            return await call_next(request)

        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/edit/alice/hw1/")
        assert resp.status_code == 404

    def test_proxy_touches_last_seen(self, mock_session_manager):
        """Proxy hit updates session.last_seen."""
        from fastapi import FastAPI
        from starlette.testclient import TestClient

        session = _make_session("alice", "hw1", 18000)
        old_last_seen = session.last_seen - 100
        session.last_seen = old_last_seen
        mock_session_manager.sessions = {("alice", "hw1"): session}

        app = FastAPI()
        router = create_proxy_router(mock_session_manager)
        app.include_router(router)

        @app.middleware("http")
        async def inject_user(request, call_next):
            request.scope["user"] = {"username": "alice", "is_instructor": False}
            return await call_next(request)

        client = TestClient(app, raise_server_exceptions=False)
        client.get("/edit/alice/hw1/")
        assert session.last_seen > old_last_seen
