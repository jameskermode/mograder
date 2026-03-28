"""Tests for mograder.transport.moodle_api — Moodle REST API client and CLI commands."""

from unittest.mock import MagicMock, patch

import click
import pytest
from click.testing import CliRunner

from mograder.cli import cli
from mograder.transport.moodle_api import (
    MoodleAPIClient,
    MoodleAPIError,
    build_sso_login_url,
    clear_cached_token,
    extract_token_from_sso_url,
    find_assignment,
    load_cached_token,
    request_token,
    resolve_credentials,
    save_cached_token,
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
                            "intro": "<p>Do this assignment.</p>",
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
        assert result[0]["intro"] == "<p>Do this assignment.</p>"
        assert len(result[0]["introattachments"]) == 1
        assert result[1]["introattachments"] == []
        assert result[1]["intro"] == ""


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
        # Uses singular save_grade API, called once per student
        assert mock_call.call_count == 2
        for call in mock_call.call_args_list:
            assert call.args[0] == "mod_assign_save_grade"


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
        with patch(
            "mograder.transport.moodle_api.load_cached_token", return_value=None
        ):
            with pytest.raises(click.UsageError, match="token"):
                resolve_credentials("https://example.com", None, config)

    def test_cached_token_fallback(self, monkeypatch):
        monkeypatch.delenv("MOGRADER_MOODLE_TOKEN", raising=False)
        config = MagicMock(moodle_url="https://example.com")
        cached = {"url": "https://example.com", "token": "cached-tok", "fullname": "A"}
        with patch(
            "mograder.transport.moodle_api.load_cached_token", return_value=cached
        ):
            url, token = resolve_credentials("https://example.com", None, config)
        assert token == "cached-tok"

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
            "mograder.transport.moodle_api.MoodleAPIClient.get_assignments",
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
                "mograder.transport.moodle_api.MoodleAPIClient.get_assignments",
                return_value=[assignment],
            ),
            patch(
                "mograder.transport.moodle_api.MoodleAPIClient.download_file",
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
                "mograder.transport.moodle_api.MoodleAPIClient.get_assignments",
                return_value=[assignment],
            ),
            patch(
                "mograder.transport.moodle_api.MoodleAPIClient.download_file",
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
                "mograder.transport.moodle_api.MoodleAPIClient.get_assignments",
                return_value=[assignment],
            ),
            patch(
                "mograder.transport.moodle_api.MoodleAPIClient.upload_file",
                return_value=99999,
            ) as mock_upload,
            patch(
                "mograder.transport.moodle_api.MoodleAPIClient.save_submission"
            ) as mock_save,
            patch(
                "mograder.transport.moodle_api.MoodleAPIClient.submit_for_grading"
            ) as mock_finalize,
        ):
            runner = CliRunner()
            result = runner.invoke(
                cli,
                [
                    "moodle",
                    "submit",
                    "Demo",
                    str(nb),
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
                "mograder.transport.moodle_api.MoodleAPIClient.get_assignments",
                return_value=[assignment],
            ),
            patch(
                "mograder.transport.moodle_api.MoodleAPIClient.upload_file"
            ) as mock_upload,
        ):
            runner = CliRunner()
            result = runner.invoke(
                cli,
                [
                    "moodle",
                    "submit",
                    "Demo",
                    str(nb),
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
                "mograder.transport.moodle_api.MoodleAPIClient.get_assignments",
                return_value=[assignment],
            ),
            patch(
                "mograder.transport.moodle_api.MoodleAPIClient.upload_file",
                return_value=99999,
            ),
            patch("mograder.transport.moodle_api.MoodleAPIClient.save_submission"),
            patch(
                "mograder.transport.moodle_api.MoodleAPIClient.submit_for_grading"
            ) as mock_finalize,
        ):
            runner = CliRunner()
            result = runner.invoke(
                cli,
                [
                    "moodle",
                    "submit",
                    "Demo",
                    str(nb),
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
        result = runner.invoke(cli, ["moodle", "submit", "Demo", str(nb), "-c", "1"])
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
                "mograder.transport.moodle_api.MoodleAPIClient.get_assignments",
                return_value=[assignment],
            ),
            patch(
                "mograder.transport.moodle_api.MoodleAPIClient.list_participants",
                return_value=participants,
            ),
            patch(
                "mograder.transport.moodle_api.MoodleAPIClient.get_submissions",
                return_value=submissions,
            ),
            patch(
                "mograder.transport.moodle_api.MoodleAPIClient.download_file",
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
                "mograder.transport.moodle_api.MoodleAPIClient.get_assignments",
                return_value=[assignment],
            ),
            patch(
                "mograder.transport.moodle_api.MoodleAPIClient.list_participants",
                return_value=participants,
            ),
            patch(
                "mograder.transport.moodle_api.MoodleAPIClient.save_grades"
            ) as mock_grades,
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
    """Verify moodle export with assignment-based signature."""

    def test_export_basic(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)

        # Place worksheet at import/<assignment>.csv
        import_dir = tmp_path / "import"
        import_dir.mkdir()
        worksheet = import_dir / "hw1.csv"
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
                "hw1",
                "--grades-csv",
                str(grades),
                "-o",
                str(out_dir),
            ],
        )
        assert result.exit_code == 0, result.output
        assert (out_dir / "hw1.csv").exists()

    def test_export_with_explicit_worksheet(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)

        worksheet = tmp_path / "custom.csv"
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
                "hw1",
                "--worksheet",
                str(worksheet),
                "--grades-csv",
                str(grades),
                "-o",
                str(out_dir),
            ],
        )
        assert result.exit_code == 0, result.output


