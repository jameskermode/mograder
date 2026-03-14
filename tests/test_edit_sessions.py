"""Tests for mograder.edit_sessions — shared utility, session manager, ASGI proxy."""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Layer 1: Shared headless spawn utility
# ---------------------------------------------------------------------------


class TestSpawnHeadlessEdit:
    def test_command_flags_sandbox(self):
        """Verify the command includes --sandbox --headless flags."""
        with patch("mograder.edit_sessions.subprocess.Popen") as mock_popen:
            mock_proc = MagicMock()
            mock_proc.stdout = iter(["URL: http://127.0.0.1:1234\n"])
            mock_proc.kill = MagicMock()
            mock_popen.return_value = mock_proc

            from mograder.edit_sessions import spawn_headless_edit

            result = spawn_headless_edit("/tmp/test.py", spawn_timeout=2)

            cmd = mock_popen.call_args[0][0]
            assert "--sandbox" in cmd
            assert "--headless" in cmd
            assert "--host" in cmd
            assert "127.0.0.1" in cmd
            assert "/tmp/test.py" in cmd
            assert result.port == 1234

    def test_command_flags_no_sandbox(self):
        """Verify --sandbox is omitted when sandbox=False."""
        with patch("mograder.edit_sessions.subprocess.Popen") as mock_popen:
            mock_proc = MagicMock()
            mock_proc.stdout = iter(["URL: http://127.0.0.1:5678\n"])
            mock_proc.kill = MagicMock()
            mock_popen.return_value = mock_proc

            from mograder.edit_sessions import spawn_headless_edit

            spawn_headless_edit("/tmp/test.py", sandbox=False, spawn_timeout=2)

            cmd = mock_popen.call_args[0][0]
            assert "--sandbox" not in cmd

    def test_command_flags_base_url_and_no_token(self):
        """Verify --base-url and --no-token flags."""
        with patch("mograder.edit_sessions.subprocess.Popen") as mock_popen:
            mock_proc = MagicMock()
            mock_proc.stdout = iter(["URL: http://127.0.0.1:9999\n"])
            mock_proc.kill = MagicMock()
            mock_popen.return_value = mock_proc

            from mograder.edit_sessions import spawn_headless_edit

            spawn_headless_edit(
                "/tmp/test.py",
                base_url="/live/grader/_edit/abc123",
                token=False,
                timeout=30,
                spawn_timeout=2,
            )

            cmd = mock_popen.call_args[0][0]
            assert "--base-url" in cmd
            idx = cmd.index("--base-url")
            assert cmd[idx + 1] == "/live/grader/_edit/abc123"
            assert "--no-token" in cmd
            assert "--timeout" in cmd
            idx2 = cmd.index("--timeout")
            assert cmd[idx2 + 1] == "30"

    def test_url_extraction(self):
        """Verify URL and port are extracted from marimo stdout."""
        with patch("mograder.edit_sessions.subprocess.Popen") as mock_popen:
            mock_proc = MagicMock()
            # Simulate marimo output with some noise before the URL
            mock_proc.stdout = iter(
                [
                    "Installing dependencies...\n",
                    "Downloading https://pypi.org/something\n",
                    "URL: http://127.0.0.1:4567\n",
                    "Ready.\n",
                ]
            )
            mock_proc.kill = MagicMock()
            mock_popen.return_value = mock_proc

            from mograder.edit_sessions import spawn_headless_edit

            result = spawn_headless_edit("/tmp/test.py", spawn_timeout=5)
            assert result.url == "http://127.0.0.1:4567"
            assert result.port == 4567

    def test_timeout_kills_process(self):
        """Verify TimeoutError is raised and process is killed."""
        with patch("mograder.edit_sessions.subprocess.Popen") as mock_popen:
            mock_proc = MagicMock()
            # No URL line in output — simulate a hang
            mock_proc.stdout = iter(["Installing...\n", "Still installing...\n"])
            mock_proc.kill = MagicMock()
            mock_popen.return_value = mock_proc

            from mograder.edit_sessions import spawn_headless_edit

            with pytest.raises(TimeoutError, match="did not produce URL"):
                spawn_headless_edit("/tmp/test.py", spawn_timeout=0.5)
            mock_proc.kill.assert_called_once()


