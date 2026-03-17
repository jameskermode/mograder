"""Transport protocol for remote assignment servers."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

from mograder.models import RemoteAssignment, RemoteStatus, RemoteSubmission


class TransportError(Exception):
    """Raised when a transport operation fails."""


@runtime_checkable
class Transport(Protocol):
    """Protocol for fetching/submitting assignments from a remote server."""

    def list_assignments(self) -> list[RemoteAssignment]: ...

    def download_file(self, url: str, dest: Path) -> Path: ...

    def submit_file(self, assignment: str, filepath: Path) -> None: ...

    def get_submissions(self, assignment: str) -> list[RemoteSubmission]: ...

    def upload_grades(
        self,
        assignment: str,
        grades: list[dict],
        workflow_state: str = "",
    ) -> None: ...

    def get_status(self, assignment: str) -> RemoteStatus: ...


def build_transport(config) -> Transport:
    """Build a Transport from a MograderConfig.

    Reads ``config.transport`` to decide which implementation to use.
    """
    transport_type = getattr(config, "transport", "moodle")

    if transport_type == "https":
        from mograder.auth import load_cached_https_token
        from mograder.https_transport import HTTPSTransport

        url = getattr(config, "https_url", None)
        if not url:
            raise TransportError(
                "HTTPS transport selected but no URL configured. "
                "Set [https] url in mograder.toml"
            )
        # Token resolution: config > env var > cache
        token = getattr(config, "https_token", None) or ""
        user = ""
        if not token:
            import os

            token = os.environ.get("MOGRADER_HTTPS_TOKEN", "")
        if not token:
            cached = load_cached_https_token(url)
            if cached:
                token = cached["token"]
                user = cached.get("user", "")
        if token and not user and ":" in token:
            user = token.split(":", 1)[0]
        return HTTPSTransport(url, user=user, token=token)

    if transport_type == "moodle":
        from mograder.moodle_api import MoodleAPIClient, load_cached_token
        from mograder.moodle_transport import MoodleTransport

        url = getattr(config, "moodle_url", None)
        course_id = getattr(config, "moodle_course_id", None)
        if not url or not course_id:
            raise TransportError(
                "Moodle transport selected but URL or course_id not configured. "
                "Set [moodle] url and course_id in mograder.toml"
            )
        cached = load_cached_token(url)
        if not cached:
            raise TransportError(
                "No Moodle token found. Run 'mograder moodle login' first."
            )
        client = MoodleAPIClient(url, cached["token"])
        return MoodleTransport(client, course_id)

    raise TransportError(f"Unknown transport type: {transport_type!r}")
