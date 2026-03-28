"""Tests for late penalty computation."""

import json
from pathlib import Path

from mograder.grading.penalties import (
    compute_penalty,
    load_fetch_metadata,
    resolve_submission_time,
)


class TestComputePenalty:
    def test_on_time(self):
        result = compute_penalty(
            raw_mark=80,
            submission_time=1000,
            due_date=2000,
        )
        assert result.penalty_pct == 0
        assert result.penalised_mark == 80
        assert result.days_late == 0
        assert result.reason == "on time"

    def test_within_grace_period(self):
        # Due at t=1000, grace=5min=300s, submitted at t=1200 (within grace)
        result = compute_penalty(
            raw_mark=80,
            submission_time=1200,
            due_date=1000,
            grace_minutes=5,
        )
        assert result.penalty_pct == 0
        assert result.penalised_mark == 80
        assert result.days_late == 0

    def test_one_day_late(self):
        # Due at t=1000, grace=300s, submitted at t=1000+300+3600 (1h after grace)
        result = compute_penalty(
            raw_mark=100,
            submission_time=1000 + 300 + 3600,
            due_date=1000,
            grace_minutes=5,
            per_day=5.0,
        )
        assert result.days_late == 1
        assert result.penalty_pct == 5.0
        assert result.penalised_mark == 95

    def test_partial_day_rounds_up(self):
        # 1.1 days late → 2 day penalty
        result = compute_penalty(
            raw_mark=100,
            submission_time=1000 + 300 + int(1.1 * 86400),
            due_date=1000,
            grace_minutes=5,
            per_day=5.0,
        )
        assert result.days_late == 2
        assert result.penalty_pct == 10.0
        assert result.penalised_mark == 90

    def test_max_cap(self):
        # 30 days late with 5%/day but max 100%
        result = compute_penalty(
            raw_mark=80,
            submission_time=1000 + 300 + 30 * 86400,
            due_date=1000,
            grace_minutes=5,
            per_day=5.0,
            max_penalty=100.0,
        )
        assert result.penalty_pct == 100.0
        assert result.penalised_mark == 0

    def test_no_deadline(self):
        result = compute_penalty(
            raw_mark=80,
            submission_time=999999,
            due_date=0,
        )
        assert result.penalty_pct == 0
        assert result.penalised_mark == 80
        assert result.reason == "no deadline set"

    def test_zero_mark(self):
        result = compute_penalty(
            raw_mark=0,
            submission_time=1000 + 300 + 86400,
            due_date=1000,
            grace_minutes=5,
            per_day=5.0,
        )
        assert result.penalised_mark == 0
        assert result.penalty_pct == 5.0

    def test_grace_boundary_exact(self):
        # Submitted exactly at grace boundary
        result = compute_penalty(
            raw_mark=100,
            submission_time=1300,  # due=1000, grace=300s
            due_date=1000,
            grace_minutes=5,
        )
        assert result.penalty_pct == 0
        assert result.penalised_mark == 100

    def test_one_second_after_grace(self):
        result = compute_penalty(
            raw_mark=100,
            submission_time=1301,  # 1 second after grace
            due_date=1000,
            grace_minutes=5,
            per_day=5.0,
        )
        assert result.days_late == 1
        assert result.penalty_pct == 5.0

    def test_custom_per_day(self):
        result = compute_penalty(
            raw_mark=100,
            submission_time=1000 + 300 + 86400,
            due_date=1000,
            grace_minutes=5,
            per_day=10.0,
        )
        assert result.penalty_pct == 10.0
        assert result.penalised_mark == 90

    def test_reason_string(self):
        result = compute_penalty(
            raw_mark=100,
            submission_time=1000 + 300 + 2 * 86400,
            due_date=1000,
            grace_minutes=5,
            per_day=5.0,
        )
        assert result.reason == "2 days late, 5.0%/day"

    def test_reason_singular_day(self):
        result = compute_penalty(
            raw_mark=100,
            submission_time=1000 + 300 + 3600,
            due_date=1000,
            grace_minutes=5,
            per_day=5.0,
        )
        assert result.reason == "1 day late, 5.0%/day"


class TestResolveSubmissionTime:
    def test_from_fetch_metadata(self):
        ts = resolve_submission_time(
            "alice",
            "A1",
            Path("/nonexistent"),
            fetch_metadata={"alice": 1234567890},
        )
        assert ts == 1234567890

    def test_from_file_mtime(self, tmp_path):
        submitted_dir = tmp_path / "submitted"
        submitted_dir.mkdir()
        f = submitted_dir / "alice.py"
        f.write_text("pass")
        ts = resolve_submission_time("alice", "A1", submitted_dir)
        assert ts is not None
        assert ts > 0

    def test_missing_student(self, tmp_path):
        ts = resolve_submission_time("nobody", "A1", tmp_path)
        assert ts is None

    def test_metadata_takes_priority(self, tmp_path):
        submitted_dir = tmp_path / "submitted"
        submitted_dir.mkdir()
        f = submitted_dir / "alice.py"
        f.write_text("pass")
        ts = resolve_submission_time(
            "alice",
            "A1",
            submitted_dir,
            fetch_metadata={"alice": 9999},
        )
        assert ts == 9999


class TestLoadFetchMetadata:
    def test_load_valid(self, tmp_path):
        meta = {"alice": 1234, "bob": 5678}
        (tmp_path / ".fetch_metadata.json").write_text(json.dumps(meta))
        result = load_fetch_metadata(tmp_path)
        assert result == meta

    def test_missing_file(self, tmp_path):
        assert load_fetch_metadata(tmp_path) is None

    def test_invalid_json(self, tmp_path):
        (tmp_path / ".fetch_metadata.json").write_text("not json")
        assert load_fetch_metadata(tmp_path) is None