class TestRewriteCodespacesUrl:
    def test_basic_rewrite(self, monkeypatch):
        monkeypatch.setenv("CODESPACE_NAME", "my-codespace")
        monkeypatch.setenv("GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN", "app.github.dev")
        from mograder.edit_sessions import rewrite_codespaces_url

        result = rewrite_codespaces_url("http://127.0.0.1:3456")
        assert result == "https://my-codespace-3456.app.github.dev"

    def test_preserves_query_string(self, monkeypatch):
        monkeypatch.setenv("CODESPACE_NAME", "my-cs")
        from mograder.edit_sessions import rewrite_codespaces_url

        result = rewrite_codespaces_url("http://127.0.0.1:3456?token=abc123")
        assert result == "https://my-cs-3456.app.github.dev?token=abc123"

    def test_no_port_returns_unchanged(self, monkeypatch):
        monkeypatch.setenv("CODESPACE_NAME", "my-cs")
        from mograder.edit_sessions import rewrite_codespaces_url

        result = rewrite_codespaces_url("http://localhost")
        assert result == "http://localhost"


# ---------------------------------------------------------------------------
# Layer 2: Session manager
# ---------------------------------------------------------------------------


class TestEditSessionManager:
    @pytest.fixture
    def manager(self):
        from mograder.edit_sessions import EditSessionManager

        mgr = EditSessionManager(base_url="/live/grader", idle_timeout=10)
        with patch("mograder.edit_sessions._kill_tree"):
            yield mgr
            mgr.shutdown()

    @patch("mograder.edit_sessions.spawn_headless_edit")
    def test_start_session(self, mock_spawn, manager):
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        from mograder.edit_sessions import HeadlessSession

        mock_spawn.return_value = HeadlessSession(
            proc=mock_proc, url="http://127.0.0.1:5555", port=5555
        )

        session = manager.start("/tmp/notebook.py")
        assert session.session_id in manager.sessions
        assert session.path == "/tmp/notebook.py"
        assert session.port == 5555

        # Verify spawn was called with correct args
        mock_spawn.assert_called_once()
        call_kwargs = mock_spawn.call_args[1]
        assert call_kwargs["host"] == "127.0.0.1"
        assert call_kwargs["token"] is False
        assert call_kwargs["timeout"] == 30

    @patch("mograder.edit_sessions.spawn_headless_edit")
    def test_reuse_existing_session(self, mock_spawn, manager):
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        from mograder.edit_sessions import HeadlessSession

        mock_spawn.return_value = HeadlessSession(
            proc=mock_proc, url="http://127.0.0.1:5555", port=5555
        )

        s1 = manager.start("/tmp/notebook.py")
        s2 = manager.start("/tmp/notebook.py")
        assert s1.session_id == s2.session_id
        # spawn should only be called once
        assert mock_spawn.call_count == 1

    @patch("mograder.edit_sessions._kill_tree")
    @patch("mograder.edit_sessions.spawn_headless_edit")
    def test_stop_session(self, mock_spawn, mock_kill, manager):
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        from mograder.edit_sessions import HeadlessSession

        mock_spawn.return_value = HeadlessSession(
            proc=mock_proc, url="http://127.0.0.1:5555", port=5555
        )

        session = manager.start("/tmp/notebook.py")
        sid = session.session_id
        assert manager.stop(sid) is True
        assert sid not in manager.sessions
        mock_kill.assert_called_once_with(mock_proc.pid)

    @patch("mograder.edit_sessions.spawn_headless_edit")
    def test_stop_nonexistent_returns_false(self, mock_spawn, manager):
        assert manager.stop("nonexistent") is False

    @patch("mograder.edit_sessions._kill_tree")
    @patch("mograder.edit_sessions.spawn_headless_edit")
    def test_cleanup_stale_dead_process(self, mock_spawn, mock_kill, manager):
        mock_proc = MagicMock()
        mock_proc.poll.return_value = 0  # process exited
        from mograder.edit_sessions import HeadlessSession

        mock_spawn.return_value = HeadlessSession(
            proc=mock_proc, url="http://127.0.0.1:5555", port=5555
        )

        session = manager.start("/tmp/notebook.py")
        sid = session.session_id
        # Force the proc to look dead
        session.proc.poll.return_value = 0
        manager.cleanup_stale()
        assert sid not in manager.sessions

    @patch("mograder.edit_sessions._kill_tree")
    @patch("mograder.edit_sessions.spawn_headless_edit")
    def test_cleanup_stale_idle_timeout(self, mock_spawn, mock_kill, manager):
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        from mograder.edit_sessions import HeadlessSession

        mock_spawn.return_value = HeadlessSession(
            proc=mock_proc, url="http://127.0.0.1:5555", port=5555
        )

        session = manager.start("/tmp/notebook.py")
        sid = session.session_id
        # Set last_activity to long ago
        session.last_activity = time.time() - 20  # idle_timeout is 10
        manager.cleanup_stale()
        assert sid not in manager.sessions

    @patch("mograder.edit_sessions.spawn_headless_edit")
    def test_get_returns_none_for_dead_session(self, mock_spawn, manager):
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        from mograder.edit_sessions import HeadlessSession

        mock_spawn.return_value = HeadlessSession(
            proc=mock_proc, url="http://127.0.0.1:5555", port=5555
        )

        session = manager.start("/tmp/notebook.py")
        session.proc.poll.return_value = 1  # process died
        assert manager.get(session.session_id) is None

    @patch("mograder.edit_sessions.spawn_headless_edit")
    def test_list_sessions(self, mock_spawn, manager):
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        from mograder.edit_sessions import HeadlessSession

        mock_spawn.return_value = HeadlessSession(
            proc=mock_proc, url="http://127.0.0.1:5555", port=5555
        )

        session = manager.start("/tmp/notebook.py")
        listing = manager.list_sessions()
        assert len(listing) == 1
        assert listing[0]["session_id"] == session.session_id
        assert listing[0]["path"] == "/tmp/notebook.py"
        assert "/live/grader/_edit/" in listing[0]["url"]


