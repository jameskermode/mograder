"""Tests for mograder.transport.https_server — assignment HTTP server."""

import json
import sys

import pytest
import requests

from mograder.core.auth import INSTRUCTOR_USER, generate_secret, make_token
from mograder.transport.https_server import run_server_background


@pytest.fixture()
def server(tmp_path):
    """Start a server with a test assignment directory (no auth)."""
    # Set up directory structure
    hw1_dir = tmp_path / "hw1" / "files"
    hw1_dir.mkdir(parents=True)
    (hw1_dir / "homework.py").write_text("# HW1 starter code")
    (hw1_dir / "data.csv").write_text("a,b\n1,2\n")

    srv, thread = run_server_background(tmp_path, port=0)
    port = srv.server_address[1]
    yield f"http://127.0.0.1:{port}", tmp_path, srv
    srv.shutdown()


@pytest.fixture()
def auth_server(tmp_path):
    """Start a server with authentication enabled."""
    hw1_dir = tmp_path / "hw1" / "files"
    hw1_dir.mkdir(parents=True)
    (hw1_dir / "homework.py").write_text("# HW1 starter code")

    secret = generate_secret()
    srv, thread = run_server_background(tmp_path, port=0, secret=secret)
    port = srv.server_address[1]
    base_url = f"http://127.0.0.1:{port}"
    yield base_url, tmp_path, srv, secret
    srv.shutdown()


class TestListAssignments:
    def test_auto_discover(self, server):
        base_url, _, _ = server
        resp = requests.get(f"{base_url}/assignments")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["name"] == "hw1"
        assert len(data[0]["files"]) == 2

    def test_manifest_file(self, server):
        base_url, tmp_path, _ = server
        manifest = [{"name": "custom", "id": "99", "files": []}]
        (tmp_path / "assignments.json").write_text(json.dumps(manifest))
        resp = requests.get(f"{base_url}/assignments")
        data = resp.json()
        assert len(data) == 1
        assert data[0]["name"] == "custom"


class TestDownloadFile:
    def test_download_existing_file(self, server):
        base_url, _, _ = server
        resp = requests.get(f"{base_url}/assignments/hw1/files/homework.py")
        assert resp.status_code == 200
        assert b"HW1 starter code" in resp.content

    def test_download_missing_file(self, server):
        base_url, _, _ = server
        resp = requests.get(f"{base_url}/assignments/hw1/files/nope.py")
        assert resp.status_code == 404


