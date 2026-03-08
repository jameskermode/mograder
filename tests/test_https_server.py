"""Tests for mograder.https_server — assignment HTTP server."""

import json

import pytest
import requests

from mograder.https_server import run_server_background


@pytest.fixture()
def server(tmp_path):
    """Start a server with a test assignment directory."""
    # Set up directory structure
    hw1_dir = tmp_path / "hw1" / "files"
    hw1_dir.mkdir(parents=True)
    (hw1_dir / "homework.py").write_text("# HW1 starter code")
    (hw1_dir / "data.csv").write_text("a,b\n1,2\n")

    srv, thread = run_server_background(tmp_path, port=0)
    port = srv.server_address[1]
    yield f"http://127.0.0.1:{port}", tmp_path, srv
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
        assert (tmp_path / "hw1" / "submissions" / "alice.py").exists()

    def test_submit_missing_user(self, server):
        base_url, _, _ = server
        resp = requests.post(
            f"{base_url}/assignments/hw1/submit",
            files={"file": ("solution.py", b"code")},
        )
        assert resp.status_code == 400


class TestListSubmissions:
    def test_list_empty(self, server):
        base_url, _, _ = server
        resp = requests.get(f"{base_url}/assignments/hw1/submissions")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_list_after_submit(self, server):
        base_url, tmp_path, _ = server
        sub_dir = tmp_path / "hw1" / "submissions"
        sub_dir.mkdir(parents=True)
        (sub_dir / "alice.py").write_text("print('hi')")

        resp = requests.get(f"{base_url}/assignments/hw1/submissions")
        data = resp.json()
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
        sub_dir = tmp_path / "hw1" / "submissions"
        sub_dir.mkdir(parents=True)
        (sub_dir / "alice.py").write_text("code")

        resp = requests.get(f"{base_url}/assignments/hw1/status?user=alice")
        data = resp.json()
        assert data["status"] == "submitted"

    def test_status_graded(self, server):
        base_url, tmp_path, _ = server
        sub_dir = tmp_path / "hw1" / "submissions"
        sub_dir.mkdir(parents=True)
        (sub_dir / "alice.py").write_text("code")
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