# ---------------------------------------------------------------------------
# Auth and token cache tests
# ---------------------------------------------------------------------------


class TestGetSiteInfo:
    def test_get_site_info(self):
        client = MoodleAPIClient("https://moodle.example.com", "tok")
        moodle_response = {
            "userid": 42,
            "username": "alice",
            "fullname": "Alice Smith",
            "sitename": "Test Moodle",
        }
        with patch.object(client, "_call", return_value=moodle_response):
            info = client.get_site_info()
        assert info["userid"] == 42
        assert info["username"] == "alice"
        assert info["fullname"] == "Alice Smith"
        assert info["sitename"] == "Test Moodle"


class TestRequestToken:
    def test_request_token_success(self):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"token": "abc123", "privatetoken": "xyz"}
        mock_resp.raise_for_status = MagicMock()
        with patch("requests.post", return_value=mock_resp) as mock_post:
            token = request_token("https://moodle.example.com", "alice", "pass123")
        assert token == "abc123"
        call_data = mock_post.call_args
        assert "login/token.php" in call_data.args[0]
        assert call_data.kwargs["data"]["service"] == "moodle_mobile_app"

    def test_request_token_invalid_credentials(self):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "error": "Invalid login",
            "errorcode": "invalidlogin",
        }
        mock_resp.raise_for_status = MagicMock()
        with patch("requests.post", return_value=mock_resp):
            with pytest.raises(MoodleAPIError, match="Invalid login"):
                request_token("https://moodle.example.com", "alice", "wrong")

    def test_request_token_custom_service(self):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"token": "tok999"}
        mock_resp.raise_for_status = MagicMock()
        with patch("requests.post", return_value=mock_resp) as mock_post:
            token = request_token(
                "https://moodle.example.com", "alice", "pass", service="custom_svc"
            )
        assert token == "tok999"
        assert mock_post.call_args.kwargs["data"]["service"] == "custom_svc"


