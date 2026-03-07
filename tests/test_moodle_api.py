"""Tests for mograder.moodle_api — Moodle REST API client and CLI commands."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import click
import pytest
from click.testing import CliRunner

from mograder.cli import cli
from mograder.moodle_api import (
    MoodleAPIClient,
    MoodleAPIError,
    find_assignment,
    resolve_credentials,
)


# ---------------------------------------------------------------------------
# MoodleAPIClient unit tests
# ---------------------------------------------------------------------------


class TestMoodleAPIClientCall:
    def test_call_success(self):
        client = MoodleAPIClient("https://moodle.example.com", "test-token")
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"status": "ok"}
        mock_resp.raise_for_status = MagicMock()
        with patch("requests.post", return_value=mock_resp) as mock_post:
            result = client._call("core_webservice_get_site_info")
        assert result == {"status": "ok"}
        call_data = mock_post.call_args
        assert call_data.kwargs["data"]["wsfunction"] == "core_webservice_get_site_info"
        assert call_data.kwargs["data"]["wstoken"] == "test-token"

    def test_call_error_response(self):
        client = MoodleAPIClient("https://moodle.example.com", "test-token")
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "exception": "webservice_access_exception",
            "errorcode": "invalidtoken",
            "message": "Invalid token",
        }
        mock_resp.raise_for_status = MagicMock()
        with patch("requests.post", return_value=mock_resp):
            with pytest.raises(MoodleAPIError) as exc_info:
                client._call("mod_assign_get_assignments")
        assert exc_info.value.error_code == "invalidtoken"
        assert "Invalid token" in str(exc_info.value)

    def test_call_network_error(self):
        client = MoodleAPIClient("https://moodle.example.com", "test-token")
        with patch("requests.post", side_effect=ConnectionError("Connection refused")):
            with pytest.raises(ConnectionError):
                client._call("mod_assign_get_assignments")


class TestGetAssignments:
    def test_get_assignments_flattens(self):
        client = MoodleAPIClient("https://moodle.example.com", "tok")
        moodle_response = {
            "courses": [
                {
                    "id": 1,
                    "assignments": [
                        {
                            "id": 10,
                            "name": "Assignment 1",
                            "duedate": 1700000000,
                            "introattachments": [
                                {
                                    "filename": "notebook.py",
                                    "fileurl": "https://moodle.example.com/file/1",
                                    "filesize": 1024,
                                }
                            ],
                        },
                        {
                            "id": 20,
                            "name": "Assignment 2",
                            "duedate": 0,
                            "introattachments": [],
                        },
                    ],
                }
            ]
        }
        with patch.object(client, "_call", return_value=moodle_response):
            result = client.get_assignments(1)
        assert len(result) == 2
        assert result[0]["id"] == 10
        assert result[0]["name"] == "Assignment 1"
        assert len(result[0]["introattachments"]) == 1
        assert result[1]["introattachments"] == []


class TestUploadFile:
    def test_upload_file_returns_itemid(self, tmp_path):
        client = MoodleAPIClient("https://moodle.example.com", "tok")
        test_file = tmp_path / "notebook.py"
        test_file.write_text("print('hello')")

        mock_resp = MagicMock()
        mock_resp.json.return_value = [{"itemid": 12345, "filename": "notebook.py"}]
        mock_resp.raise_for_status = MagicMock()
        with patch("requests.post", return_value=mock_resp):
            item_id = client.upload_file(test_file)
        assert item_id == 12345

    def test_upload_file_error(self, tmp_path):
        client = MoodleAPIClient("https://moodle.example.com", "tok")
        test_file = tmp_path / "notebook.py"
        test_file.write_text("print('hello')")

        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "exception": "moodle_exception",
            "errorcode": "nofile",
            "message": "The file has not been specified",
        }
        mock_resp.raise_for_status = MagicMock()
        with patch("requests.post", return_value=mock_resp):
            with pytest.raises(MoodleAPIError):
                client.upload_file(test_file)


class TestSaveSubmission:
    def test_save_submission_calls_correctly(self):
        client = MoodleAPIClient("https://moodle.example.com", "tok")
        with patch.object(client, "_call", return_value=[]) as mock_call:
            client.save_submission(10, 12345)
        mock_call.assert_called_once_with(
            "mod_assign_save_submission",
            assignmentid=10,
            **{"plugindata[files_filemanager]": 12345},
        )


class TestGetSubmissions:
    def test_get_submissions_extracts_files(self):
        client = MoodleAPIClient("https://moodle.example.com", "tok")
        moodle_response = {
            "assignments": [
                {
                    "assignmentid": 10,
                    "submissions": [
                        {
                            "userid": 100,
                            "status": "submitted",
                            "plugins": [
                                {
                                    "type": "file",
                                    "fileareas": [
                                        {
                                            "area": "submission_files",
                                            "files": [
                                                {
                                                    "filename": "student.py",
                                                    "fileurl": "https://moodle.example.com/file/42",
                                                    "filesize": 512,
                                                }
                                            ],
                                        }
                                    ],
                                }
                            ],
                        }
                    ],
                }
            ]
        }
        with patch.object(client, "_call", return_value=moodle_response):
            subs = client.get_submissions(10)
        assert len(subs) == 1
        assert subs[0]["userid"] == 100
        assert subs[0]["status"] == "submitted"
        assert len(subs[0]["files"]) == 1
        assert subs[0]["files"][0]["filename"] == "student.py"


class TestSaveGrades:
    def test_save_grades_params(self):
        client = MoodleAPIClient("https://moodle.example.com", "tok")
        grades = [
            {"userid": 100, "grade": 85, "feedback": "Good work"},
            {"userid": 200, "grade": 70, "feedback": "Needs improvement"},
        ]
        with patch.object(client, "_call", return_value=[]) as mock_call:
            client.save_grades(10, grades)
        call_kwargs = mock_call.call_args
        params = call_kwargs.kwargs if call_kwargs.kwargs else call_kwargs[1]
        # Just check the function name was correct
        assert call_kwargs.args[0] == "mod_assign_save_grades"


class TestDownloadFile:
    def test_download_file(self, tmp_path):
        client = MoodleAPIClient("https://moodle.example.com", "tok")
        dest = tmp_path / "downloaded.py"

        mock_resp = MagicMock()
        mock_resp.iter_content.return_value = [b"file content"]
        mock_resp.raise_for_status = MagicMock()
        with patch("requests.get", return_value=mock_resp):
            result = client.download_file(
                "https://moodle.example.com/pluginfile.php/123/mod_assign/intro/file.py",
                dest,
            )
        assert result == dest
        assert dest.read_text() == "file content"


# ---------------------------------------------------------------------------
# resolve_credentials tests
# ---------------------------------------------------------------------------


class TestResolveCredentials:
    def test_cli_overrides_env(self, monkeypatch):
        monkeypatch.setenv("MOGRADER_MOODLE_URL", "https://env.example.com")
        monkeypatch.setenv("MOGRADER_MOODLE_TOKEN", "env-token")
        config = MagicMock(moodle_url="https://config.example.com")
        url, token = resolve_credentials("https://cli.example.com", "cli-token", config)
        assert url == "https://cli.example.com"
        assert token == "cli-token"

    def test_env_overrides_config(self, monkeypatch):
        monkeypatch.setenv("MOGRADER_MOODLE_URL", "https://env.example.com")
        monkeypatch.setenv("MOGRADER_MOODLE_TOKEN", "env-token")
        config = MagicMock(moodle_url="https://config.example.com")
        url, token = resolve_credentials(None, None, config)
        assert url == "https://env.example.com"
        assert token == "env-token"

    def test_config_fallback(self, monkeypatch):
        monkeypatch.delenv("MOGRADER_MOODLE_URL", raising=False)
        monkeypatch.delenv("MOGRADER_MOODLE_TOKEN", raising=False)
        config = MagicMock(moodle_url="https://config.example.com")
        # Token is not in config, so this should fail
        with pytest.raises(click.UsageError, match="token"):
            resolve_credentials(None, None, config)

    def test_missing_url_errors(self, monkeypatch):
        monkeypatch.delenv("MOGRADER_MOODLE_URL", raising=False)
        monkeypatch.delenv("MOGRADER_MOODLE_TOKEN", raising=False)
        config = MagicMock(moodle_url=None)
        with pytest.raises(click.UsageError, match="URL"):
            resolve_credentials(None, "some-token", config)

    def test_missing_token_errors(self, monkeypatch):
        monkeypatch.delenv("MOGRADER_MOODLE_TOKEN", raising=False)
        config = MagicMock(moodle_url="https://example.com")
        with pytest.raises(click.UsageError, match="token"):
            resolve_credentials("https://example.com", None, config)

    def test_http_warning(self, monkeypatch, capsys):
        monkeypatch.delenv("MOGRADER_MOODLE_URL", raising=False)
        monkeypatch.delenv("MOGRADER_MOODLE_TOKEN", raising=False)
        config = MagicMock(moodle_url=None)
        url, token = resolve_credentials("http://insecure.example.com", "tok", config)
        assert url == "http://insecure.example.com"
        captured = capsys.readouterr()
        assert "HTTP" in captured.err or "HTTP" in captured.out


# ---------------------------------------------------------------------------
# find_assignment tests
# ---------------------------------------------------------------------------


class TestFindAssignment:
    def _make_client(self, assignments):
        client = MagicMock(spec=MoodleAPIClient)
        client.get_assignments.return_value = assignments
        return client

    def test_exact_match(self):
        client = self._make_client(
            [
                {"id": 1, "name": "Assignment 1"},
                {"id": 2, "name": "Assignment 2"},
            ]
        )
        result = find_assignment(client, 1, "Assignment 1")
        assert result["id"] == 1

    def test_case_insensitive_substring(self):
        client = self._make_client(
            [
                {"id": 1, "name": "Demo Assignment"},
            ]
        )
        result = find_assignment(client, 1, "demo")
        assert result["id"] == 1

    def test_numeric_id(self):
        client = self._make_client(
            [
                {"id": 42, "name": "Some Assignment"},
            ]
        )
        result = find_assignment(client, 1, "42")
        assert result["id"] == 42

    def test_no_match_errors(self):
        client = self._make_client(
            [
                {"id": 1, "name": "Assignment 1"},
            ]
        )
        with pytest.raises(click.UsageError, match="No assignment matching"):
            find_assignment(client, 1, "nonexistent")

    def test_ambiguous_match_errors(self):
        client = self._make_client(
            [
                {"id": 1, "name": "Assignment 1"},
                {"id": 2, "name": "Assignment 2"},
            ]
        )
        with pytest.raises(click.UsageError, match="Ambiguous"):
            find_assignment(client, 1, "assignment")

    def test_no_assignments_errors(self):
        client = self._make_client([])
        with pytest.raises(click.UsageError, match="No assignments found"):
            find_assignment(client, 1, "anything")


# ---------------------------------------------------------------------------
# CLI integration tests (CliRunner)
# ---------------------------------------------------------------------------


def _mock_config(monkeypatch, url="https://moodle.example.com", course_id=1):
    """Set up environment for Moodle API CLI tests."""
    monkeypatch.setenv("MOGRADER_MOODLE_URL", url)
    monkeypatch.setenv("MOGRADER_MOODLE_TOKEN", "test-token")
    return course_id


class TestMoodleFetchCLI:
    def test_fetch_list(self, monkeypatch):
        _mock_config(monkeypatch)
        assignments = [
            {
                "id": 10,
                "name": "Demo Assignment",
                "duedate": 1700000000,
                "introattachments": [{"filename": "demo.py"}],
            }
        ]
        with patch(
            "mograder.moodle_api.MoodleAPIClient.get_assignments",
            return_value=assignments,
        ):
            runner = CliRunner()
            result = runner.invoke(cli, ["moodle", "fetch", "--list", "-c", "1"])
        assert result.exit_code == 0, result.output
        assert "Demo Assignment" in result.output

    def test_fetch_downloads_files(self, monkeypatch, tmp_path):
        _mock_config(monkeypatch)
        assignment = {
            "id": 10,
            "name": "Demo Assignment",
            "duedate": 0,
            "introattachments": [
                {
                    "filename": "notebook.py",
                    "fileurl": "https://moodle.example.com/file/1",
                    "filesize": 100,
                }
            ],
        }
        with (
            patch(
                "mograder.moodle_api.MoodleAPIClient.get_assignments",
                return_value=[assignment],
            ),
            patch(
                "mograder.moodle_api.MoodleAPIClient.download_file",
                side_effect=lambda url, dest: dest.write_bytes(b"content") or dest,
            ),
        ):
            runner = CliRunner()
            result = runner.invoke(
                cli,
                [
                    "moodle",
                    "fetch",
                    "Demo Assignment",
                    "-c",
                    "1",
                    "-o",
                    str(tmp_path),
                ],
            )
        assert result.exit_code == 0, result.output
        assert "Downloaded" in result.output
        assert (tmp_path / "notebook.py").exists()

    def test_fetch_no_assignment_errors(self, monkeypatch):
        _mock_config(monkeypatch)
        runner = CliRunner()
        result = runner.invoke(cli, ["moodle", "fetch", "-c", "1"])
        assert result.exit_code != 0

    def test_fetch_extracts_zip(self, monkeypatch, tmp_path):
        """Test that downloaded .zip files are auto-extracted."""
        import zipfile

        _mock_config(monkeypatch)
        assignment = {
            "id": 10,
            "name": "Demo",
            "duedate": 0,
            "introattachments": [
                {
                    "filename": "data.zip",
                    "fileurl": "https://moodle.example.com/file/2",
                    "filesize": 200,
                }
            ],
        }

        # Create a real zip file when "downloading"
        def fake_download(url, dest):
            with zipfile.ZipFile(dest, "w") as zf:
                zf.writestr("input.csv", "a,b,c\n1,2,3\n")
            return dest

        with (
            patch(
                "mograder.moodle_api.MoodleAPIClient.get_assignments",
                return_value=[assignment],
            ),
            patch(
                "mograder.moodle_api.MoodleAPIClient.download_file",
                side_effect=fake_download,
            ),
        ):
            runner = CliRunner()
            result = runner.invoke(
                cli, ["moodle", "fetch", "Demo", "-c", "1", "-o", str(tmp_path)]
            )
        assert result.exit_code == 0, result.output
        assert "Extracted" in result.output
        assert (tmp_path / "input.csv").exists()


class TestMoodleSubmitCLI:
    def test_submit_uploads_and_finalizes(self, monkeypatch, tmp_path):
        _mock_config(monkeypatch)
        nb = tmp_path / "solution.py"
        nb.write_text("print('answer')")

        assignment = {"id": 10, "name": "Demo", "duedate": 0, "introattachments": []}
        with (
            patch(
                "mograder.moodle_api.MoodleAPIClient.get_assignments",
                return_value=[assignment],
            ),
            patch(
                "mograder.moodle_api.MoodleAPIClient.upload_file",
                return_value=99999,
            ) as mock_upload,
            patch("mograder.moodle_api.MoodleAPIClient.save_submission") as mock_save,
            patch(
                "mograder.moodle_api.MoodleAPIClient.submit_for_grading"
            ) as mock_finalize,
        ):
            runner = CliRunner()
            result = runner.invoke(
                cli,
                [
                    "moodle",
                    "submit",
                    str(nb),
                    "-a",
                    "Demo",
                    "-c",
                    "1",
                ],
            )
        assert result.exit_code == 0, result.output
        mock_upload.assert_called_once()
        mock_save.assert_called_once_with(10, 99999)
        mock_finalize.assert_called_once_with(10)

    def test_submit_dry_run(self, monkeypatch, tmp_path):
        _mock_config(monkeypatch)
        nb = tmp_path / "solution.py"
        nb.write_text("print('answer')")

        assignment = {"id": 10, "name": "Demo", "duedate": 0, "introattachments": []}
        with (
            patch(
                "mograder.moodle_api.MoodleAPIClient.get_assignments",
                return_value=[assignment],
            ),
            patch("mograder.moodle_api.MoodleAPIClient.upload_file") as mock_upload,
        ):
            runner = CliRunner()
            result = runner.invoke(
                cli,
                [
                    "moodle",
                    "submit",
                    str(nb),
                    "-a",
                    "Demo",
                    "-c",
                    "1",
                    "--dry-run",
                ],
            )
        assert result.exit_code == 0, result.output
        assert "Would submit" in result.output
        mock_upload.assert_not_called()

    def test_submit_no_finalize(self, monkeypatch, tmp_path):
        _mock_config(monkeypatch)
        nb = tmp_path / "solution.py"
        nb.write_text("print('answer')")

        assignment = {"id": 10, "name": "Demo", "duedate": 0, "introattachments": []}
        with (
            patch(
                "mograder.moodle_api.MoodleAPIClient.get_assignments",
                return_value=[assignment],
            ),
            patch(
                "mograder.moodle_api.MoodleAPIClient.upload_file",
                return_value=99999,
            ),
            patch("mograder.moodle_api.MoodleAPIClient.save_submission"),
            patch(
                "mograder.moodle_api.MoodleAPIClient.submit_for_grading"
            ) as mock_finalize,
        ):
            runner = CliRunner()
            result = runner.invoke(
                cli,
                [
                    "moodle",
                    "submit",
                    str(nb),
                    "-a",
                    "Demo",
                    "-c",
                    "1",
                    "--no-finalize",
                ],
            )
        assert result.exit_code == 0, result.output
        mock_finalize.assert_not_called()

    def test_submit_rejects_non_py(self, monkeypatch, tmp_path):
        _mock_config(monkeypatch)
        nb = tmp_path / "notebook.ipynb"
        nb.write_text("{}")
        runner = CliRunner()
        result = runner.invoke(
            cli, ["moodle", "submit", str(nb), "-a", "Demo", "-c", "1"]
        )
        assert result.exit_code != 0


class TestMoodleFetchSubmissionsCLI:
    def test_fetch_submissions(self, monkeypatch, tmp_path):
        _mock_config(monkeypatch)
        assignment = {"id": 10, "name": "Demo", "duedate": 0, "introattachments": []}
        participants = [{"id": 100, "username": "alice", "fullname": "Alice Smith"}]
        submissions = [
            {
                "userid": 100,
                "status": "submitted",
                "files": [
                    {
                        "filename": "solution.py",
                        "fileurl": "https://moodle.example.com/file/99",
                        "filesize": 256,
                    }
                ],
            }
        ]
        with (
            patch(
                "mograder.moodle_api.MoodleAPIClient.get_assignments",
                return_value=[assignment],
            ),
            patch(
                "mograder.moodle_api.MoodleAPIClient.list_participants",
                return_value=participants,
            ),
            patch(
                "mograder.moodle_api.MoodleAPIClient.get_submissions",
                return_value=submissions,
            ),
            patch(
                "mograder.moodle_api.MoodleAPIClient.download_file",
                side_effect=lambda url, dest: dest.write_bytes(b"code") or dest,
            ),
        ):
            runner = CliRunner()
            result = runner.invoke(
                cli,
                [
                    "moodle",
                    "fetch-submissions",
                    "Demo",
                    "-c",
                    "1",
                    "-o",
                    str(tmp_path),
                ],
            )
        assert result.exit_code == 0, result.output
        assert "Downloaded 1" in result.output
        assert (tmp_path / "alice.py").exists()


class TestMoodleUploadFeedbackCLI:
    def test_upload_feedback_dry_run(self, monkeypatch, tmp_path):
        _mock_config(monkeypatch)
        assignment = {"id": 10, "name": "Demo", "duedate": 0, "introattachments": []}
        participants = [{"id": 100, "username": "alice", "fullname": "Alice Smith"}]

        # Create a grades CSV
        grades_csv = tmp_path / "grades.csv"
        grades_csv.write_text("student,mark,feedback\nalice,85,Good\n")

        with (
            patch(
                "mograder.moodle_api.MoodleAPIClient.get_assignments",
                return_value=[assignment],
            ),
            patch(
                "mograder.moodle_api.MoodleAPIClient.list_participants",
                return_value=participants,
            ),
            patch("mograder.moodle_api.MoodleAPIClient.save_grades") as mock_grades,
        ):
            runner = CliRunner()
            result = runner.invoke(
                cli,
                [
                    "moodle",
                    "upload-feedback",
                    "Demo",
                    "-c",
                    "1",
                    "--grades-csv",
                    str(grades_csv),
                    "--dry-run",
                ],
            )
        assert result.exit_code == 0, result.output
        assert "Would upload" in result.output
        mock_grades.assert_not_called()


class TestMoodleExportCLI:
    """Verify the existing moodle export (formerly top-level moodle) still works."""

    def test_export_basic(self, tmp_path):
        # Create a minimal Moodle worksheet
        worksheet = tmp_path / "worksheet.csv"
        worksheet.write_text(
            "\ufeff"
            "Identifier,Full name,Username,Grade,Maximum grade,"
            "Last modified (submission),Last modified (grade)\n"
            '"Participant 1","Alice","alice","","100","",""\n',
            encoding="utf-8-sig",
        )
        grades = tmp_path / "grades.csv"
        grades.write_text("student,mark,feedback\nalice,85,Good\n")

        out_dir = tmp_path / "export"
        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "moodle",
                "export",
                str(worksheet),
                "--grades-csv",
                str(grades),
                "-o",
                str(out_dir),
            ],
        )
        assert result.exit_code == 0, result.output
        assert (out_dir / "worksheet.csv").exists()
