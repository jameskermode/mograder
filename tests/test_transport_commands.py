"""Tests for shared transport command logic (do_fetch, do_submit, etc.)."""

import zipfile
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

    def test_fetch_caches_release(self, tmp_path, capsys):
        """do_fetch copies .py files to .mograder/release/<assignment>/."""
        transport = _mock_transport()
        do_fetch(transport, "HW1", tmp_path)
        cache = tmp_path / ".mograder" / "release" / "HW1" / "hw1.py"
        assert cache.exists()
        assert cache.read_bytes() == b"content"

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

    def test_skips_unchanged_on_repeat(self, tmp_path, capsys):
        """Second fetch should skip when timemodified hasn't changed."""
        transport = _mock_transport()
        transport.get_submissions.return_value = [
            RemoteSubmission(
                userid="100",
                username="alice",
                filename="sol.py",
                url="http://example.com/sol.py",
                timemodified=1700000000,
            )
        ]
        # First fetch
        do_fetch_submissions(transport, "HW1", tmp_path)
        captured = capsys.readouterr()
        assert "Downloaded 1" in captured.out
        assert transport.download_file.call_count == 1

        # Second fetch — same timemodified
        do_fetch_submissions(transport, "HW1", tmp_path)
        captured = capsys.readouterr()
        assert "skipped 1 unchanged" in captured.out
        assert transport.download_file.call_count == 1  # no new download

    def test_re_fetches_when_timemodified_changes(self, tmp_path, capsys):
        """Should re-download when remote timemodified increases."""
        transport = _mock_transport()
        transport.get_submissions.return_value = [
            RemoteSubmission(
                userid="100",
                username="alice",
                filename="sol.py",
                url="http://example.com/sol.py",
                timemodified=1700000000,
            )
        ]
        do_fetch_submissions(transport, "HW1", tmp_path)
        assert transport.download_file.call_count == 1

        # Simulate updated submission
        transport.get_submissions.return_value = [
            RemoteSubmission(
                userid="100",
                username="alice",
                filename="sol.py",
                url="http://example.com/sol.py",
                timemodified=1700001000,
            )
        ]
        do_fetch_submissions(transport, "HW1", tmp_path)
        captured = capsys.readouterr()
        assert "Downloaded 1" in captured.out
        assert transport.download_file.call_count == 2

    def test_force_re_fetches(self, tmp_path, capsys):
        """--force should re-download even if unchanged."""
        transport = _mock_transport()
        transport.get_submissions.return_value = [
            RemoteSubmission(
                userid="100",
                username="alice",
                filename="sol.py",
                url="http://example.com/sol.py",
                timemodified=1700000000,
            )
        ]
        do_fetch_submissions(transport, "HW1", tmp_path)
        do_fetch_submissions(transport, "HW1", tmp_path, force=True)
        captured = capsys.readouterr()
        assert "Downloaded 1" in captured.out
        assert transport.download_file.call_count == 2

    def test_fetch_submissions_extracts_zip(self, tmp_path, capsys):
        """When a student submits a .zip, extract .py and save as {username}.py."""
        # Build a zip containing a .py file
        zip_bytes = _make_zip({"A1.py": b"# student code\nprint('hello')"})

        transport = _mock_transport()
        transport.get_submissions.return_value = [
            RemoteSubmission(
                userid="100",
                username="alice",
                filename="A1.zip",
                url="http://example.com/A1.zip",
            )
        ]
        transport.download_file.side_effect = lambda url, dest: (
            dest.write_bytes(zip_bytes) or dest
        )

        do_fetch_submissions(transport, "HW1", tmp_path)
        # Should extract and save as alice.py
        assert (tmp_path / "alice.py").exists()
        assert b"student code" in (tmp_path / "alice.py").read_bytes()
        captured = capsys.readouterr()
        assert "Downloaded 1" in captured.out

    def test_fetch_submissions_zip_with_multiple_py(self, tmp_path, capsys):
        """Zip with multiple .py — only largest saved as {user}.py, extras skipped."""
        zip_bytes = _make_zip(
            {
                "A1.py": b"# main assignment (largest)",
                "helper.py": b"# helper",
            }
        )

        transport = _mock_transport()
        transport.get_submissions.return_value = [
            RemoteSubmission(
                userid="100",
                username="alice",
                filename="A1.zip",
                url="http://example.com/A1.zip",
            )
        ]
        transport.download_file.side_effect = lambda url, dest: (
            dest.write_bytes(zip_bytes) or dest
        )

        do_fetch_submissions(transport, "HW1", tmp_path)
        # alice.py should contain the main (largest) .py
        assert (tmp_path / "alice.py").exists()
        assert b"main assignment" in (tmp_path / "alice.py").read_bytes()
        # Extra .py files should NOT be extracted (avoids polluting submissions dir)
        assert not (tmp_path / "helper.py").exists()

    def test_fetch_submissions_zip_extracts_data_files(self, tmp_path, capsys):
        """Non-.py files (data, configs) from zip should be extracted."""
        zip_bytes = _make_zip(
            {
                "A1.py": b"# assignment",
                "data.csv": b"x,y\n1,2\n",
            }
        )

        transport = _mock_transport()
        transport.get_submissions.return_value = [
            RemoteSubmission(
                userid="100",
                username="alice",
                filename="A1.zip",
                url="http://example.com/A1.zip",
            )
        ]
        transport.download_file.side_effect = lambda url, dest: (
            dest.write_bytes(zip_bytes) or dest
        )

        do_fetch_submissions(transport, "HW1", tmp_path)
        assert (tmp_path / "alice.py").exists()
        assert (tmp_path / "data.csv").exists()


def _make_zip(files: dict[str, bytes]) -> bytes:
    """Create an in-memory zip with the given {name: content} entries."""
    import io

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, content in files.items():
            zf.writestr(name, content)
    return buf.getvalue()


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