class TestTokenCache:
    def test_save_and_load(self, tmp_path, monkeypatch):
        cache_file = tmp_path / "token.json"
        monkeypatch.setattr("mograder.transport.moodle_api.TOKEN_CACHE", cache_file)

        save_cached_token("https://moodle.example.com", "tok123", "Alice Smith")

        result = load_cached_token("https://moodle.example.com")
        assert result is not None
        assert result["token"] == "tok123"
        assert result["fullname"] == "Alice Smith"
        assert result["url"] == "https://moodle.example.com"

    def test_load_wrong_url(self, tmp_path, monkeypatch):
        cache_file = tmp_path / "token.json"
        monkeypatch.setattr("mograder.transport.moodle_api.TOKEN_CACHE", cache_file)

        save_cached_token("https://moodle.example.com", "tok123", "Alice")
        result = load_cached_token("https://other.example.com")
        assert result is None

    def test_load_missing_file(self, tmp_path, monkeypatch):
        cache_file = tmp_path / "nonexistent" / "token.json"
        monkeypatch.setattr("mograder.transport.moodle_api.TOKEN_CACHE", cache_file)

        result = load_cached_token("https://moodle.example.com")
        assert result is None

    def test_load_corrupt_file(self, tmp_path, monkeypatch):
        cache_file = tmp_path / "token.json"
        cache_file.write_text("not json!")
        monkeypatch.setattr("mograder.transport.moodle_api.TOKEN_CACHE", cache_file)

        result = load_cached_token("https://moodle.example.com")
        assert result is None

    def test_clear(self, tmp_path, monkeypatch):
        cache_file = tmp_path / "token.json"
        monkeypatch.setattr("mograder.transport.moodle_api.TOKEN_CACHE", cache_file)

        save_cached_token("https://moodle.example.com", "tok123", "Alice")
        assert cache_file.exists()
        clear_cached_token()
        assert not cache_file.exists()

    def test_clear_missing_ok(self, tmp_path, monkeypatch):
        cache_file = tmp_path / "nonexistent.json"
        monkeypatch.setattr("mograder.transport.moodle_api.TOKEN_CACHE", cache_file)
        clear_cached_token()  # Should not raise

    def test_url_trailing_slash(self, tmp_path, monkeypatch):
        cache_file = tmp_path / "token.json"
        monkeypatch.setattr("mograder.transport.moodle_api.TOKEN_CACHE", cache_file)

        save_cached_token("https://moodle.example.com/", "tok123", "Alice")
        result = load_cached_token("https://moodle.example.com")
        assert result is not None
        assert result["token"] == "tok123"


# ---------------------------------------------------------------------------
# get_submission_status tests
# ---------------------------------------------------------------------------


class TestGetSubmissionStatus:
    def test_submitted_no_grade(self):
        client = MoodleAPIClient("https://moodle.example.com", "tok")
        moodle_response = {
            "lastattempt": {
                "submission": {"status": "submitted"},
            },
        }
        with patch.object(client, "_call", return_value=moodle_response):
            status = client.get_submission_status(10)
        assert status["status"] == "submitted"
        assert status["graded"] is False
        assert status["grade"] is None
        assert status["feedback"] == ""

    def test_graded_with_feedback(self):
        client = MoodleAPIClient("https://moodle.example.com", "tok")
        moodle_response = {
            "lastattempt": {
                "submission": {"status": "submitted"},
            },
            "feedback": {
                "grade": {"grade": "85.00"},
                "plugins": [
                    {
                        "type": "comments",
                        "editorfields": [
                            {"name": "comments", "text": "Good work!"},
                        ],
                    },
                ],
            },
        }
        with patch.object(client, "_call", return_value=moodle_response):
            status = client.get_submission_status(10)
        assert status["status"] == "submitted"
        assert status["graded"] is True
        assert status["grade"] == "85.00"
        assert status["feedback"] == "Good work!"

    def test_new_submission(self):
        client = MoodleAPIClient("https://moodle.example.com", "tok")
        moodle_response = {}
        with patch.object(client, "_call", return_value=moodle_response):
            status = client.get_submission_status(10)
        assert status["status"] == "new"
        assert status["graded"] is False

    def test_feedback_from_fileareas(self):
        client = MoodleAPIClient("https://moodle.example.com", "tok")
        moodle_response = {
            "lastattempt": {"submission": {"status": "submitted"}},
            "feedback": {
                "grade": {"grade": "70.00"},
                "plugins": [
                    {
                        "type": "comments",
                        "editorfields": [],
                        "fileareas": [{"text": "Needs improvement"}],
                    },
                ],
            },
        }
        with patch.object(client, "_call", return_value=moodle_response):
            status = client.get_submission_status(10)
        assert status["feedback"] == "Needs improvement"


# ---------------------------------------------------------------------------
# moodle feedback CLI test
# ---------------------------------------------------------------------------


