"""Tests for hub FastAPI app (Phase 6)."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from starlette.testclient import TestClient

from mograder.hub.app import create_hub_app


@pytest.fixture
def hub_dirs(tmp_path):
    """Create hub directory structure."""
    notebooks = tmp_path / "hub-notebooks"
    notebooks.mkdir()
    release = tmp_path / "hub-release"
    release.mkdir()
    # Create mograder.toml (use forward slashes for Windows TOML compat)
    nb_str = str(notebooks).replace("\\", "/")
    rel_str = str(release).replace("\\", "/")
    (tmp_path / "mograder.toml").write_text(
        f'[hub]\nnotebooks_dir = "{nb_str}"\nrelease_dir = "{rel_str}"\n'
    )
    return {"course_dir": tmp_path, "notebooks": notebooks, "release": release}


@pytest.fixture
def app(hub_dirs):
    """Create test hub app in dev mode."""
    return create_hub_app(
        hub_dirs["course_dir"],
        dev=True,
        notebooks_dir=hub_dirs["notebooks"],
        release_dir=hub_dirs["release"],
    )


@pytest.fixture
def client(app):
    """TestClient with dev-user auth."""
    return TestClient(
        app, raise_server_exceptions=False, headers={"X-Remote-User": "dev-user"}
    )


def _setup_student_file(hub_dirs, username, assignment, content="# student code"):
    """Create a student notebook file."""
    d = hub_dirs["notebooks"] / username / assignment
    d.mkdir(parents=True, exist_ok=True)
    nb = d / f"{assignment}.py"
    nb.write_text(content)
    return nb


def _setup_release(hub_dirs, assignment, content="# release version"):
    """Create a release notebook."""
    d = hub_dirs["release"] / assignment
    d.mkdir(parents=True, exist_ok=True)
    nb = d / f"{assignment}.py"
    nb.write_text(content)
    return nb


class TestUpload:
    def test_safe_file_200(self, client, hub_dirs):
        """Valid .py upload succeeds."""
        content = "import numpy as np\nx = np.array([1, 2, 3])\n"
        resp = client.post(
            "/upload/dev-user/hw1",
            files={"file": ("hw1.py", content, "text/x-python")},
        )
        assert resp.status_code == 200
        nb = hub_dirs["notebooks"] / "dev-user" / "hw1" / "hw1.py"
        assert nb.read_text() == content

    def test_unsafe_file_400(self, client, hub_dirs):
        """File with denied import is rejected."""
        content = "import socket\n"
        resp = client.post(
            "/upload/dev-user/hw1",
            files={"file": ("hw1.py", content, "text/x-python")},
        )
        assert resp.status_code == 400
        assert (
            "denied" in resp.json()["detail"].lower()
            or "unsafe" in resp.json()["detail"].lower()
        )

    def test_archives_existing(self, client, hub_dirs):
        """Existing file is archived before upload."""
        _setup_student_file(hub_dirs, "dev-user", "hw1", "# old code")
        content = "# new code\n"
        resp = client.post(
            "/upload/dev-user/hw1",
            files={"file": ("hw1.py", content, "text/x-python")},
        )
        assert resp.status_code == 200
        d = hub_dirs["notebooks"] / "dev-user" / "hw1"
        baks = list(d.glob("*.bak.*.py"))
        assert len(baks) == 1
        assert baks[0].read_text() == "# old code"

    def test_user_isolation(self, hub_dirs):
        """User A can't upload to user B (non-dev mode)."""
        app = create_hub_app(
            hub_dirs["course_dir"],
            dev=False,
            notebooks_dir=hub_dirs["notebooks"],
            release_dir=hub_dirs["release"],
            secret="test-secret",
        )
        # Without auth, should get 403
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post(
            "/upload/alice/hw1",
            files={"file": ("hw1.py", "# code", "text/x-python")},
        )
        assert resp.status_code == 403


class TestExport:
    def test_returns_file(self, client, hub_dirs):
        """Existing notebook returns file content."""
        _setup_student_file(hub_dirs, "dev-user", "hw1", "# my code")
        resp = client.get("/export/dev-user/hw1")
        assert resp.status_code == 200
        assert b"# my code" in resp.content

    def test_marks_exported(self, client, hub_dirs):
        """Export touches .exported marker."""
        _setup_student_file(hub_dirs, "dev-user", "hw1", "# code")
        client.get("/export/dev-user/hw1")
        marker = hub_dirs["notebooks"] / "dev-user" / "hw1" / ".exported"
        assert marker.exists()


