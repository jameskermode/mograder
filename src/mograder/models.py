"""Data models for mograder."""

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class CheckResult:
    """Result of a single check() callout."""

    label: str
    status: str  # "success", "danger", "warn", or "error"
    details: str = ""


@dataclass
class NotebookResult:
    """Aggregated results for one submitted notebook."""

    path: Path
    checks: list[CheckResult] = field(default_factory=list)
    export_ok: bool = True
    export_error: str = ""
    cell_errors: int = 0
    html_path: Path | None = None
    tampered: list[str] = field(default_factory=list)


@dataclass
class RemoteAssignment:
    """An assignment available on a remote server (Moodle or HTTPS)."""

    name: str
    id: str
    files: list[dict] = field(default_factory=list)
    duedate: int = 0
    cmid: str = ""


@dataclass
class RemoteSubmission:
    """A student submission fetched from a remote server."""

    userid: str
    username: str
    filename: str
    url: str
    status: str = "submitted"


@dataclass
class RemoteStatus:
    """Submission status for the current user on a remote server."""

    status: str = "new"
    graded: bool = False
    grade: str | None = None
    feedback: str = ""