class TestMoodleFeedbackCLI:
    def test_feedback_graded(self, monkeypatch):
        _mock_config(monkeypatch)
        with (
            patch(
                "mograder.transport.moodle_api.MoodleAPIClient.get_assignments",
                return_value=[
                    {"id": 10, "name": "HW1", "duedate": 0, "introattachments": []},
                ],
            ),
            patch(
                "mograder.transport.moodle_api.MoodleAPIClient.get_submission_status",
                return_value={
                    "status": "submitted",
                    "graded": True,
                    "grade": "90.00",
                    "feedback": "Excellent work!",
                },
            ),
        ):
            runner = CliRunner()
            result = runner.invoke(
                cli,
                ["moodle", "feedback", "HW1", "-c", "1"],
                catch_exceptions=False,
            )
        assert result.exit_code == 0, result.output
        assert "HW1" in result.output
        assert "90.00" in result.output
        assert "Excellent work!" in result.output

    def test_feedback_not_graded(self, monkeypatch):
        _mock_config(monkeypatch)
        with (
            patch(
                "mograder.transport.moodle_api.MoodleAPIClient.get_assignments",
                return_value=[
                    {"id": 10, "name": "HW1", "duedate": 0, "introattachments": []},
                ],
            ),
            patch(
                "mograder.transport.moodle_api.MoodleAPIClient.get_submission_status",
                return_value={
                    "status": "submitted",
                    "graded": False,
                    "grade": None,
                    "feedback": "",
                },
            ),
        ):
            runner = CliRunner()
            result = runner.invoke(
                cli,
                ["moodle", "feedback", "HW1", "-c", "1"],
            )
        assert result.exit_code == 0, result.output
        assert "Not yet graded" in result.output


# ---------------------------------------------------------------------------
# SSO login tests
# ---------------------------------------------------------------------------


class TestBuildSsoLoginUrl:
    def test_basic_url(self):
        url = build_sso_login_url("https://moodle.example.com", "abc123")
        assert url == (
            "https://moodle.example.com/admin/tool/mobile/launch.php"
            "?service=moodle_mobile_app&passport=abc123"
        )

    def test_trailing_slash_stripped(self):
        url = build_sso_login_url("https://moodle.example.com/", "abc123")
        assert url.startswith("https://moodle.example.com/admin/")

    def test_custom_service(self):
        url = build_sso_login_url(
            "https://moodle.example.com", "abc", service="custom_svc"
        )
        assert "service=custom_svc" in url


class TestExtractTokenFromSsoUrl:
    def test_standard_moodlemobile_url(self):
        import base64

        payload = base64.b64encode(b"siteid123:::mytoken:::privatetoken").decode()
        url = f"moodlemobile://token={payload}"
        token = extract_token_from_sso_url(url)
        assert token == "mytoken"

    def test_two_part_payload(self):
        import base64

        payload = base64.b64encode(b"siteid123:::mytoken").decode()
        url = f"moodlemobile://token={payload}"
        token = extract_token_from_sso_url(url)
        assert token == "mytoken"

    def test_raw_base64_string(self):
        import base64

        payload = base64.b64encode(b"siteid123:::rawtoken:::priv").decode()
        token = extract_token_from_sso_url(payload)
        assert token == "rawtoken"

    def test_invalid_base64_raises(self):
        with pytest.raises(MoodleAPIError, match="Could not decode"):
            extract_token_from_sso_url("moodlemobile://token=!!!invalid!!!")

    def test_single_part_payload_raises(self):
        import base64

        payload = base64.b64encode(b"notokenhere").decode()
        url = f"moodlemobile://token={payload}"
        with pytest.raises(MoodleAPIError, match="Unexpected token format"):
            extract_token_from_sso_url(url)


# ---------------------------------------------------------------------------
# upload_file with itemid, upload_files_to_draft, update_introattachments
# ---------------------------------------------------------------------------


class TestUploadFileItemid:
    def test_upload_file_passes_nonzero_itemid(self, tmp_path):
        client = MoodleAPIClient("https://moodle.example.com", "tok")
        test_file = tmp_path / "notebook.py"
        test_file.write_text("print('hello')")

        mock_resp = MagicMock()
        mock_resp.json.return_value = [{"itemid": 555, "filename": "notebook.py"}]
        mock_resp.raise_for_status = MagicMock()
        with patch("requests.post", return_value=mock_resp) as mock_post:
            item_id = client.upload_file(test_file, itemid=555)
        assert item_id == 555
        # Verify itemid was passed in the request data
        call_data = mock_post.call_args
        assert call_data.kwargs["data"]["itemid"] == 555

    def test_upload_file_default_itemid_zero(self, tmp_path):
        client = MoodleAPIClient("https://moodle.example.com", "tok")
        test_file = tmp_path / "notebook.py"
        test_file.write_text("print('hello')")

        mock_resp = MagicMock()
        mock_resp.json.return_value = [{"itemid": 123, "filename": "notebook.py"}]
        mock_resp.raise_for_status = MagicMock()
        with patch("requests.post", return_value=mock_resp) as mock_post:
            item_id = client.upload_file(test_file)
        assert item_id == 123
        call_data = mock_post.call_args
        assert call_data.kwargs["data"]["itemid"] == 0


