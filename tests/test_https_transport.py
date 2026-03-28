"""Tests for HTTPSTransport against a localhost server."""

import pytest

from mograder.core.auth import INSTRUCTOR_USER, generate_secret, make_token
from mograder.transport.https_server import run_server_background
from mograder.transport.https_transport import HTTPSTransport
from mograder.core.models import RemoteAssignment, RemoteStatus, RemoteSubmission


@pytest.fixture()
def transport_server(tmp_path):
    """Start server + create transport (no auth)."""
    hw1_dir = tmp_path / "hw1" / "files"
    hw1_dir.mkdir(parents=True)
    (hw1_dir / "homework.py").write_text("# starter code")

    srv, thread = run_server_background(tmp_path, port=0)
    port = srv.server_address[1]
    base_url = f"http://127.0.0.1:{port}"
    transport = HTTPSTransport(base_url, user="alice")
    yield transport, tmp_path
    srv.shutdown()


@pytest.fixture()
def auth_transport_server(tmp_path):
    """Start server with auth + create transport with valid token."""
    hw1_dir = tmp_path / "hw1" / "files"
    hw1_dir.mkdir(parents=True)
    (hw1_dir / "homework.py").write_text("# starter code")

    secret = generate_secret()
    srv, thread = run_server_background(tmp_path, port=0, secret=secret)
    port = srv.server_address[1]
    base_url = f"http://127.0.0.1:{port}"

    student_token = make_token(secret, "alice")
    instructor_token = make_token(secret, INSTRUCTOR_USER)

    student_transport = HTTPSTransport(base_url, user="alice", token=student_token)
    instructor_transport = HTTPSTransport(
        base_url, user=INSTRUCTOR_USER, token=instructor_token
    )
    yield student_transport, instructor_transport, tmp_path, secret
    srv.shutdown()


class TestHTTPSTransportListAssignments:
    def test_list_returns_remote_assignments(self, transport_server):
        transport, _ = transport_server
        assignments = transport.list_assignments()
        assert len(assignments) == 1
        assert isinstance(assignments[0], RemoteAssignment)
        assert assignments[0].name == "hw1"
        assert len(assignments[0].files) == 1


class TestHTTPSTransportDownload:
    def test_download_file(self, transport_server, tmp_path):
        transport, _ = transport_server
        assignments = transport.list_assignments()
        url = assignments[0].files[0]["url"]
        dest = tmp_path / "output" / "homework.py"
        transport.download_file(url, dest)
        assert dest.exists()
        assert "starter code" in dest.read_text()


class TestHTTPSTransportSubmit:
    def test_submit_file(self, transport_server, tmp_path):
        transport, server_root = transport_server
        nb = tmp_path / "solution.py"
        nb.write_text("print('answer')")
        transport.submit_file("hw1", nb)
        # submitted_dir defaults to root; symlink created there
        assert (server_root / "hw1" / "alice.py").exists()


class TestHTTPSTransportGetSubmissions:
    def test_get_submissions(self, transport_server):
        transport, server_root = transport_server
        # Create a symlink-style submission in submitted_dir (defaults to root)
        sub_dir = server_root / "hw1"
        sub_dir.mkdir(parents=True, exist_ok=True)
        import os

        (sub_dir / "bob_20260310T195000.py").write_text("code")
        os.symlink("bob_20260310T195000.py", sub_dir / "bob.py")

        subs = transport.get_submissions("hw1")
        assert len(subs) == 1
        assert isinstance(subs[0], RemoteSubmission)
        assert subs[0].username == "bob"


class TestHTTPSTransportUploadGrades:
    def test_upload_grades(self, transport_server):
        transport, server_root = transport_server
        (server_root / "hw1").mkdir(exist_ok=True)
        grades = [{"username": "alice", "grade": 95, "feedback": "Excellent"}]
        transport.upload_grades("hw1", grades)
        assert (server_root / "hw1" / "grades.json").exists()


class TestHTTPSTransportGetStatus:
    def test_status_new(self, transport_server):
        transport, _ = transport_server
        status = transport.get_status("hw1")
        assert isinstance(status, RemoteStatus)
        assert status.status == "new"

    def test_status_after_submit(self, transport_server, tmp_path):
        transport, _ = transport_server
        nb = tmp_path / "solution.py"
        nb.write_text("print('answer')")
        transport.submit_file("hw1", nb)
        status = transport.get_status("hw1")
        assert status.status == "submitted"