class TestSubmit:
    def test_submit_file(self, server):
        base_url, tmp_path, _ = server
        resp = requests.post(
            f"{base_url}/assignments/hw1/submit?user=alice",
            files={"file": ("solution.py", b"print('hello')")},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        # Symlink created in submitted_dir (defaults to root)
        symlink = tmp_path / "hw1" / "alice.py"
        assert symlink.exists()
        assert symlink.read_bytes() == b"print('hello')"

    def test_submit_missing_user(self, server):
        base_url, _, _ = server
        resp = requests.post(
            f"{base_url}/assignments/hw1/submit",
            files={"file": ("solution.py", b"code")},
        )
        assert resp.status_code == 400


class TestSubmittedDir:
    def test_submit_writes_timestamped_and_symlink(self, tmp_path):
        """Submitting with submitted_dir creates timestamped file + symlink."""
        root = tmp_path / "root"
        hw1_dir = root / "hw1" / "files"
        hw1_dir.mkdir(parents=True)
        (hw1_dir / "homework.py").write_text("# starter")

        submitted = tmp_path / "submitted"
        srv, thread = run_server_background(root, port=0, submitted_dir=submitted)
        port = srv.server_address[1]
        base_url = f"http://127.0.0.1:{port}"

        try:
            resp = requests.post(
                f"{base_url}/assignments/hw1/submit?user=alice",
                files={"file": ("solution.py", b"print('answer')")},
            )
            assert resp.status_code == 200

            # Symlink (or copy on Windows) exists and resolves to the content
            symlink = submitted / "hw1" / "alice.py"
            assert symlink.exists()
            if sys.platform != "win32":
                assert symlink.is_symlink()
            assert symlink.read_bytes() == b"print('answer')"

            # Timestamped file exists
            timestamped = [
                f
                for f in (submitted / "hw1").iterdir()
                if f.name.startswith("alice_") and f.suffix == ".py"
            ]
            assert len(timestamped) == 1

            # Nothing written to root/<assignment>/submissions/
            assert not (root / "hw1" / "submissions").exists()
        finally:
            srv.shutdown()

    def test_resubmission_preserves_history(self, tmp_path):
        """Resubmitting creates a new timestamped file, updates symlink."""
        import time

        root = tmp_path / "root"
        hw1_dir = root / "hw1" / "files"
        hw1_dir.mkdir(parents=True)
        (hw1_dir / "homework.py").write_text("# starter")

        submitted = tmp_path / "submitted"
        srv, thread = run_server_background(root, port=0, submitted_dir=submitted)
        port = srv.server_address[1]
        base_url = f"http://127.0.0.1:{port}"

        try:
            # First submission
            requests.post(
                f"{base_url}/assignments/hw1/submit?user=alice",
                files={"file": ("solution.py", b"v1")},
            )
            # On Unix, resolve() follows symlink to the timestamped file
            first_target = (submitted / "hw1" / "alice.py").resolve()

            # Wait to ensure different timestamp
            time.sleep(1.1)

            # Second submission
            requests.post(
                f"{base_url}/assignments/hw1/submit?user=alice",
                files={"file": ("solution.py", b"v2")},
            )

            symlink = submitted / "hw1" / "alice.py"
            assert symlink.read_bytes() == b"v2"

            if sys.platform != "win32":
                # On Unix the old timestamped file still exists via symlink resolve
                assert first_target.exists()
                assert first_target.read_bytes() == b"v1"

            # Two timestamped files
            timestamped = [
                f
                for f in (submitted / "hw1").iterdir()
                if f.name.startswith("alice_") and f.suffix == ".py"
            ]
            assert len(timestamped) == 2
        finally:
            srv.shutdown()


class TestListSubmissions:
    def test_list_empty(self, server):
        base_url, _, _ = server
        resp = requests.get(f"{base_url}/assignments/hw1/submissions")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_list_after_submit(self, server):
        base_url, tmp_path, _ = server
        # Submit a file so timestamped + symlink are created
        requests.post(
            f"{base_url}/assignments/hw1/submit?user=alice",
            files={"file": ("solution.py", b"print('hi')")},
        )

        resp = requests.get(f"{base_url}/assignments/hw1/submissions")
        data = resp.json()
        # Should list only the symlink, not the timestamped file
        assert len(data) == 1
        assert data[0]["username"] == "alice"


class TestUploadGrades:
    def test_upload_grades(self, server):
        base_url, tmp_path, _ = server
        (tmp_path / "hw1").mkdir(exist_ok=True)
        grades = [
            {"username": "alice", "grade": 85, "feedback": "Good work"},
        ]
        resp = requests.post(
            f"{base_url}/assignments/hw1/grades",
            json={"grades": grades},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"

        grades_file = tmp_path / "hw1" / "grades.json"
        assert grades_file.exists()
        saved = json.loads(grades_file.read_text())
        assert len(saved) == 1
        assert saved[0]["grade"] == 85


class TestStatus:
    def test_status_new(self, server):
        base_url, _, _ = server
        resp = requests.get(f"{base_url}/assignments/hw1/status?user=alice")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "new"
        assert data["graded"] is False

    def test_status_submitted(self, server):
        base_url, tmp_path, _ = server
        # Submit via the API so symlink is created
        requests.post(
            f"{base_url}/assignments/hw1/submit?user=alice",
            files={"file": ("solution.py", b"code")},
        )

        resp = requests.get(f"{base_url}/assignments/hw1/status?user=alice")
        data = resp.json()
        assert data["status"] == "submitted"

    def test_status_graded(self, server):
        base_url, tmp_path, _ = server
        # Submit via the API
        requests.post(
            f"{base_url}/assignments/hw1/submit?user=alice",
            files={"file": ("solution.py", b"code")},
        )
        grades_path = tmp_path / "hw1" / "grades.json"
        grades_path.write_text(
            json.dumps([{"username": "alice", "grade": "90", "feedback": "Great!"}])
        )

        resp = requests.get(f"{base_url}/assignments/hw1/status?user=alice")
        data = resp.json()
        assert data["status"] == "submitted"
        assert data["graded"] is True
        assert data["grade"] == "90"
        assert data["feedback"] == "Great!"

    def test_status_missing_user(self, server):
        base_url, _, _ = server
        resp = requests.get(f"{base_url}/assignments/hw1/status")
        assert resp.status_code == 400


class TestCORS:
    def test_cors_headers_on_get(self, server):
        base_url, _, _ = server
        resp = requests.get(f"{base_url}/assignments")
        assert resp.headers.get("Access-Control-Allow-Origin") == "*"

    def test_cors_headers_on_file(self, server):
        base_url, _, _ = server
        resp = requests.get(f"{base_url}/assignments/hw1/files/homework.py")
        assert resp.headers.get("Access-Control-Allow-Origin") == "*"

    def test_options_preflight(self, server):
        base_url, _, _ = server
        resp = requests.options(f"{base_url}/assignments")
        assert resp.status_code == 204
        assert resp.headers.get("Access-Control-Allow-Origin") == "*"
        assert "POST" in resp.headers.get("Access-Control-Allow-Methods", "")


class TestHealthCheck:
    def test_root_returns_ok(self, server):
        base_url, _, _ = server
        resp = requests.get(f"{base_url}/")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_root_no_trailing_slash(self, server):
        base_url, _, _ = server
        # requests normalizes, so test the raw path
        resp = requests.get(base_url)
        assert resp.status_code == 200


# --- Authentication tests ---


class TestAuthRequired:
    """Test that endpoints reject unauthenticated requests when auth is enabled."""

    def test_list_assignments_requires_auth(self, auth_server):
        base_url, _, _, _ = auth_server
        resp = requests.get(f"{base_url}/assignments")
        assert resp.status_code == 401

    def test_download_file_requires_auth(self, auth_server):
        base_url, _, _, _ = auth_server
        resp = requests.get(f"{base_url}/assignments/hw1/files/homework.py")
        assert resp.status_code == 401

    def test_submit_requires_auth(self, auth_server):
        base_url, _, _, _ = auth_server
        resp = requests.post(
            f"{base_url}/assignments/hw1/submit?user=alice",
            files={"file": ("solution.py", b"code")},
        )
        assert resp.status_code == 401

    def test_list_submissions_requires_auth(self, auth_server):
        base_url, _, _, _ = auth_server
        resp = requests.get(f"{base_url}/assignments/hw1/submissions")
        assert resp.status_code == 401

    def test_upload_grades_requires_auth(self, auth_server):
        base_url, _, _, _ = auth_server
        resp = requests.post(
            f"{base_url}/assignments/hw1/grades",
            json={"grades": []},
        )
        assert resp.status_code == 401

    def test_status_requires_auth(self, auth_server):
        base_url, _, _, _ = auth_server
        resp = requests.get(f"{base_url}/assignments/hw1/status?user=alice")
        assert resp.status_code == 401

    def test_health_check_no_auth(self, auth_server):
        """Health check endpoint should not require auth."""
        base_url, _, _, _ = auth_server
        resp = requests.get(f"{base_url}/")
        assert resp.status_code == 200


class TestAuthWithToken:
    """Test authenticated requests work correctly."""

    def _headers(self, secret, username):
        token = make_token(secret, username)
        return {"Authorization": f"Bearer {token}"}

    def test_student_can_list_assignments(self, auth_server):
        base_url, _, _, secret = auth_server
        resp = requests.get(
            f"{base_url}/assignments", headers=self._headers(secret, "alice")
        )
        assert resp.status_code == 200

    def test_student_can_download_file(self, auth_server):
        base_url, _, _, secret = auth_server
        resp = requests.get(
            f"{base_url}/assignments/hw1/files/homework.py",
            headers=self._headers(secret, "alice"),
        )
        assert resp.status_code == 200

    def test_student_can_submit_as_self(self, auth_server):
        base_url, _, _, secret = auth_server
        resp = requests.post(
            f"{base_url}/assignments/hw1/submit?user=alice",
            files={"file": ("solution.py", b"code")},
            headers=self._headers(secret, "alice"),
        )
        assert resp.status_code == 200

    def test_student_cannot_submit_as_other(self, auth_server):
        base_url, _, _, secret = auth_server
        resp = requests.post(
            f"{base_url}/assignments/hw1/submit?user=bob",
            files={"file": ("solution.py", b"code")},
            headers=self._headers(secret, "alice"),
        )
        assert resp.status_code == 403

    def test_student_can_check_own_status(self, auth_server):
        base_url, _, _, secret = auth_server
        resp = requests.get(
            f"{base_url}/assignments/hw1/status?user=alice",
            headers=self._headers(secret, "alice"),
        )
        assert resp.status_code == 200

    def test_student_cannot_check_other_status(self, auth_server):
        base_url, _, _, secret = auth_server
        resp = requests.get(
            f"{base_url}/assignments/hw1/status?user=bob",
            headers=self._headers(secret, "alice"),
        )
        assert resp.status_code == 403

    def test_student_cannot_list_submissions(self, auth_server):
        base_url, _, _, secret = auth_server
        resp = requests.get(
            f"{base_url}/assignments/hw1/submissions",
            headers=self._headers(secret, "alice"),
        )
        assert resp.status_code == 403

    def test_student_cannot_upload_grades(self, auth_server):
        base_url, _, _, secret = auth_server
        resp = requests.post(
            f"{base_url}/assignments/hw1/grades",
            json={"grades": []},
            headers=self._headers(secret, "alice"),
        )
        assert resp.status_code == 403


class TestInstructorAuth:
    """Test instructor token grants full access."""

    def _headers(self, secret):
        token = make_token(secret, INSTRUCTOR_USER)
        return {"Authorization": f"Bearer {token}"}

    def test_instructor_can_list_submissions(self, auth_server):
        base_url, _, _, secret = auth_server
        resp = requests.get(
            f"{base_url}/assignments/hw1/submissions",
            headers=self._headers(secret),
        )
        assert resp.status_code == 200

    def test_instructor_can_upload_grades(self, auth_server):
        base_url, tmp_path, _, secret = auth_server
        (tmp_path / "hw1").mkdir(exist_ok=True)
        resp = requests.post(
            f"{base_url}/assignments/hw1/grades",
            json={"grades": [{"username": "alice", "grade": 90}]},
            headers=self._headers(secret),
        )
        assert resp.status_code == 200

    def test_instructor_can_submit_as_any_user(self, auth_server):
        base_url, _, _, secret = auth_server
        resp = requests.post(
            f"{base_url}/assignments/hw1/submit?user=alice",
            files={"file": ("solution.py", b"code")},
            headers=self._headers(secret),
        )
        assert resp.status_code == 200

    def test_instructor_can_check_any_status(self, auth_server):
        base_url, _, _, secret = auth_server
        resp = requests.get(
            f"{base_url}/assignments/hw1/status?user=alice",
            headers=self._headers(secret),
        )
        assert resp.status_code == 200

    def test_instructor_can_download_submission(self, auth_server):
        base_url, tmp_path, _, secret = auth_server
        # Submit via API so symlink is created in submitted_dir (defaults to root)
        resp = requests.post(
            f"{base_url}/assignments/hw1/submit?user=alice",
            files={"file": ("solution.py", b"code")},
            headers=self._headers(secret),
        )
        assert resp.status_code == 200

        resp = requests.get(
            f"{base_url}/assignments/hw1/submissions/alice.py",
            headers=self._headers(secret),
        )
        assert resp.status_code == 200


class TestInvalidToken:
    def test_invalid_token_rejected(self, auth_server):
        base_url, _, _, _ = auth_server
        resp = requests.get(
            f"{base_url}/assignments",
            headers={"Authorization": "Bearer fake:token"},
        )
        assert resp.status_code == 401

    def test_malformed_auth_header(self, auth_server):
        base_url, _, _, _ = auth_server
        resp = requests.get(
            f"{base_url}/assignments",
            headers={"Authorization": "Basic dXNlcjpwYXNz"},
        )
        assert resp.status_code == 401


@pytest.fixture()
def reg_server(tmp_path):
    """Start a server with auth + enrollment code enabled."""
    hw1_dir = tmp_path / "hw1" / "files"
    hw1_dir.mkdir(parents=True)
    (hw1_dir / "homework.py").write_text("# HW1")
    secret = generate_secret()
    enrollment_code = "test-enroll-123"
    srv, thread = run_server_background(
        tmp_path, port=0, secret=secret, enrollment_code=enrollment_code
    )
    port = srv.server_address[1]
    base_url = f"http://127.0.0.1:{port}"
    yield base_url, tmp_path, srv, secret, enrollment_code
    srv.shutdown()


class TestRegistration:
    def test_register_success(self, reg_server):
        from mograder.core.auth import verify_token

        base_url, _, _, secret, enrollment_code = reg_server
        resp = requests.post(
            f"{base_url}/register",
            json={"user": "alice", "enrollment_code": enrollment_code},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["user"] == "alice"
        assert verify_token(secret, data["token"]) == "alice"

    def test_register_token_works_for_list(self, reg_server):
        base_url, _, _, _, enrollment_code = reg_server
        resp = requests.post(
            f"{base_url}/register",
            json={"user": "bob", "enrollment_code": enrollment_code},
        )
        token = resp.json()["token"]
        # Use the token to access a protected endpoint
        resp2 = requests.get(
            f"{base_url}/assignments",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp2.status_code == 200

    def test_register_wrong_code(self, reg_server):
        base_url, _, _, _, _ = reg_server
        resp = requests.post(
            f"{base_url}/register",
            json={"user": "alice", "enrollment_code": "wrong"},
        )
        assert resp.status_code == 403

    def test_register_missing_user(self, reg_server):
        base_url, _, _, _, enrollment_code = reg_server
        resp = requests.post(
            f"{base_url}/register",
            json={"enrollment_code": enrollment_code},
        )
        assert resp.status_code == 400

    def test_register_reserved_username(self, reg_server):
        base_url, _, _, _, enrollment_code = reg_server
        resp = requests.post(
            f"{base_url}/register",
            json={"user": INSTRUCTOR_USER, "enrollment_code": enrollment_code},
        )
        assert resp.status_code == 400

    def test_register_dunder_username(self, reg_server):
        base_url, _, _, _, enrollment_code = reg_server
        resp = requests.post(
            f"{base_url}/register",
            json={"user": "__admin__", "enrollment_code": enrollment_code},
        )
        assert resp.status_code == 400

    def test_register_not_enabled(self, auth_server):
        base_url, _, _, _ = auth_server
        resp = requests.post(
            f"{base_url}/register",
            json={"user": "alice", "enrollment_code": "anything"},
        )
        assert resp.status_code == 403

    def test_register_no_auth_server(self, server):
        base_url, _, _ = server
        resp = requests.post(
            f"{base_url}/register",
            json={"user": "alice", "enrollment_code": "anything"},
        )
        # No enrollment code configured → 403 (not enabled)
        assert resp.status_code in (400, 403, 404)

    def test_registered_token_cannot_access_instructor(self, reg_server):
        base_url, _, _, _, enrollment_code = reg_server
        resp = requests.post(
            f"{base_url}/register",
            json={"user": "student1", "enrollment_code": enrollment_code},
        )
        token = resp.json()["token"]
        # Student cannot list submissions (instructor-only)
        resp2 = requests.get(
            f"{base_url}/assignments/hw1/submissions",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp2.status_code == 403


# --- release_dir tests (flat layout, no files/ subdir) ---


@pytest.fixture()
def release_server(tmp_path):
    """Start a server with release_dir (flat layout) and separate grades_dir."""
    root = tmp_path / "root"
    root.mkdir()
    release = tmp_path / "release"
    hw1_release = release / "hw1"
    hw1_release.mkdir(parents=True)
    (hw1_release / "homework.py").write_text("# HW1 flat layout")
    (hw1_release / "data.csv").write_text("x,y\n3,4\n")

    submitted = tmp_path / "submitted"
    grades = tmp_path / "grades"

    srv, thread = run_server_background(
        root, port=0, release_dir=release, submitted_dir=submitted, grades_dir=grades
    )
    port = srv.server_address[1]
    yield f"http://127.0.0.1:{port}", tmp_path, srv, release, grades
    srv.shutdown()


class TestReleaseDirAutoDiscover:
    def test_auto_discover_flat_layout(self, release_server):
        base_url, _, _, _, _ = release_server
        resp = requests.get(f"{base_url}/assignments")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["name"] == "hw1"
        assert len(data[0]["files"]) == 2
        filenames = {f["filename"] for f in data[0]["files"]}
        assert filenames == {"homework.py", "data.csv"}

    def test_auto_discover_flat_layout_prefers_zip(self, tmp_path):
        """When a .zip is present in release dir, only the zip is listed."""
        root = tmp_path / "root"
        root.mkdir()
        release = tmp_path / "release"
        hw1_release = release / "hw1"
        hw1_release.mkdir(parents=True)
        (hw1_release / "homework.py").write_text("# code")
        (hw1_release / "hw1.zip").write_bytes(b"PK\x03\x04fake")

        srv, thread = run_server_background(root, port=0, release_dir=release)
        port = srv.server_address[1]
        try:
            resp = requests.get(f"http://127.0.0.1:{port}/assignments")
            data = resp.json()
            assert len(data) == 1
            files = data[0]["files"]
            assert len(files) == 1
            assert files[0]["filename"] == "hw1.zip"
        finally:
            srv.shutdown()

    def test_download_from_flat_layout(self, release_server):
        base_url, _, _, _, _ = release_server
        resp = requests.get(f"{base_url}/assignments/hw1/files/homework.py")
        assert resp.status_code == 200
        assert b"HW1 flat layout" in resp.content

    def test_download_missing_from_flat_layout(self, release_server):
        base_url, _, _, _, _ = release_server
        resp = requests.get(f"{base_url}/assignments/hw1/files/nope.py")
        assert resp.status_code == 404


# --- Security tests ---


class TestPathTraversal:
    """Verify path traversal attacks are blocked."""

    def test_download_file_path_traversal(self, server):
        base_url, _, _ = server
        resp = requests.get(f"{base_url}/assignments/hw1/files/../../etc/passwd")
        assert resp.status_code in (403, 404)

    def test_download_file_dotdot_in_assignment(self, server):
        base_url, _, _ = server
        resp = requests.get(f"{base_url}/assignments/../../../etc/passwd/files/x")
        assert resp.status_code in (403, 404)

    def test_download_submission_path_traversal(self, auth_server):
        base_url, _, _, secret = auth_server
        token = make_token(secret, INSTRUCTOR_USER)
        resp = requests.get(
            f"{base_url}/assignments/hw1/submissions/../../etc/passwd",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code in (403, 404)

    def test_download_file_path_traversal_release_dir(self, release_server):
        base_url, _, _, _, _ = release_server
        resp = requests.get(f"{base_url}/assignments/hw1/files/../../etc/passwd")
        assert resp.status_code in (403, 404)


class TestUsernameValidation:
    """Verify malicious usernames are rejected."""

    def test_submit_traversal_username(self, server):
        base_url, _, _ = server
        resp = requests.post(
            f"{base_url}/assignments/hw1/submit?user=../../evil",
            files={"file": ("solution.py", b"code")},
        )
        assert resp.status_code == 400

    def test_submit_slash_username(self, server):
        base_url, _, _ = server
        resp = requests.post(
            f"{base_url}/assignments/hw1/submit?user=a/b",
            files={"file": ("solution.py", b"code")},
        )
        assert resp.status_code == 400

    def test_submit_backslash_username(self, server):
        base_url, _, _ = server
        resp = requests.post(
            f"{base_url}/assignments/hw1/submit?user=a\\b",
            files={"file": ("solution.py", b"code")},
        )
        assert resp.status_code == 400

    def test_register_traversal_username(self, reg_server):
        base_url, _, _, _, enrollment_code = reg_server
        resp = requests.post(
            f"{base_url}/register",
            json={"user": "../../evil", "enrollment_code": enrollment_code},
        )
        assert resp.status_code == 400

    def test_register_slash_username(self, reg_server):
        base_url, _, _, _, enrollment_code = reg_server
        resp = requests.post(
            f"{base_url}/register",
            json={"user": "foo/bar", "enrollment_code": enrollment_code},
        )
        assert resp.status_code == 400

    def test_valid_usernames_accepted(self, server):
        """Usernames with dots, hyphens, underscores should work."""
        base_url, _, _ = server
        for username in ["alice", "bob-smith", "user_1", "first.last"]:
            resp = requests.post(
                f"{base_url}/assignments/hw1/submit?user={username}",
                files={"file": ("solution.py", b"code")},
            )
            assert resp.status_code == 200, f"Failed for username: {username}"


class TestGradesDir:
    def test_upload_grades_to_separate_dir(self, release_server):
        base_url, _, _, _, grades_dir = release_server
        grades = [{"username": "alice", "grade": 88, "feedback": "Nice"}]
        resp = requests.post(
            f"{base_url}/assignments/hw1/grades",
            json={"grades": grades},
        )
        assert resp.status_code == 200
        grades_file = grades_dir / "hw1" / "grades.json"
        assert grades_file.exists()
        saved = json.loads(grades_file.read_text())
        assert saved[0]["grade"] == 88

    def test_status_reads_from_grades_dir(self, release_server):
        base_url, _, _, _, grades_dir = release_server
        # Upload grades first
        grades = [{"username": "alice", "grade": 92, "feedback": "Great!"}]
        requests.post(
            f"{base_url}/assignments/hw1/grades",
            json={"grades": grades},
        )
        resp = requests.get(f"{base_url}/assignments/hw1/status?user=alice")
        data = resp.json()
        assert data["graded"] is True
        assert data["grade"] == "92"

    def test_empty_release_dir_skipped(self, tmp_path):
        """Directories with no files should not appear in assignment list."""
        root = tmp_path / "root"
        root.mkdir()
        release = tmp_path / "release"
        empty_assignment = release / "empty-hw"
        empty_assignment.mkdir(parents=True)
        # Also add a subdirectory (not a file)
        (empty_assignment / "subdir").mkdir()

        srv, thread = run_server_background(root, port=0, release_dir=release)
        port = srv.server_address[1]
        try:
            resp = requests.get(f"http://127.0.0.1:{port}/assignments")
            data = resp.json()
            assert len(data) == 0
        finally:
            srv.shutdown()


class TestFeedbackUpload:
    """Tests for HTML feedback file upload and serving."""

    def test_upload_feedback_files(self, server):
        """POST feedback HTML files → stored on disk."""
        base_url, tmp_path, _ = server
        (tmp_path / "hw1").mkdir(exist_ok=True)
        resp = requests.post(
            f"{base_url}/assignments/hw1/feedback",
            files=[
                ("files", ("alice.html", b"<h1>Feedback for Alice</h1>", "text/html")),
                ("files", ("bob.html", b"<h1>Feedback for Bob</h1>", "text/html")),
            ],
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "alice.html" in data["files"]
        assert "bob.html" in data["files"]

        fb_dir = tmp_path / "hw1" / "feedback"
        assert (fb_dir / "alice.html").read_text() == "<h1>Feedback for Alice</h1>"
        assert (fb_dir / "bob.html").read_text() == "<h1>Feedback for Bob</h1>"

    def test_upload_feedback_requires_instructor(self, auth_server):
        """Non-instructor cannot upload feedback."""
        base_url, tmp_path, _, secret = auth_server
        student_token = make_token(secret, "alice")
        resp = requests.post(
            f"{base_url}/assignments/hw1/feedback",
            headers={"Authorization": f"Bearer {student_token}"},
            files=[("files", ("alice.html", b"<h1>Feedback</h1>", "text/html"))],
        )
        assert resp.status_code == 403

    def test_get_feedback_html(self, server):
        """GET feedback returns HTML for authenticated user."""
        base_url, tmp_path, _ = server
        fb_dir = tmp_path / "hw1" / "feedback"
        fb_dir.mkdir(parents=True)
        (fb_dir / "alice.html").write_text("<h1>Alice's feedback</h1>")

        resp = requests.get(
            f"{base_url}/assignments/hw1/feedback/alice",
        )
        assert resp.status_code == 200
        assert "Alice's feedback" in resp.text

    def test_get_feedback_user_isolation(self, auth_server):
        """User A cannot see user B's feedback."""
        base_url, tmp_path, _, secret = auth_server
        fb_dir = tmp_path / "hw1" / "feedback"
        fb_dir.mkdir(parents=True)
        (fb_dir / "bob.html").write_text("<h1>Bob's feedback</h1>")

        alice_token = make_token(secret, "alice")
        resp = requests.get(
            f"{base_url}/assignments/hw1/feedback/alice",
            headers={"Authorization": f"Bearer {alice_token}"},
        )
        # Alice has no feedback
        assert resp.status_code == 404

        resp = requests.get(
            f"{base_url}/assignments/hw1/feedback/bob",
            headers={"Authorization": f"Bearer {alice_token}"},
        )
        # Alice can't see Bob's feedback
        assert resp.status_code == 403

    def test_get_feedback_404(self, server):
        """No feedback file → 404."""
        base_url, _, _ = server
        resp = requests.get(f"{base_url}/assignments/hw1/feedback/nobody")
        assert resp.status_code == 404

    def test_status_includes_feedback_available(self, server):
        """Status response includes feedback_available field."""
        base_url, tmp_path, _ = server
        # No feedback yet
        resp = requests.get(f"{base_url}/assignments/hw1/status?user=alice")
        data = resp.json()
        assert data.get("feedback_available") is False

        # Add feedback file
        fb_dir = tmp_path / "hw1" / "feedback"
        fb_dir.mkdir(parents=True)
        (fb_dir / "alice.html").write_text("<h1>Feedback</h1>")

        resp = requests.get(f"{base_url}/assignments/hw1/status?user=alice")
        data = resp.json()
        assert data.get("feedback_available") is True