class TestUploadFilesToDraft:
    def test_chains_calls_and_returns_final_itemid(self, tmp_path):
        client = MoodleAPIClient("https://moodle.example.com", "tok")
        f1 = tmp_path / "a.py"
        f2 = tmp_path / "b.py"
        f1.write_text("a")
        f2.write_text("b")

        # First call creates draft (itemid=0 → returns 100)
        # Second call appends (itemid=100 → returns 100)
        with patch.object(client, "upload_file", side_effect=[100, 100]) as mock_upload:
            result = client.upload_files_to_draft([f1, f2])
        assert result == 100
        assert mock_upload.call_count == 2
        mock_upload.assert_any_call(f1, itemid=0)
        mock_upload.assert_any_call(f2, itemid=100)

    def test_empty_list_raises(self):
        client = MoodleAPIClient("https://moodle.example.com", "tok")
        with pytest.raises(ValueError, match="No files"):
            client.upload_files_to_draft([])


class TestUpdateIntroattachments:
    def test_calls_edit_module(self):
        client = MoodleAPIClient("https://moodle.example.com", "tok")
        with patch.object(client, "_call", return_value={}) as mock_call:
            client.update_introattachments(42, 999)
        mock_call.assert_called_once_with(
            "core_course_edit_module",
            action="update",
            id=42,
            introattachments=999,
        )

    def test_raises_on_api_error(self):
        client = MoodleAPIClient("https://moodle.example.com", "tok")
        with patch.object(
            client, "_call", side_effect=MoodleAPIError("Access denied", "nopermission")
        ):
            with pytest.raises(MoodleAPIError, match="Access denied"):
                client.update_introattachments(42, 999)


class TestUpdateIntro:
    def test_calls_edit_module_with_html(self):
        client = MoodleAPIClient("https://moodle.example.com", "tok")
        with patch.object(client, "_call", return_value={}) as mock_call:
            client.update_intro(42, "<p>Hello world</p>")
        mock_call.assert_called_once_with(
            "core_course_edit_module",
            action="update",
            id=42,
            intro="<p>Hello world</p>",
            introformat=1,
        )

    def test_raises_on_api_error(self):
        client = MoodleAPIClient("https://moodle.example.com", "tok")
        with patch.object(
            client, "_call", side_effect=MoodleAPIError("Access denied", "nopermission")
        ):
            with pytest.raises(MoodleAPIError, match="Access denied"):
                client.update_intro(42, "<p>test</p>")


# ---------------------------------------------------------------------------
# moodle upload CLI tests
# ---------------------------------------------------------------------------


