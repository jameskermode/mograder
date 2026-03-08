"""Tests for HTTPSTransport against a localhost server."""

import pytest

from mograder.https_server import run_server_background
from mograder.https_transport import HTTPSTransport
from mograder.models import RemoteAssignment, RemoteStatus, RemoteSubmission


@pytest.fixture()
def transport_server(tmp_path):
    """Start server + create transport."""
    hw1_dir = tmp_path / "hw1" / "files"
    hw1_dir.mkdir(parents=True)
    (hw1_dir / "homework.py").write_text("# starter code")

    srv, thread = run_server_background(tmp_path, port=0)
    port = srv.server_address[1]
    base_url = f"http://127.0.0.1:{port}"
    transport = HTTPSTransport(base_url, user="alice")
    yield transport, tmp_path
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
        assert (server_root / "hw1" / "submissions" / "alice.py").exists()


class TestHTTPSTransportGetSubmissions:
    def test_get_submissions(self, transport_server):
        transport, server_root = transport_server
        sub_dir = server_root / "hw1" / "submissions"
        sub_dir.mkdir(parents=True)
        (sub_dir / "bob.py").write_text("code")

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