class TestReset:
    def test_with_release(self, client, hub_dirs):
        """Reset with release copies release version."""
        _setup_student_file(hub_dirs, "dev-user", "hw1", "# modified")
        _setup_release(hub_dirs, "hw1", "# release version")
        resp = client.post("/reset/dev-user/hw1")
        assert resp.status_code == 200
        nb = hub_dirs["notebooks"] / "dev-user" / "hw1" / "hw1.py"
        assert nb.read_text() == "# release version"

    def test_without_release(self, client, hub_dirs):
        """Reset without release archives only."""
        _setup_student_file(hub_dirs, "dev-user", "hw1", "# student work")
        resp = client.post("/reset/dev-user/hw1")
        assert resp.status_code == 200
        nb = hub_dirs["notebooks"] / "dev-user" / "hw1" / "hw1.py"
        assert not nb.exists()


class TestStatus:
    def test_status_fields(self, client, hub_dirs):
        """Status returns expected fields."""
        _setup_student_file(hub_dirs, "dev-user", "hw1")
        resp = client.get("/status/dev-user/hw1")
        assert resp.status_code == 200
        data = resp.json()
        assert "file_status" in data
        assert "session_active" in data
        assert "has_release" in data


class TestValidate:
    def test_validate_returns_checks(self, client, hub_dirs):
        """Valid notebook returns check results."""
        _setup_student_file(
            hub_dirs, "dev-user", "hw1", "import marimo\napp = marimo.App()\n"
        )

        with patch("mograder.hub.app.run_notebook") as mock_run:
            mock_result = MagicMock()
            mock_result.checks = []
            mock_result.cell_errors = 0
            mock_result.export_ok = True
            mock_result.export_error = ""
            mock_run.return_value = mock_result

            resp = client.post("/validate/dev-user/hw1")

        assert resp.status_code == 200
        data = resp.json()
        assert "checks" in data
        assert "integrity_level" in data


class TestRelease:
    def test_release_download(self, client, hub_dirs):
        """Authenticated student can download release file."""
        _setup_release(hub_dirs, "hw1", "# release")
        resp = client.get("/release/hw1/hw1.py")
        assert resp.status_code == 200
        assert b"# release" in resp.content

    def test_release_path_traversal(self, client, hub_dirs):
        """../ in filename → 400."""
        _setup_release(hub_dirs, "hw1")
        resp = client.get("/release/hw1/../../../etc/passwd")
        assert resp.status_code in (400, 404, 422)