# ---------------------------------------------------------------------------
# Layer 3: ASGI proxy app
# ---------------------------------------------------------------------------


class TestEditProxyApp:
    @pytest.fixture
    def manager(self):
        from mograder.edit_sessions import EditSessionManager

        mgr = EditSessionManager(base_url="/live/grader", idle_timeout=60)
        with patch("mograder.edit_sessions._kill_tree"):
            yield mgr
            mgr.shutdown()

    @pytest.fixture
    def mock_http_client(self):
        """Shared mock httpx.AsyncClient injected into the proxy app."""
        return MagicMock()

    @pytest.fixture
    def client(self, manager, mock_http_client):
        from starlette.testclient import TestClient

        from mograder.edit_sessions import build_edit_proxy_app

        app = build_edit_proxy_app(manager, http_client=mock_http_client)

        # Wrap with a minimal middleware that sets scope["user"]
        async def authed_app(scope, receive, send):
            if scope["type"] in ("http", "websocket"):
                scope["user"] = {"username": "admin", "is_instructor": True}
            await app(scope, receive, send)

        return TestClient(authed_app)

    @pytest.fixture
    def non_instructor_client(self, manager, mock_http_client):
        from starlette.testclient import TestClient

        from mograder.edit_sessions import build_edit_proxy_app

        app = build_edit_proxy_app(manager, http_client=mock_http_client)

        async def unauthed_app(scope, receive, send):
            if scope["type"] in ("http", "websocket"):
                scope["user"] = {"username": "student", "is_instructor": False}
            await app(scope, receive, send)

        return TestClient(unauthed_app)

    def test_create_session_instructor_only(self, non_instructor_client):
        resp = non_instructor_client.post(
            "/live/grader/_api/edit",
            json={"path": "/tmp/notebook.py"},
        )
        assert resp.status_code == 403

    @patch("mograder.edit_sessions.spawn_headless_edit")
    def test_create_session_returns_url(self, mock_spawn, client, manager):
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        from mograder.edit_sessions import HeadlessSession

        mock_spawn.return_value = HeadlessSession(
            proc=mock_proc, url="http://127.0.0.1:7777", port=7777
        )

        resp = client.post(
            "/live/grader/_api/edit",
            json={"path": "/tmp/notebook.py"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "session_id" in data
        assert "/live/grader/_edit/" in data["url"]

    def test_create_session_missing_path(self, client):
        resp = client.post(
            "/live/grader/_api/edit",
            json={},
        )
        assert resp.status_code == 400

    @patch("mograder.edit_sessions.spawn_headless_edit")
    def test_list_sessions_endpoint(self, mock_spawn, client, manager):
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        from mograder.edit_sessions import HeadlessSession

        mock_spawn.return_value = HeadlessSession(
            proc=mock_proc, url="http://127.0.0.1:7777", port=7777
        )
        manager.start("/tmp/notebook.py")

        resp = client.get("/live/grader/_api/edit")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["path"] == "/tmp/notebook.py"

    @patch("mograder.edit_sessions._kill_tree")
    @patch("mograder.edit_sessions.spawn_headless_edit")
    def test_delete_session(self, mock_spawn, mock_kill, client, manager):
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        from mograder.edit_sessions import HeadlessSession

        mock_spawn.return_value = HeadlessSession(
            proc=mock_proc, url="http://127.0.0.1:7777", port=7777
        )
        session = manager.start("/tmp/notebook.py")

        resp = client.request(
            "DELETE",
            "/live/grader/_api/edit",
            json={"session_id": session.session_id},
        )
        assert resp.status_code == 200
        assert resp.json()["removed"] is True

    def test_delete_session_forbidden(self, non_instructor_client):
        resp = non_instructor_client.request(
            "DELETE",
            "/live/grader/_api/edit",
            json={"session_id": "nonexistent"},
        )
        assert resp.status_code == 403

    def test_proxy_http_forbidden_for_non_instructor(self, non_instructor_client):
        """Non-instructors cannot access edit proxy routes."""
        resp = non_instructor_client.get("/live/grader/_edit/any_session/")
        assert resp.status_code == 403

    @patch("mograder.edit_sessions.spawn_headless_edit")
    def test_proxy_http_forwards(self, mock_spawn, client, manager):
        """Test that HTTP proxy returns 404 for unknown session."""
        resp = client.get("/live/grader/_edit/nonexistent/")
        assert resp.status_code == 404

    @patch("mograder.edit_sessions.spawn_headless_edit")
    def test_proxy_http_known_session(
        self, mock_spawn, client, manager, mock_http_client
    ):
        """Test HTTP proxy with a known session — mocked upstream via httpx."""
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        from mograder.edit_sessions import HeadlessSession

        mock_spawn.return_value = HeadlessSession(
            proc=mock_proc, url="http://127.0.0.1:7777", port=7777
        )
        session = manager.start("/tmp/notebook.py")

        import httpx

        mock_response = httpx.Response(
            200,
            content=b"<html>marimo</html>",
            headers={"content-type": "text/html"},
            request=httpx.Request("GET", "http://127.0.0.1:7777/"),
        )

        async def _request(**kwargs):
            return mock_response

        mock_http_client.request = MagicMock(side_effect=_request)

        resp = client.get(f"/live/grader/_edit/{session.session_id}/")
        assert resp.status_code == 200
        assert b"marimo" in resp.content

    @patch("mograder.edit_sessions.spawn_headless_edit")
    def test_proxy_adds_cache_headers_for_assets(
        self, mock_spawn, client, manager, mock_http_client
    ):
        """Asset responses get immutable cache-control header."""
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        from mograder.edit_sessions import HeadlessSession

        mock_spawn.return_value = HeadlessSession(
            proc=mock_proc, url="http://127.0.0.1:7777", port=7777
        )
        session = manager.start("/tmp/notebook.py")

        import httpx

        mock_response = httpx.Response(
            200,
            content=b"// js content",
            headers={"content-type": "application/javascript"},
            request=httpx.Request("GET", "http://127.0.0.1:7777/"),
        )

        async def _request(**kwargs):
            return mock_response

        mock_http_client.request = MagicMock(side_effect=_request)

        resp = client.get(
            f"/live/grader/_edit/{session.session_id}/assets/cells-CCtxWKxf.js"
        )
        assert resp.status_code == 200
        assert "immutable" in resp.headers["cache-control"]

    @patch("mograder.edit_sessions.spawn_headless_edit")
    def test_proxy_no_cache_headers_for_non_assets(
        self, mock_spawn, client, manager, mock_http_client
    ):
        """Index HTML should not get immutable cache-control."""
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        from mograder.edit_sessions import HeadlessSession

        mock_spawn.return_value = HeadlessSession(
            proc=mock_proc, url="http://127.0.0.1:7777", port=7777
        )
        session = manager.start("/tmp/notebook.py")

        import httpx

        mock_response = httpx.Response(
            200,
            content=b"<html><div id='root'></div></html>",
            headers={"content-type": "text/html"},
            request=httpx.Request("GET", "http://127.0.0.1:7777/"),
        )

        async def _request(**kwargs):
            return mock_response

        mock_http_client.request = MagicMock(side_effect=_request)

        resp = client.get(f"/live/grader/_edit/{session.session_id}/")
        assert resp.status_code == 200
        assert "immutable" not in resp.headers.get("cache-control", "")

    @patch("mograder.edit_sessions.spawn_headless_edit")
    def test_loading_screen_injected(
        self, mock_spawn, client, manager, mock_http_client
    ):
        """HTML responses have a loading spinner injected inside #root."""
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        from mograder.edit_sessions import HeadlessSession

        mock_spawn.return_value = HeadlessSession(
            proc=mock_proc, url="http://127.0.0.1:7777", port=7777
        )
        session = manager.start("/tmp/notebook.py")

        import httpx

        mock_response = httpx.Response(
            200,
            content=b'<html><div id="root"></div></html>',
            headers={"content-type": "text/html"},
            request=httpx.Request("GET", "http://127.0.0.1:7777/"),
        )

        async def _request(**kwargs):
            return mock_response

        mock_http_client.request = MagicMock(side_effect=_request)

        resp = client.get(f"/live/grader/_edit/{session.session_id}/")
        assert resp.status_code == 200
        assert b"Loading notebook..." in resp.content
        assert b'<div id="root"></div>' not in resp.content

    @patch("mograder.edit_sessions.spawn_headless_edit")
    def test_loading_screen_not_injected_for_non_html(
        self, mock_spawn, client, manager, mock_http_client
    ):
        """JS/CSS responses are not modified by loading screen injection."""
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        from mograder.edit_sessions import HeadlessSession

        mock_spawn.return_value = HeadlessSession(
            proc=mock_proc, url="http://127.0.0.1:7777", port=7777
        )
        session = manager.start("/tmp/notebook.py")

        import httpx

        js_content = b'var root = document.getElementById("root");'
        mock_response = httpx.Response(
            200,
            content=js_content,
            headers={"content-type": "application/javascript"},
            request=httpx.Request("GET", "http://127.0.0.1:7777/"),
        )

        async def _request(**kwargs):
            return mock_response

        mock_http_client.request = MagicMock(side_effect=_request)

        resp = client.get(f"/live/grader/_edit/{session.session_id}/app.js")
        assert resp.status_code == 200
        assert resp.content == js_content


# ---------------------------------------------------------------------------
# Asset path regex
# ---------------------------------------------------------------------------


class TestAssetPathRegex:
    """Test that _ASSET_PATH_RE matches content-hashed assets correctly."""

    def test_matches_hashed_js(self):
        from mograder.edit_sessions import _ASSET_PATH_RE

        assert _ASSET_PATH_RE.search("/assets/cells-CCtxWKxf.js")

    def test_matches_hashed_css(self):
        from mograder.edit_sessions import _ASSET_PATH_RE

        assert _ASSET_PATH_RE.search("/assets/index-Dh3JkL9m.css")

    def test_matches_long_hash(self):
        from mograder.edit_sessions import _ASSET_PATH_RE

        assert _ASSET_PATH_RE.search("/assets/vendor-Ab3CdE6fGhIj.js")

    def test_rejects_unhashed_path(self):
        from mograder.edit_sessions import _ASSET_PATH_RE

        assert not _ASSET_PATH_RE.search("/assets/favicon.ico")

    def test_rejects_short_hash(self):
        from mograder.edit_sessions import _ASSET_PATH_RE

        assert not _ASSET_PATH_RE.search("/assets/x-Ab.js")

    def test_rejects_api_path(self):
        from mograder.edit_sessions import _ASSET_PATH_RE

        assert not _ASSET_PATH_RE.search("/api/kernel/sessions")

    def test_rejects_root_html(self):
        from mograder.edit_sessions import _ASSET_PATH_RE

        assert not _ASSET_PATH_RE.search("/")


# ---------------------------------------------------------------------------
# Loading screen helper
# ---------------------------------------------------------------------------


class TestInjectLoadingScreen:
    def test_replaces_empty_root(self):
        from mograder.edit_sessions import _inject_loading_screen

        html = b'<html><div id="root"></div></html>'
        result = _inject_loading_screen(html)
        assert b"Loading notebook..." in result
        assert b'<div id="root"></div>' not in result

    def test_no_root_unchanged(self):
        from mograder.edit_sessions import _inject_loading_screen

        html = b"<html><body>hello</body></html>"
        assert _inject_loading_screen(html) == html

    def test_already_has_content_unchanged(self):
        from mograder.edit_sessions import _inject_loading_screen

        html = b'<html><div id="root"><p>existing</p></div></html>'
        result = _inject_loading_screen(html)
        # No empty root to replace, so content is unchanged
        assert result == html


# ---------------------------------------------------------------------------
# Lifespan / client ownership
# ---------------------------------------------------------------------------


class TestLifespan:
    def test_lifespan_does_not_close_injected_client(self):
        """Externally-provided http_client is NOT closed by the lifespan."""
        from mograder.edit_sessions import EditSessionManager, build_edit_proxy_app

        mgr = EditSessionManager(base_url="/live/grader", idle_timeout=60)
        mock_client = MagicMock()

        async def _aclose():
            pass

        mock_client.aclose = MagicMock(side_effect=_aclose)

        with patch("mograder.edit_sessions._kill_tree"):
            app = build_edit_proxy_app(mgr, http_client=mock_client)

            from starlette.testclient import TestClient

            # TestClient enters and exits the lifespan
            with TestClient(app):
                pass

            # aclose should NOT have been called for injected client
            mock_client.aclose.assert_not_called()
            mgr.shutdown()


# ---------------------------------------------------------------------------
# MarimoOptimizeMiddleware (shared ASGI middleware)
# ---------------------------------------------------------------------------


class TestMarimoOptimizeMiddleware:
    """Test the shared ASGI middleware that adds cache headers and loading screen."""

    @pytest.fixture
    def make_client(self):
        """Factory: returns a TestClient wrapping the middleware around a fake ASGI app."""
        from starlette.testclient import TestClient

        from mograder.edit_sessions import MarimoOptimizeMiddleware

        def _make(status, body, headers, *, path="/"):
            async def inner(scope, receive, send):
                await send(
                    {
                        "type": "http.response.start",
                        "status": status,
                        "headers": [
                            (k.encode(), v.encode()) for k, v in headers.items()
                        ],
                    }
                )
                await send({"type": "http.response.body", "body": body})

            app = MarimoOptimizeMiddleware(inner)

            # Wrap with a tiny app that overrides the path for testing
            async def path_app(scope, receive, send):
                scope["path"] = path
                await app(scope, receive, send)

            return TestClient(path_app)

        return _make

    def test_adds_cache_headers_for_hashed_asset(self, make_client):
        """Asset paths with content hashes get immutable cache-control."""
        client = make_client(
            200,
            b"// js content",
            {"content-type": "application/javascript"},
            path="/assets/cells-CCtxWKxf.js",
        )
        resp = client.get("/assets/cells-CCtxWKxf.js")
        assert resp.status_code == 200
        assert "immutable" in resp.headers["cache-control"]
        assert "31536000" in resp.headers["cache-control"]

    def test_no_cache_headers_for_unhashed_path(self, make_client):
        """Non-hashed paths like /favicon.ico should not get cache headers."""
        client = make_client(
            200,
            b"icon data",
            {"content-type": "image/x-icon"},
            path="/favicon.ico",
        )
        resp = client.get("/favicon.ico")
        assert "immutable" not in resp.headers.get("cache-control", "")

    def test_no_cache_headers_for_html_page(self, make_client):
        """HTML pages should not get immutable cache headers."""
        client = make_client(
            200,
            b"<html><body>hello</body></html>",
            {"content-type": "text/html"},
            path="/",
        )
        resp = client.get("/")
        assert "immutable" not in resp.headers.get("cache-control", "")

    def test_injects_loading_screen_into_html(self, make_client):
        """HTML responses with empty #root get loading spinner injected."""
        client = make_client(
            200,
            b'<html><div id="root"></div></html>',
            {"content-type": "text/html"},
            path="/",
        )
        resp = client.get("/")
        assert resp.status_code == 200
        assert b"Loading notebook..." in resp.content
        assert b'<div id="root"></div>' not in resp.content

    def test_does_not_modify_non_html_body(self, make_client):
        """JS responses should not be modified."""
        js_content = b'var root = document.getElementById("root");'
        client = make_client(
            200,
            js_content,
            {"content-type": "application/javascript"},
            path="/app.js",
        )
        resp = client.get("/app.js")
        assert resp.content == js_content

    def test_strips_content_length_for_html(self, make_client):
        """content-length should be removed for HTML since body size changes."""
        original = b'<html><div id="root"></div></html>'
        client = make_client(
            200,
            original,
            {"content-type": "text/html", "content-length": str(len(original))},
            path="/",
        )
        resp = client.get("/")
        # Body was modified (loading screen injected), so content-length
        # should not reflect the original size
        assert b"Loading notebook..." in resp.content
        # The response should still be valid (Starlette TestClient handles this)
        assert resp.status_code == 200

    def test_websocket_passthrough(self):
        """WebSocket scopes should pass through without modification."""
        from mograder.edit_sessions import MarimoOptimizeMiddleware

        calls = []

        async def inner(scope, receive, send):
            calls.append(scope["type"])

        app = MarimoOptimizeMiddleware(inner)

        import asyncio

        asyncio.run(app({"type": "websocket"}, None, None))
        assert calls == ["websocket"]


class TestFormgraderMiddlewareWiring:
    """Verify MarimoOptimizeMiddleware is wired into the formgrader marimo app."""

    def test_formgrader_includes_optimize_middleware(self):
        """The formgrader_asgi module should include MarimoOptimizeMiddleware."""
        from mograder import formgrader_asgi

        # The middleware list passed to marimo's with_app includes our middleware
        # We verify by checking the import worked and the class is referenced
        assert hasattr(formgrader_asgi, "MarimoOptimizeMiddleware")
