"""Moodle transport — wraps MoodleAPIClient to implement the Transport protocol."""

from __future__ import annotations

from pathlib import Path

from mograder.models import RemoteAssignment, RemoteStatus, RemoteSubmission
from mograder.moodle_api import MoodleAPIClient, find_assignment


class MoodleTransport:
    """Transport adapter wrapping :class:`MoodleAPIClient`."""

    def __init__(self, client: MoodleAPIClient, course_id: int):
        self.client = client
        self.course_id = course_id

    def list_assignments(self) -> list[RemoteAssignment]:
        raw = self.client.get_assignments(self.course_id)
        return [
            RemoteAssignment(
                name=a["name"],
                id=str(a["id"]),
                files=[
                    {"filename": f["filename"], "url": f.get("fileurl", "")}
                    for f in a.get("introattachments", [])
                ],
                duedate=a.get("duedate", 0),
                cmid=str(a.get("cmid", "")),
            )
            for a in raw
        ]

    def download_file(self, url: str, dest: Path) -> Path:
        return self.client.download_file(url, dest)

    def submit_file(self, assignment: str, filepath: Path) -> None:
        match = find_assignment(self.client, self.course_id, assignment)
        item_id = self.client.upload_file(filepath)
        self.client.save_submission(match["id"], item_id)
        self.client.submit_for_grading(match["id"])

    def get_submissions(self, assignment: str) -> list[RemoteSubmission]:
        match = find_assignment(self.client, self.course_id, assignment)
        assignment_id = match["id"]
        participants = self.client.list_participants(assignment_id)
        user_map = {p["id"]: p["username"] or f"user_{p['id']}" for p in participants}
        raw = self.client.get_submissions(assignment_id)
        result = []
        for sub in raw:
            username = user_map.get(sub["userid"], f"user_{sub['userid']}")
            py_files = [f for f in sub["files"] if f["filename"].endswith(".py")]
            if py_files:
                result.append(
                    RemoteSubmission(
                        userid=str(sub["userid"]),
                        username=username,
                        filename=py_files[0]["filename"],
                        url=py_files[0]["fileurl"],
                        status=sub.get("status", ""),
                    )
                )
        return result

    def upload_grades(
        self,
        assignment: str,
        grades: list[dict],
        workflow_state: str = "",
    ) -> None:
        match = find_assignment(self.client, self.course_id, assignment)
        self.client.save_grades(match["id"], grades, workflow_state=workflow_state)

    def get_status(self, assignment: str) -> RemoteStatus:
        match = find_assignment(self.client, self.course_id, assignment)
        raw = self.client.get_submission_status(match["id"])
        return RemoteStatus(
            status=raw["status"],
            graded=raw["graded"],
            grade=raw.get("grade"),
            feedback=raw.get("feedback", ""),
        )
