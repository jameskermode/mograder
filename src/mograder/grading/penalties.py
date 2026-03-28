"""Late submission penalty computation."""

import json
import math
from dataclasses import dataclass

from pathlib import Path


@dataclass
class PenaltyResult:
    """Result of computing a late penalty."""

    raw_mark: float
    penalty_pct: float
    penalised_mark: float
    days_late: int
    reason: str


def compute_penalty(
    raw_mark: float,
    submission_time: int,
    due_date: int,
    grace_minutes: int = 5,
    per_day: float = 5.0,
    max_penalty: float = 100.0,
) -> PenaltyResult:
    """Compute late penalty for a submission.

    Args:
        raw_mark: The raw mark before penalties.
        submission_time: Unix timestamp of submission.
        due_date: Unix timestamp of deadline.
        grace_minutes: Grace period in minutes (accounts for clock skew).
        per_day: Percentage points deducted per calendar day late.
        max_penalty: Maximum penalty percentage (100 = can lose all marks).

    Returns:
        PenaltyResult with the computed penalty.
    """
    if due_date == 0:
        return PenaltyResult(
            raw_mark=raw_mark,
            penalty_pct=0,
            penalised_mark=raw_mark,
            days_late=0,
            reason="no deadline set",
        )

    grace_seconds = grace_minutes * 60
    effective_deadline = due_date + grace_seconds
    late_seconds = submission_time - effective_deadline

    if late_seconds <= 0:
        return PenaltyResult(
            raw_mark=raw_mark,
            penalty_pct=0,
            penalised_mark=raw_mark,
            days_late=0,
            reason="on time",
        )

    # Ceil to whole calendar days
    days_late = math.ceil(late_seconds / 86400)
    penalty_pct = min(days_late * per_day, max_penalty)
    deduction = raw_mark * penalty_pct / 100
    penalised_mark = max(raw_mark - deduction, 0)
    # Round to nearest integer
    penalised_mark = round(penalised_mark)

    day_word = "day" if days_late == 1 else "days"
    reason = f"{days_late} {day_word} late, {per_day}%/day"

    return PenaltyResult(
        raw_mark=raw_mark,
        penalty_pct=penalty_pct,
        penalised_mark=penalised_mark,
        days_late=days_late,
        reason=reason,
    )


def resolve_submission_time(
    student: str,
    assignment: str,
    submitted_dir: Path,
    fetch_metadata: dict | None = None,
) -> int | None:
    """Resolve the submission timestamp for a student.

    Checks (in order):
    1. ``.fetch_metadata.json`` sidecar (from ``do_fetch_submissions``)
    2. File modification time of the submitted notebook

    Returns Unix timestamp, or None if no submission found.
    """
    # Try fetch_metadata.json sidecar
    if fetch_metadata is not None:
        ts = fetch_metadata.get(student)
        if ts is not None:
            return int(ts)

    # Fallback: file mtime
    submitted_file = submitted_dir / f"{student}.py"
    if submitted_file.is_file():
        return int(submitted_file.stat().st_mtime)

    return None


def load_fetch_metadata(submitted_dir: Path) -> dict | None:
    """Load ``.fetch_metadata.json`` from a submitted directory.

    Returns ``{username: timemodified}`` dict, or None if not found.
    """
    meta_path = submitted_dir / ".fetch_metadata.json"
    if not meta_path.is_file():
        return None
    try:
        data = json.loads(meta_path.read_text())
        return data
    except (json.JSONDecodeError, OSError):
        return None
