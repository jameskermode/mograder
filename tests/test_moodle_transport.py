"""Tests for MoodleTransport adapter wrapping MoodleAPIClient."""

from unittest.mock import MagicMock, patch

from mograder.models import RemoteAssignment, RemoteStatus, RemoteSubmission
from mograder.moodle_api import MoodleAPIClient
from mograder.moodle_transport import MoodleTransport


def _make_transport():
    client = MagicMock(spec=MoodleAPIClient)
    return MoodleTransport(client, course_id=1), client


class TestListAssignments:
    def test_list_maps_to_remote_assignments(self):
        transport, client = _make_transport()
        client.get_assignments.return_value = [
            {
                "id": 10,
                "name": "HW1",
                "cmid": 42,
                "duedate": 1700000000,
                "introattachments": [
                    {"filename": "hw1.py", "fileurl": "https://moodle.example.com/f/1"}
                ],
            }
        ]
        result = transport.list_assignments()
        assert len(result) == 1
        assert isinstance(result[0], RemoteAssignment)
        assert result[0].name == "HW1"
        assert result[0].id == "10"
        assert result[0].cmid == "42"
        assert len(result[0].files) == 1


class TestDownloadFile:
    def test_delegates_to_client(self, tmp_path):
        transport, client = _make_transport()
        dest = tmp_path / "file.py"
        client.download_file.return_value = dest
        result = transport.download_file("https://example.com/f", dest)
        assert result == dest
        client.download_file.assert_called_once_with("https://example.com/f", dest)


class TestSubmitFile:
    def test_submit_uploads_and_finalizes(self, tmp_path):
        transport, client = _make_transport()
        nb = tmp_path / "sol.py"
        nb.write_text("code")

        with patch(
            "mograder.moodle_transport.find_assignment",
            return_value={"id": 10, "name": "HW1"},
        ):
            client.upload_file.return_value = 99999
            transport.submit_file("HW1", nb)

        client.upload_file.assert_called_once_with(nb)
        client.save_submission.assert_called_once_with(10, 99999)
        client.submit_for_grading.assert_called_once_with(10)


class TestGetSubmissions:
    def test_maps_submissions(self):
        transport, client = _make_transport()
        with patch(
            "mograder.moodle_transport.find_assignment",
            return_value={"id": 10, "name": "HW1"},
        ):
            client.list_participants.return_value = [
                {"id": 100, "username": "alice", "fullname": "Alice"}
            ]
            client.get_submissions.return_value = [
                {
                    "userid": 100,
                    "status": "submitted",
                    "files": [
                        {"filename": "sol.py", "fileurl": "https://example.com/sol.py"}
                    ],
                }
            ]
            result = transport.get_submissions("HW1")

        assert len(result) == 1
        assert isinstance(result[0], RemoteSubmission)
        assert result[0].username == "alice"
        assert result[0].filename == "sol.py"


class TestUploadGrades:
    def test_delegates_to_client(self):
        transport, client = _make_transport()
        grades = [{"userid": 100, "grade": 85}]
        with patch(
            "mograder.moodle_transport.find_assignment",
            return_value={"id": 10, "name": "HW1"},
        ):
            transport.upload_grades("HW1", grades, workflow_state="released")
        client.save_grades.assert_called_once_with(
            10, grades, workflow_state="released"
        )


class TestGetStatus:
    def test_maps_status(self):
        transport, client = _make_transport()
        with patch(
            "mograder.moodle_transport.find_assignment",
            return_value={"id": 10, "name": "HW1"},
        ):
            client.get_submission_status.return_value = {
                "status": "submitted",
                "graded": True,
                "grade": "90.00",
                "feedback": "Well done",
            }
            result = transport.get_status("HW1")

        assert isinstance(result, RemoteStatus)
        assert result.status == "submitted"
        assert result.graded is True
        assert result.grade == "90.00"
