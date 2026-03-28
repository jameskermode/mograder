"""Tests for transport protocol data models and factory."""

from mograder.core.models import RemoteAssignment, RemoteStatus, RemoteSubmission
from mograder.transport.transport import Transport


class TestRemoteModels:
    def test_remote_assignment_defaults(self):
        a = RemoteAssignment(name="HW1", id="10")
        assert a.name == "HW1"
        assert a.id == "10"
        assert a.files == []
        assert a.duedate == 0
        assert a.cmid == ""

    def test_remote_assignment_with_files(self):
        files = [{"filename": "hw1.py", "url": "http://example.com/hw1.py"}]
        a = RemoteAssignment(name="HW1", id="10", files=files, duedate=1700000000)
        assert len(a.files) == 1
        assert a.files[0]["filename"] == "hw1.py"
        assert a.duedate == 1700000000

    def test_remote_submission(self):
        s = RemoteSubmission(
            userid="100",
            username="alice",
            filename="solution.py",
            url="http://example.com/solution.py",
        )
        assert s.userid == "100"
        assert s.username == "alice"
        assert s.status == "submitted"

    def test_remote_status_defaults(self):
        st = RemoteStatus()
        assert st.status == "new"
        assert st.graded is False
        assert st.grade is None
        assert st.feedback == ""

    def test_remote_status_graded(self):
        st = RemoteStatus(status="submitted", graded=True, grade="85", feedback="Good")
        assert st.graded is True
        assert st.grade == "85"


class TestTransportProtocol:
    def test_https_transport_is_transport(self):
        from mograder.transport.https_transport import HTTPSTransport

        assert isinstance(HTTPSTransport("http://localhost"), Transport)

    def test_moodle_transport_is_transport(self):
        from unittest.mock import MagicMock

        from mograder.transport.moodle_api import MoodleAPIClient
        from mograder.transport.moodle_transport import MoodleTransport

        client = MagicMock(spec=MoodleAPIClient)
        assert isinstance(MoodleTransport(client, 1), Transport)


class TestMoodleTransportGetSubmissions:
    """MoodleTransport.get_submissions should accept .zip as well as .py."""

    def test_get_submissions_includes_zip(self):
        from unittest.mock import MagicMock

        from mograder.transport.moodle_api import MoodleAPIClient
        from mograder.transport.moodle_transport import MoodleTransport

        client = MagicMock(spec=MoodleAPIClient)
        client.get_assignments.return_value = [
            {"id": 10, "name": "A1", "duedate": 0, "introattachments": []}
        ]
        client.list_participants.return_value = [
            {"id": 100, "username": "alice", "fullname": "Alice"}
        ]
        client.get_submissions.return_value = [
            {
                "userid": 100,
                "status": "submitted",
                "files": [
                    {
                        "filename": "A1.zip",
                        "fileurl": "https://moodle.example.com/file/99",
                        "filesize": 1024,
                        "timemodified": 1700000000,
                    }
                ],
            }
        ]
        transport = MoodleTransport(client, 1)
        subs = transport.get_submissions("A1")
        assert len(subs) == 1
        assert subs[0].username == "alice"
        assert subs[0].filename == "A1.zip"

    def test_get_submissions_prefers_py_over_zip(self):
        """When both .py and .zip are submitted, prefer .py."""
        from unittest.mock import MagicMock

        from mograder.transport.moodle_api import MoodleAPIClient
        from mograder.transport.moodle_transport import MoodleTransport

        client = MagicMock(spec=MoodleAPIClient)
        client.get_assignments.return_value = [
            {"id": 10, "name": "A1", "duedate": 0, "introattachments": []}
        ]
        client.list_participants.return_value = [
            {"id": 100, "username": "alice", "fullname": "Alice"}
        ]
        client.get_submissions.return_value = [
            {
                "userid": 100,
                "status": "submitted",
                "files": [
                    {
                        "filename": "solution.py",
                        "fileurl": "https://moodle.example.com/file/1",
                        "filesize": 256,
                    },
                    {
                        "filename": "A1.zip",
                        "fileurl": "https://moodle.example.com/file/2",
                        "filesize": 1024,
                    },
                ],
            }
        ]
        transport = MoodleTransport(client, 1)
        subs = transport.get_submissions("A1")
        assert len(subs) == 1
        assert subs[0].filename == "solution.py"