class TestMoodleUploadCLI:
    """Tests for ``moodle upload`` — zips release files and opens edit page."""

    def test_dry_run(self, monkeypatch, tmp_path):
        _mock_config(monkeypatch)
        monkeypatch.chdir(tmp_path)
        f1 = tmp_path / "notebook.py"
        f1.write_text("print('hello')")

        assignment = {
            "id": 10,
            "cmid": 42,
            "name": "Demo",
            "duedate": 0,
            "introattachments": [],
        }
        with patch(
            "mograder.transport.moodle_api.MoodleAPIClient.get_assignments",
            return_value=[assignment],
        ):
            runner = CliRunner()
            result = runner.invoke(
                cli,
                ["moodle", "upload", "Demo", str(f1), "-c", "1", "--dry-run"],
            )
        assert result.exit_code == 0, result.output
        assert "Would create Demo.zip" in result.output
        assert "notebook.py" in result.output
        # Dry run should clean up the zip
        assert not (tmp_path / "Demo.zip").exists()

    def test_explicit_files_zipped(self, monkeypatch, tmp_path):
        import zipfile

        _mock_config(monkeypatch)
        monkeypatch.chdir(tmp_path)
        f1 = tmp_path / "a.py"
        f2 = tmp_path / "data.csv"
        f1.write_text("a")
        f2.write_text("x,y\n1,2\n")

        assignment = {
            "id": 10,
            "cmid": 42,
            "name": "Demo",
            "duedate": 0,
            "introattachments": [],
        }
        with (
            patch(
                "mograder.transport.moodle_api.MoodleAPIClient.get_assignments",
                return_value=[assignment],
            ),
            patch("webbrowser.open"),
        ):
            runner = CliRunner()
            result = runner.invoke(
                cli,
                ["moodle", "upload", "Demo", str(f1), str(f2), "-c", "1"],
            )
        assert result.exit_code == 0, result.output
        assert "Created Demo.zip" in result.output
        assert "modedit.php?update=42" in result.output
        # Verify zip was created with both files
        zip_path = tmp_path / "Demo.zip"
        assert zip_path.exists()
        with zipfile.ZipFile(zip_path) as zf:
            assert sorted(zf.namelist()) == ["a.py", "data.csv"]
        zip_path.unlink()

    def test_auto_discover_release_files(self, monkeypatch, tmp_path):
        import zipfile

        _mock_config(monkeypatch)
        monkeypatch.chdir(tmp_path)

        # Create release/Demo/notebook.py
        release_dir = tmp_path / "release" / "Demo"
        release_dir.mkdir(parents=True)
        nb = release_dir / "notebook.py"
        nb.write_text("print('hello')")

        assignment = {
            "id": 10,
            "cmid": 42,
            "name": "Demo",
            "duedate": 0,
            "introattachments": [],
        }
        with (
            patch(
                "mograder.transport.moodle_api.MoodleAPIClient.get_assignments",
                return_value=[assignment],
            ),
            patch("webbrowser.open"),
        ):
            runner = CliRunner()
            result = runner.invoke(
                cli,
                ["moodle", "upload", "Demo", "-c", "1"],
            )
        assert result.exit_code == 0, result.output
        zip_path = tmp_path / "Demo.zip"
        assert zip_path.exists()
        with zipfile.ZipFile(zip_path) as zf:
            assert zf.namelist() == ["notebook.py"]
        zip_path.unlink()

    def test_no_open(self, monkeypatch, tmp_path):
        _mock_config(monkeypatch)
        monkeypatch.chdir(tmp_path)
        f1 = tmp_path / "a.py"
        f1.write_text("a")

        assignment = {
            "id": 10,
            "cmid": 42,
            "name": "Demo",
            "duedate": 0,
            "introattachments": [],
        }
        with (
            patch(
                "mograder.transport.moodle_api.MoodleAPIClient.get_assignments",
                return_value=[assignment],
            ),
            patch("webbrowser.open") as mock_open,
        ):
            runner = CliRunner()
            result = runner.invoke(
                cli,
                ["moodle", "upload", "Demo", str(f1), "-c", "1", "--no-open"],
            )
        assert result.exit_code == 0, result.output
        mock_open.assert_not_called()
        assert "modedit.php?update=42" in result.output
        (tmp_path / "Demo.zip").unlink()

    def test_no_cmid_fallback(self, monkeypatch, tmp_path):
        _mock_config(monkeypatch)
        monkeypatch.chdir(tmp_path)
        f1 = tmp_path / "a.py"
        f1.write_text("a")

        assignment = {
            "id": 10,
            "name": "Demo",
            "duedate": 0,
            "introattachments": [],
        }
        with patch(
            "mograder.transport.moodle_api.MoodleAPIClient.get_assignments",
            return_value=[assignment],
        ):
            runner = CliRunner()
            result = runner.invoke(
                cli,
                ["moodle", "upload", "Demo", str(f1), "-c", "1"],
            )
        assert result.exit_code == 0, result.output
        assert "open the assignment edit page manually" in result.output
        (tmp_path / "Demo.zip").unlink()


# ---------------------------------------------------------------------------
# moodle sync --edit-links tests
# ---------------------------------------------------------------------------


