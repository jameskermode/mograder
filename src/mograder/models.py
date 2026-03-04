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
