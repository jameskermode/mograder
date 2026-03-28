"""Check result caching for student validation runs and submission tracking."""

from __future__ import annotations

import json
from pathlib import Path

from mograder.core.models import NotebookResult


def _cache_path(course_dir: Path, notebook_name: str) -> Path:
    return course_dir / ".mograder" / "check_cache" / f"{notebook_name}.json"


def load_cached_results(course_dir: Path, notebook_name: str) -> dict | None:
    """Load cached check results for a notebook.

    Returns dict with keys: notebook, file_mtime, checks, export_ok,
    export_error, cell_errors.  Returns None if no cache or corrupt.
    """
    path = _cache_path(course_dir, notebook_name)
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def save_cached_results(
    course_dir: Path,
    notebook_name: str,
    result: NotebookResult,
    file_mtime: float,
) -> None:
    """Persist check results to the cache directory."""
    path = _cache_path(course_dir, notebook_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "notebook": notebook_name,
        "file_mtime": file_mtime,
        "checks": [
            {"label": c.label, "status": c.status, "details": c.details}
            for c in result.checks
        ],
        "export_ok": result.export_ok,
        "export_error": result.export_error,
        "cell_errors": result.cell_errors,
    }
    path.write_text(json.dumps(data))


def is_cache_stale(cached: dict, notebook_path: Path) -> bool:
    """Return True if the notebook has been modified since the cached run."""
    try:
        return notebook_path.stat().st_mtime > cached["file_mtime"]
    except (KeyError, OSError):
        return True


def _submission_path(course_dir: Path, notebook_name: str) -> Path:
    return course_dir / ".mograder" / "submissions" / f"{notebook_name}.json"


def load_submission_record(course_dir: Path, notebook_name: str) -> dict | None:
    """Load submission record. Returns dict with 'file_mtime' or None."""
    path = _submission_path(course_dir, notebook_name)
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def save_submission_record(
    course_dir: Path, notebook_name: str, file_mtime: float
) -> None:
    """Record that a notebook was submitted at the given file mtime."""
    path = _submission_path(course_dir, notebook_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"file_mtime": file_mtime}))


def get_submission_status(course_dir: Path, notebook_path: Path) -> str:
    """Return status string for a notebook: Downloaded, Submitted, or Modified."""
    record = load_submission_record(course_dir, notebook_path.name)
    if record is None:
        return "Downloaded"
    try:
        if notebook_path.stat().st_mtime > record["file_mtime"]:
            return "Modified"
    except (KeyError, OSError):
        return "Downloaded"
    return "Submitted"


def format_check_summary(cached: dict | None, stale: bool) -> str:
    """Return a compact display string for the Checks column."""
    if cached is None:
        return "---"
    if not cached.get("export_ok", True):
        return "Export failed"
    checks = cached.get("checks", [])
    if not checks:
        return "No checks"
    passed = sum(1 for c in checks if c["status"] == "success")
    total = len(checks)
    summary = f"{passed}/{total} PASS"
    if stale:
        summary += " (stale)"
    return summary