class TestPublish:
    def test_requires_instructor(self, hub_dirs):
        """Non-dev mode: student cannot publish."""
        from mograder.core.auth import make_token

        secret = "test-secret"
        app = create_hub_app(
            hub_dirs["course_dir"],
            dev=False,
            notebooks_dir=hub_dirs["notebooks"],
            release_dir=hub_dirs["release"],
            secret=secret,
        )
        # Use student token
        token = make_token(secret, "student1")
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post(
            "/publish/hw1",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 403

    def test_publish_writes_files(self, hub_dirs):
        """Publish writes files to release dir."""
        import io

        from mograder.core.auth import INSTRUCTOR_USER, make_token

        secret = "test-secret"
        app = create_hub_app(
            hub_dirs["course_dir"],
            dev=False,
            notebooks_dir=hub_dirs["notebooks"],
            release_dir=hub_dirs["release"],
            secret=secret,
        )
        token = make_token(secret, INSTRUCTOR_USER)
        client = TestClient(app, raise_server_exceptions=False)
        content = "# release notebook\n"
        resp = client.post(
            "/publish/hw1",
            headers={"Authorization": f"Bearer {token}"},
            files={"files": ("hw1.py", io.BytesIO(content.encode()), "text/x-python")},
        )
        assert resp.status_code == 200
        nb = hub_dirs["release"] / "hw1" / "hw1.py"
        assert nb.exists()
        assert nb.read_text() == content

    def test_publish_manifest_format(self, hub_dirs):
        """files.json is {"files": [...]} not a bare list, excluding dotfiles."""
        import io

        from mograder.core.auth import INSTRUCTOR_USER, make_token

        secret = "test-secret"
        app = create_hub_app(
            hub_dirs["course_dir"],
            dev=False,
            notebooks_dir=hub_dirs["notebooks"],
            release_dir=hub_dirs["release"],
            secret=secret,
        )
        token = make_token(secret, INSTRUCTOR_USER)
        client = TestClient(app, raise_server_exceptions=False)

        # Create a dotfile in the release dir first (should be excluded)
        assignment_dir = hub_dirs["release"] / "hw1"
        assignment_dir.mkdir(parents=True, exist_ok=True)
        (assignment_dir / ".hidden").write_text("secret")

        resp = client.post(
            "/publish/hw1",
            headers={"Authorization": f"Bearer {token}"},
            files=[
                ("files", ("hw1.py", io.BytesIO(b"# code"), "text/x-python")),
                ("files", ("data.csv", io.BytesIO(b"a,b\n1,2"), "text/csv")),
            ],
        )
        assert resp.status_code == 200

        manifest_path = hub_dirs["release"] / "hw1" / "files.json"
        assert manifest_path.exists()
        manifest = json.loads(manifest_path.read_text())
        assert isinstance(manifest, dict)
        assert "files" in manifest
        assert ".hidden" not in manifest["files"]
        assert "files.json" not in manifest["files"]
        assert "hw1.py" in manifest["files"]
        assert "data.csv" in manifest["files"]

    def test_publish_triggers_warm_cache(self, hub_dirs):
        """Publish calls warm_notebook_cache for the assignment notebook."""
        import io

        from mograder.core.auth import INSTRUCTOR_USER, make_token

        secret = "test-secret"
        app = create_hub_app(
            hub_dirs["course_dir"],
            dev=False,
            notebooks_dir=hub_dirs["notebooks"],
            release_dir=hub_dirs["release"],
            secret=secret,
        )
        token = make_token(secret, INSTRUCTOR_USER)
        client = TestClient(app, raise_server_exceptions=False)

        nb_content = '# /// script\n# dependencies = ["numpy"]\n# ///\nimport numpy\n'
        with patch("mograder.hub.spawner.warm_notebook_cache") as mock_warm:
            resp = client.post(
                "/publish/hw1",
                headers={"Authorization": f"Bearer {token}"},
                files={
                    "files": (
                        "hw1.py",
                        io.BytesIO(nb_content.encode()),
                        "text/x-python",
                    )
                },
            )
        assert resp.status_code == 200
        mock_warm.assert_called_once()
        call_path = mock_warm.call_args[0][0]
        assert call_path.name == "hw1.py"

    def test_publish_lecture_sets_type(self, hub_dirs):
        """Publish with ?type=lecture stores type in manifest."""
        import io

        from mograder.core.auth import INSTRUCTOR_USER, make_token

        secret = "test-secret"
        app = create_hub_app(
            hub_dirs["course_dir"],
            dev=False,
            notebooks_dir=hub_dirs["notebooks"],
            release_dir=hub_dirs["release"],
            secret=secret,
        )
        token = make_token(secret, INSTRUCTOR_USER)
        client = TestClient(app, raise_server_exceptions=False)

        with patch("mograder.hub.spawner.warm_notebook_cache"):
            resp = client.post(
                "/publish/L01?type=lecture",
                headers={"Authorization": f"Bearer {token}"},
                files={
                    "files": (
                        "L01.py",
                        io.BytesIO(b"# lecture"),
                        "text/x-python",
                    )
                },
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["type"] == "lecture"

        manifest = json.loads((hub_dirs["release"] / "L01" / "files.json").read_text())
        assert manifest["type"] == "lecture"

    def test_publish_lecture_warms_cache(self, hub_dirs):
        """Publish with ?type=lecture still warms cache (lectures have deps too)."""
        import io

        from mograder.core.auth import INSTRUCTOR_USER, make_token

        secret = "test-secret"
        app = create_hub_app(
            hub_dirs["course_dir"],
            dev=False,
            notebooks_dir=hub_dirs["notebooks"],
            release_dir=hub_dirs["release"],
            secret=secret,
        )
        token = make_token(secret, INSTRUCTOR_USER)
        client = TestClient(app, raise_server_exceptions=False)

        with patch("mograder.hub.spawner.warm_notebook_cache") as mock_warm:
            resp = client.post(
                "/publish/L01?type=lecture",
                headers={"Authorization": f"Bearer {token}"},
                files={
                    "files": (
                        "L01.py",
                        io.BytesIO(b"# lecture"),
                        "text/x-python",
                    )
                },
            )
        assert resp.status_code == 200
        mock_warm.assert_called_once()


class TestListAssignmentsAPI:
    def test_assignments_include_lectures(self, hub_dirs):
        """/assignments returns both assignments and lectures."""
        from mograder.core.auth import make_token

        secret = "test-secret"
        app = create_hub_app(
            hub_dirs["course_dir"],
            dev=False,
            notebooks_dir=hub_dirs["notebooks"],
            release_dir=hub_dirs["release"],
            secret=secret,
        )
        token = make_token(secret, "student1")
        client = TestClient(app, raise_server_exceptions=False)

        # Create an assignment
        (hub_dirs["release"] / "hw1").mkdir()
        (hub_dirs["release"] / "hw1" / "hw1.py").write_text("# hw1")

        # Create a lecture with manifest
        (hub_dirs["release"] / "L01").mkdir()
        (hub_dirs["release"] / "L01" / "L01.py").write_text("# lecture")
        (hub_dirs["release"] / "L01" / "files.json").write_text(
            json.dumps({"files": ["L01.py"], "type": "lecture"})
        )

        resp = client.get(
            "/assignments",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        names = {item["name"]: item["type"] for item in data}
        assert names["hw1"] == "assignment"
        assert names["L01"] == "lecture"


class TestWarmCacheAPI:
    def test_warm_cache_requires_instructor(self, hub_dirs):
        """Non-instructor cannot call /warm-cache."""
        from mograder.core.auth import make_token

        secret = "test-secret"
        app = create_hub_app(
            hub_dirs["course_dir"],
            dev=False,
            notebooks_dir=hub_dirs["notebooks"],
            release_dir=hub_dirs["release"],
            secret=secret,
        )
        token = make_token(secret, "student1")
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post(
            "/warm-cache",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 403

    def test_warm_cache_calls_warm_logic(self, hub_dirs):
        """POST /warm-cache invokes warm_notebook_cache for each release notebook."""
        from mograder.core.auth import INSTRUCTOR_USER, make_token

        secret = "test-secret"
        app = create_hub_app(
            hub_dirs["course_dir"],
            dev=False,
            notebooks_dir=hub_dirs["notebooks"],
            release_dir=hub_dirs["release"],
            secret=secret,
        )
        # Create release notebooks
        for name in ["hw1", "hw2"]:
            d = hub_dirs["release"] / name
            d.mkdir(parents=True, exist_ok=True)
            (d / f"{name}.py").write_text(
                '# /// script\n# dependencies = ["numpy"]\n# ///\nimport numpy\n'
            )

        token = make_token(secret, INSTRUCTOR_USER)
        client = TestClient(app, raise_server_exceptions=False)

        with patch("mograder.hub.spawner.warm_notebook_cache") as mock_warm:
            resp = client.post(
                "/warm-cache",
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert len(data["warmed"]) == 2
        assert mock_warm.call_count == 2

    def test_warm_cache_empty_release(self, hub_dirs):
        """POST /warm-cache with no releases returns empty warmed list."""
        from mograder.core.auth import INSTRUCTOR_USER, make_token

        secret = "test-secret"
        app = create_hub_app(
            hub_dirs["course_dir"],
            dev=False,
            notebooks_dir=hub_dirs["notebooks"],
            release_dir=hub_dirs["release"],
            secret=secret,
        )
        token = make_token(secret, INSTRUCTOR_USER)
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post(
            "/warm-cache",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["warmed"] == []


class TestMarkExported:
    def test_mark_exported(self, client, hub_dirs):
        """mark-exported sets marker."""
        _setup_student_file(hub_dirs, "dev-user", "hw1")
        resp = client.post("/mark-exported/dev-user/hw1")
        assert resp.status_code == 200
        marker = hub_dirs["notebooks"] / "dev-user" / "hw1" / ".exported"
        assert marker.exists()


class TestStartEdit:
    def test_start_edit_spawns_session(self, app, client, hub_dirs):
        """POST /start-edit returns url and port when notebook exists."""
        _setup_student_file(hub_dirs, "dev-user", "hw1")

        # Mock the session manager's get_or_spawn to avoid spawning a real process
        from mograder.hub.models import MarimoSession

        mock_session = MarimoSession(
            username="dev-user",
            assignment="hw1",
            port=18001,
            process=None,
            notebook_path=str(hub_dirs["notebooks"] / "dev-user" / "hw1" / "hw1.py"),
        )

        # Patch the session_mgr on the app
        async def mock_get_or_spawn(username, assignment):
            return mock_session

        # Access session_mgr via app.state
        app.state.session_mgr.get_or_spawn = mock_get_or_spawn

        resp = client.post("/start-edit/dev-user/hw1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["url"] == "edit/user/dev-user/hw1/"
        assert data["port"] == 18001

    def test_start_edit_no_notebook_404(self, client, hub_dirs):
        """POST /start-edit for non-existent notebook returns 404."""
        resp = client.post("/start-edit/dev-user/nonexistent")
        assert resp.status_code == 404

    def test_start_edit_user_isolation(self, hub_dirs):
        """User A can't start user B's session."""
        from mograder.core.auth import make_token

        secret = "test-secret"
        app = create_hub_app(
            hub_dirs["course_dir"],
            dev=False,
            notebooks_dir=hub_dirs["notebooks"],
            release_dir=hub_dirs["release"],
            secret=secret,
        )
        _setup_student_file(hub_dirs, "alice", "hw1")

        # Bob tries to start Alice's session
        token = make_token(secret, "bob")
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post(
            "/start-edit/alice/hw1",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 403


class TestStopEdit:
    def test_stop_edit_terminates(self, app, client, hub_dirs):
        """POST /stop-edit terminates an active session."""
        from mograder.hub.models import MarimoSession

        mock_session = MarimoSession(
            username="dev-user",
            assignment="hw1",
            port=18001,
            process=None,
            notebook_path=str(hub_dirs["notebooks"] / "dev-user" / "hw1" / "hw1.py"),
        )
        app.state.session_mgr.sessions[("dev-user", "hw1")] = mock_session

        resp = client.post("/stop-edit/dev-user/hw1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["terminated"] is True

    def test_stop_edit_no_session(self, client, hub_dirs):
        """POST /stop-edit with no session returns terminated=False."""
        resp = client.post("/stop-edit/dev-user/hw1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["terminated"] is False


class TestListAssignments:
    def test_list_assignments(self, client, hub_dirs):
        """GET /assignments returns list with status fields."""
        _setup_release(hub_dirs, "hw1", "# release version")
        _setup_student_file(hub_dirs, "dev-user", "hw1")

        resp = client.get("/assignments")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["name"] == "hw1"
        assert "file_status" in data[0]
        assert "has_release" in data[0]
        assert "session_active" in data[0]

    def test_list_assignments_empty(self, client, hub_dirs):
        """GET /assignments with no releases returns empty list."""
        resp = client.get("/assignments")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_list_assignments_requires_auth(self, hub_dirs):
        """GET /assignments without auth returns 403."""
        app = create_hub_app(
            hub_dirs["course_dir"],
            dev=False,
            notebooks_dir=hub_dirs["notebooks"],
            release_dir=hub_dirs["release"],
            secret="test-secret",
        )
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/assignments")
        assert resp.status_code == 403


class TestDashboardMount:
    def test_dashboard_mounted_at_root(self, client, hub_dirs):
        """GET / returns 200 (HTML page from marimo dashboard)."""
        resp = client.get("/")
        assert resp.status_code == 200
        # Should be HTML content (marimo app)
        ct = resp.headers.get("content-type", "")
        assert "text/html" in ct

    def test_api_routes_take_priority(self, client, hub_dirs):
        """API routes like POST /upload still work with dashboard mounted at /."""
        content = "import numpy as np\nx = np.array([1, 2, 3])\n"
        resp = client.post(
            "/upload/dev-user/hw1",
            files={"file": ("hw1.py", content, "text/x-python")},
        )
        assert resp.status_code == 200


class TestDeepLinkEdit:
    """Tests for /start-edit-deep/{assignment} — auto-download + start-edit."""

    def test_deep_edit_unauthenticated_403(self, hub_dirs):
        """POST /start-edit-deep/hw1 without auth → 403."""
        from mograder.core.auth import make_token

        secret = "test-secret"
        app = create_hub_app(
            hub_dirs["course_dir"],
            dev=False,
            notebooks_dir=hub_dirs["notebooks"],
            release_dir=hub_dirs["release"],
            secret=secret,
        )
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post("/start-edit-deep/hw1")
        assert resp.status_code == 403

    def test_deep_edit_no_release_404(self, client, hub_dirs):
        """POST /start-edit-deep/nonexistent → 404."""
        resp = client.post("/start-edit-deep/nonexistent")
        assert resp.status_code == 404

    def test_deep_edit_downloads_release(self, app, client, hub_dirs):
        """POST /start-edit-deep/hw1 creates student copy from release."""
        _setup_release(hub_dirs, "hw1", "# release version")

        from mograder.hub.models import MarimoSession

        mock_session = MarimoSession(
            username="dev-user",
            assignment="hw1",
            port=18001,
            process=None,
            notebook_path=str(hub_dirs["notebooks"] / "dev-user" / "hw1" / "hw1.py"),
        )

        async def mock_get_or_spawn(username, assignment):
            return mock_session

        app.state.session_mgr.get_or_spawn = mock_get_or_spawn

        resp = client.post("/start-edit-deep/hw1")
        assert resp.status_code == 200

        # Check student file was created from release
        nb = hub_dirs["notebooks"] / "dev-user" / "hw1" / "hw1.py"
        assert nb.exists()
        assert nb.read_text() == "# release version"

    def test_deep_edit_preserves_student_edits(self, app, client, hub_dirs):
        """POST /start-edit-deep/hw1 when student copy exists → file unchanged."""
        _setup_release(hub_dirs, "hw1", "# release version")
        _setup_student_file(hub_dirs, "dev-user", "hw1", "# my edits")

        from mograder.hub.models import MarimoSession

        mock_session = MarimoSession(
            username="dev-user",
            assignment="hw1",
            port=18001,
            process=None,
            notebook_path=str(hub_dirs["notebooks"] / "dev-user" / "hw1" / "hw1.py"),
        )

        async def mock_get_or_spawn(username, assignment):
            return mock_session

        app.state.session_mgr.get_or_spawn = mock_get_or_spawn

        resp = client.post("/start-edit-deep/hw1")
        assert resp.status_code == 200

        # Verify student file unchanged
        nb = hub_dirs["notebooks"] / "dev-user" / "hw1" / "hw1.py"
        assert nb.read_text() == "# my edits"

    def test_deep_edit_returns_url(self, app, client, hub_dirs):
        """POST /start-edit-deep/hw1 returns per-user edit URL."""
        _setup_release(hub_dirs, "hw1")

        from mograder.hub.models import MarimoSession

        mock_session = MarimoSession(
            username="dev-user",
            assignment="hw1",
            port=18001,
            process=None,
            notebook_path=str(hub_dirs["notebooks"] / "dev-user" / "hw1" / "hw1.py"),
        )

        async def mock_get_or_spawn(username, assignment):
            return mock_session

        app.state.session_mgr.get_or_spawn = mock_get_or_spawn

        resp = client.post("/start-edit-deep/hw1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["url"] == "edit/user/dev-user/hw1/"

    def test_publish_rejects_name_user(self, hub_dirs):
        """Publish with assignment name 'user' → 400."""
        import io

        from mograder.core.auth import INSTRUCTOR_USER, make_token

        secret = "test-secret"
        app = create_hub_app(
            hub_dirs["course_dir"],
            dev=False,
            notebooks_dir=hub_dirs["notebooks"],
            release_dir=hub_dirs["release"],
            secret=secret,
        )
        token = make_token(secret, INSTRUCTOR_USER)
        client = TestClient(app, raise_server_exceptions=False)

        with patch("mograder.hub.spawner.warm_notebook_cache"):
            resp = client.post(
                "/publish/user",
                headers={"Authorization": f"Bearer {token}"},
                files={
                    "files": (
                        "user.py",
                        io.BytesIO(b"# bad name"),
                        "text/x-python",
                    )
                },
            )
        assert resp.status_code == 400
