"""Tests for mograder.remote — stdlib-only client helpers."""

import json

import pytest

from mograder.transport.https_server import run_server_background
from mograder.remote import fetch, status, submit


@pytest.fixture()
def server(tmp_path):
    """Start a server with a test assignment directory."""
    hw1_dir = tmp_path / "hw1" / "files"
    hw1_dir.mkdir(parents=True)
    (hw1_dir / "homework.py").write_text("# HW1 starter code")

    srv, thread = run_server_background(tmp_path, port=0)
    port = srv.server_address[1]
    yield f"http://127.0.0.1:{port}", tmp_path, srv
    srv.shutdown()


class TestFetch:
    def test_fetch_downloads_files(self, server, tmp_path):
        base_url, _, _ = server
        dest = tmp_path / "dl"
        result = fetch(base_url, "hw1", str(dest))
        assert len(result) == 1
        assert result[0].name == "homework.py"
        assert result[0].read_text() == "# HW1 starter code"

    def test_fetch_unknown_assignment(self, server, tmp_path):
        base_url, _, _ = server
        with pytest.raises(ValueError, match="not found"):
            fetch(base_url, "nope", str(tmp_path / "dl"))


class TestSubmit:
    def test_submit_file(self, server, tmp_path):
        base_url, root, _ = server
        f = tmp_path / "solution.py"
        f.write_text("print('hi')")
        result = submit(base_url, "hw1", str(f), "alice")
        assert result == "ok"
        # submitted_dir defaults to root; symlink created there
        assert (root / "hw1" / "alice.py").exists()
        assert (root / "hw1" / "alice.py").read_text() == "print('hi')"

    def test_submit_missing_file(self, server, tmp_path):
        base_url, _, _ = server
        with pytest.raises(FileNotFoundError):
            submit(base_url, "hw1", str(tmp_path / "nope.py"), "alice")


class TestStatus:
    def test_status_new(self, server):
        base_url, _, _ = server
        s = status(base_url, "hw1", "alice")
        assert s["status"] == "new"
        assert s["graded"] is False

    def test_status_submitted(self, server):
        import os

        base_url, root, _ = server
        sub_dir = root / "hw1"
        sub_dir.mkdir(parents=True, exist_ok=True)
        (sub_dir / "alice_20260310T200800.py").write_text("code")
        os.symlink("alice_20260310T200800.py", sub_dir / "alice.py")

        s = status(base_url, "hw1", "alice")
        assert s["status"] == "submitted"

    def test_status_graded(self, server):
        import os

        base_url, root, _ = server
        sub_dir = root / "hw1"
        sub_dir.mkdir(parents=True, exist_ok=True)
        (sub_dir / "alice_20260310T200800.py").write_text("code")
        os.symlink("alice_20260310T200800.py", sub_dir / "alice.py")
        (root / "hw1" / "grades.json").write_text(
            json.dumps([{"username": "alice", "grade": "90", "feedback": "Great!"}])
        )

        s = status(base_url, "hw1", "alice")
        assert s["status"] == "submitted"
        assert s["graded"] is True
        assert s["grade"] == "90"
        assert s["feedback"] == "Great!"