class TestMoodleSyncEditLinks:
    def test_edit_links_pushes_intro(self, monkeypatch, tmp_path):
        """--edit-links builds HTML and calls update_intro for assignments with a dir."""
        _mock_config(monkeypatch)
        monkeypatch.chdir(tmp_path)

        # Create release dir with a .py file
        release = tmp_path / "release" / "A1-Demo"
        release.mkdir(parents=True)
        (release / "A1-Demo.py").write_text("print('hello')")

        # Create mograder.toml with edit_links config AND existing assignment with dir
        toml_path = tmp_path / "mograder.toml"
        toml_path.write_text(
            '[edit_links]\nmolab = "https://molab.marimo.io/new/#code/{content_lz}"\n\n'
            "[[assignments]]\n"
            'name = "A1. Demo Assignment"\n'
            "cmid = 42\n"
            'dir = "A1-Demo"\n'
        )

        assignments = [
            {
                "id": 10,
                "cmid": 42,
                "name": "A1. Demo Assignment",
                "duedate": 1700000000,
                "intro": "<p>Old description</p>",
                "introattachments": [],
            },
        ]
        # course contents for visibility check
        course_contents = [
            {
                "modules": [
                    {"id": 42, "modname": "assign", "visible": 1},
                ]
            }
        ]

        with (
            patch.object(
                MoodleAPIClient,
                "get_assignments",
                return_value=assignments,
            ),
            patch.object(
                MoodleAPIClient,
                "_call",
                return_value=course_contents,
            ),
            patch.object(
                MoodleAPIClient,
                "update_intro",
            ) as mock_update,
        ):
            runner = CliRunner()
            result = runner.invoke(
                cli,
                ["moodle", "sync", "-c", "1", "--edit-links"],
            )

        assert result.exit_code == 0, result.output
        assert mock_update.called
        # Verify the HTML passed contains molab link and markers
        call_args = mock_update.call_args
        assert call_args[0][0] == 42  # cmid
        intro_html = call_args[0][1]
        assert "molab.marimo.io" in intro_html
        assert "<!-- mograder:edit-links -->" in intro_html
        assert "<p>Old description</p>" in intro_html

    def test_edit_links_skips_no_dir(self, monkeypatch, tmp_path):
        """Assignments without a dir are skipped for edit-links."""
        _mock_config(monkeypatch)
        monkeypatch.chdir(tmp_path)

        toml_path = tmp_path / "mograder.toml"
        toml_path.write_text(
            '[edit_links]\nmolab = "https://molab.marimo.io/new/#code/{content_lz}"\n'
        )

        assignments = [
            {
                "id": 10,
                "cmid": 42,
                "name": "A1. Demo",
                "duedate": 0,
                "intro": "",
                "introattachments": [],
            },
        ]
        course_contents = [{"modules": [{"id": 42, "modname": "assign", "visible": 1}]}]

        with (
            patch.object(
                MoodleAPIClient,
                "get_assignments",
                return_value=assignments,
            ),
            patch.object(
                MoodleAPIClient,
                "_call",
                return_value=course_contents,
            ),
            patch.object(
                MoodleAPIClient,
                "update_intro",
            ) as mock_update,
        ):
            runner = CliRunner()
            result = runner.invoke(
                cli,
                ["moodle", "sync", "-c", "1", "--edit-links"],
            )

        assert result.exit_code == 0, result.output
        mock_update.assert_not_called()

    def test_edit_links_fallback_on_access_error(self, monkeypatch, tmp_path):
        """When update_intro fails, an HTML file is written for manual paste."""
        _mock_config(monkeypatch)
        monkeypatch.chdir(tmp_path)

        release = tmp_path / "release" / "A1-Demo"
        release.mkdir(parents=True)
        (release / "A1-Demo.py").write_text("print('hello')")

        toml_path = tmp_path / "mograder.toml"
        toml_path.write_text(
            '[edit_links]\nmolab = "https://molab.marimo.io/new/#code/{content_lz}"\n\n'
            "[[assignments]]\n"
            'name = "A1. Demo Assignment"\n'
            "cmid = 42\n"
            'dir = "A1-Demo"\n'
        )

        assignments = [
            {
                "id": 10,
                "cmid": 42,
                "name": "A1. Demo Assignment",
                "duedate": 0,
                "intro": "",
                "introattachments": [],
            },
        ]
        course_contents = [{"modules": [{"id": 42, "modname": "assign", "visible": 1}]}]

        with (
            patch.object(
                MoodleAPIClient,
                "get_assignments",
                return_value=assignments,
            ),
            patch.object(
                MoodleAPIClient,
                "_call",
                return_value=course_contents,
            ),
            patch.object(
                MoodleAPIClient,
                "update_intro",
                side_effect=MoodleAPIError("Access control exception"),
            ),
        ):
            runner = CliRunner()
            result = runner.invoke(
                cli,
                ["moodle", "sync", "-c", "1", "--edit-links"],
            )

        assert result.exit_code == 0, result.output
        assert "edit-links.html" in result.output

        html_file = tmp_path / "edit-links.html"
        assert html_file.exists()
        content = html_file.read_text()
        assert "modedit.php?update=42" in content
        assert "molab.marimo.io" in content
        assert "A1. Demo Assignment" in content
