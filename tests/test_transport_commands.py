"""Tests for shared transport command logic (do_fetch, do_submit, etc.)."""

from pathlib import Path
from unittest.mock import MagicMock

import click
import pytest

from mograder.models import RemoteAssignment, RemoteStatus, RemoteSubmission
from mograder.transport_commands import (
    do_fetch,
    do_fetch_submissions,
    do_status,
    do_submit,
    do_upload_feedback,
)


def _mock_transport():
    transport = MagicMock()
    transport.list_assignments.return_value = [
        RemoteAssignment(
            name="HW1",
            id="10",
            files=[{"filename": "hw1.py", "url": "http://example.com/hw1.py"}],
            duedate=1700000000,
        ),
    ]
    transport.download_file.side_effect = lambda url, dest: (
        dest.write_bytes(b"content") or dest
    )
    transport.get_submissions.return_value = [
        RemoteSubmission(
            userid="100",
            username="alice",
            filename="sol.py",
            url="http://example.com/sol.py",
        )
    ]
    transport.get_status.return_value = RemoteStatus(
        status="submitted", graded=True, grade="90", feedback="Good"
    )
    return transport


class TestDoFetch:
    def test_list_only(self, capsys):
        transport = _mock_transport()
        do_fetch(transport, None, Path("."), list_only=True)
        captured = capsys.readouterr()
        assert "HW1" in captured.out

    def test_fetch_downloads_files(self, tmp_path, capsys):
        transport = _mock_transport()
        do_fetch(transport, "HW1", tmp_path)
        assert (tmp_path / "hw1.py").exists()
        captured = capsys.readouterr()
        assert "Fetched 1 file(s)" in captured.out

    def test_fetch_no_assignment_errors(self, tmp_path):
        transport = _mock_transport()
        with pytest.raises(click.UsageError, match="Provide an assignment"):
            do_fetch(transport, None, tmp_path)


class TestDoSubmit:
    def test_submit(self, tmp_path, capsys):
        transport = _mock_transport()
        nb = tmp_path / "sol.py"
        nb.write_text("code")
        do_submit(transport, nb, "HW1")
        transport.submit_file.assert_called_once_with("HW1", nb)
        captured = capsys.readouterr()
        assert "Submitted" in captured.out

    def test_submit_dry_run(self, tmp_path, capsys):
        transport = _mock_transport()
        nb = tmp_path / "sol.py"
        nb.write_text("code")
        do_submit(transport, nb, "HW1", dry_run=True)
        transport.submit_file.assert_not_called()
        captured = capsys.readouterr()
        assert "Would submit" in captured.out

    def test_submit_rejects_non_py(self, tmp_path):
        transport = _mock_transport()
        nb = tmp_path / "sol.ipynb"
        nb.write_text("{}")
        with pytest.raises(click.UsageError, match="Only .py"):
            do_submit(transport, nb, "HW1")


class TestDoFetchSubmissions:
    def test_fetches_submissions(self, tmp_path, capsys):
        transport = _mock_transport()
        do_fetch_submissions(transport, "HW1", tmp_path)
        assert (tmp_path / "alice.py").exists()
        captured = capsys.readouterr()
        assert "Downloaded 1" in captured.out


class TestDoUploadFeedback:
    def test_upload(self, capsys):
        transport = _mock_transport()
        grades = [{"username": "alice", "grade": 85}]
        do_upload_feedback(transport, "HW1", grades)
        transport.upload_grades.assert_called_once()
        captured = capsys.readouterr()
        assert "Uploaded 1" in captured.out

    def test_dry_run(self, capsys):
        transport = _mock_transport()
        grades = [{"username": "alice", "grade": 85}]
        do_upload_feedback(transport, "HW1", grades, dry_run=True)
        transport.upload_grades.assert_not_called()
        captured = capsys.readouterr()
        assert "Would upload" in captured.out

    def test_empty_grades(self, capsys):
        transport = _mock_transport()
        do_upload_feedback(transport, "HW1", [])
        captured = capsys.readouterr()
        assert "No grades" in captured.out


class TestDoStatus:
    def test_shows_status(self, capsys):
        transport = _mock_transport()
        do_status(transport, "HW1")
        captured = capsys.readouterr()
        assert "submitted" in captured.out
        assert "90" in captured.out
        assert "Good" in captured.out