class TestHTTPSTransportAuth:
    """Test that the transport sends Authorization headers correctly."""

    def test_student_can_list_with_token(self, auth_transport_server):
        student, _, _, _ = auth_transport_server
        assignments = student.list_assignments()
        assert len(assignments) == 1

    def test_student_can_submit_with_token(self, auth_transport_server, tmp_path):
        student, _, server_root, _ = auth_transport_server
        nb = tmp_path / "solution.py"
        nb.write_text("print('answer')")
        student.submit_file("hw1", nb)
        assert (server_root / "hw1" / "alice.py").exists()

    def test_student_can_get_status_with_token(self, auth_transport_server):
        student, _, _, _ = auth_transport_server
        status = student.get_status("hw1")
        assert status.status == "new"

    def test_instructor_can_list_submissions(self, auth_transport_server):
        import os

        _, instructor, server_root, _ = auth_transport_server
        sub_dir = server_root / "hw1"
        sub_dir.mkdir(parents=True, exist_ok=True)
        (sub_dir / "bob_20260310T195000.py").write_text("code")
        os.symlink("bob_20260310T195000.py", sub_dir / "bob.py")
        subs = instructor.get_submissions("hw1")
        assert len(subs) == 1

    def test_instructor_can_upload_grades(self, auth_transport_server):
        _, instructor, server_root, _ = auth_transport_server
        (server_root / "hw1").mkdir(exist_ok=True)
        grades = [{"username": "alice", "grade": 95}]
        instructor.upload_grades("hw1", grades)
        assert (server_root / "hw1" / "grades.json").exists()

    def test_no_token_gets_401(self, auth_transport_server):
        student, _, _, _ = auth_transport_server
        # Create a transport without a token
        no_auth = HTTPSTransport(student.base_url, user="alice")
        with pytest.raises(Exception):
            no_auth.list_assignments()

    def test_headers_method(self):
        t = HTTPSTransport("http://example.com", token="user:abc123")
        assert t._headers() == {"Authorization": "Bearer user:abc123"}

    def test_headers_empty_when_no_token(self):
        t = HTTPSTransport("http://example.com")
        assert t._headers() == {}


@pytest.fixture()
def release_transport_server(tmp_path):
    """Start server with release_dir (flat layout) + create transport."""
    root = tmp_path / "root"
    root.mkdir()
    release = tmp_path / "release"
    hw1_release = release / "hw1"
    hw1_release.mkdir(parents=True)
    (hw1_release / "homework.py").write_text("# flat starter code")

    submitted = tmp_path / "submitted"
    grades = tmp_path / "grades"

    srv, thread = run_server_background(
        root, port=0, release_dir=release, submitted_dir=submitted, grades_dir=grades
    )
    port = srv.server_address[1]
    base_url = f"http://127.0.0.1:{port}"
    transport = HTTPSTransport(base_url, user="alice")
    yield transport, tmp_path, grades
    srv.shutdown()


class TestHTTPSTransportReleaseDir:
    def test_list_returns_flat_assignments(self, release_transport_server):
        transport, _, _ = release_transport_server
        assignments = transport.list_assignments()
        assert len(assignments) == 1
        assert assignments[0].name == "hw1"

    def test_download_flat_file(self, release_transport_server, tmp_path):
        transport, _, _ = release_transport_server
        assignments = transport.list_assignments()
        url = assignments[0].files[0]["url"]
        dest = tmp_path / "output" / "homework.py"
        transport.download_file(url, dest)
        assert dest.exists()
        assert "flat starter code" in dest.read_text()

    def test_grades_in_separate_dir(self, release_transport_server):
        transport, _, grades_dir = release_transport_server
        # Upload via transport would need instructor token, test via direct HTTP
        import requests

        assignments = transport.list_assignments()
        assert len(assignments) == 1
        grades = [{"username": "alice", "grade": 95}]
        resp = requests.post(
            f"{transport.base_url}/assignments/hw1/grades",
            json={"grades": grades},
        )
        assert resp.status_code == 200
        assert (grades_dir / "hw1" / "grades.json").exists()
