"""Tests for check_cache module."""

from pathlib import Path

import pytest

from mograder.check_cache import (
    format_check_summary,
    is_cache_stale,
    load_cached_results,
    save_cached_results,
)
from mograder.models import CheckResult, NotebookResult


@pytest.fixture
def course_dir(tmp_path):
    return tmp_path


@pytest.fixture
def notebook_result():
    return NotebookResult(
        path=Path("hw1.py"),
        checks=[
            CheckResult(label="Q1: Arrays", status="success"),
            CheckResult(label="Q2: Sorting", status="danger"),
            CheckResult(label="Q3: Search", status="success"),
        ],
        export_ok=True,
        export_error="",
        cell_errors=0,
    )


class TestSaveAndLoad:
    def test_round_trip(self, course_dir, notebook_result):
        save_cached_results(course_dir, "hw1.py", notebook_result, 1000.0)
        cached = load_cached_results(course_dir, "hw1.py")
        assert cached is not None
        assert cached["notebook"] == "hw1.py"
        assert cached["file_mtime"] == 1000.0
        assert len(cached["checks"]) == 3
        assert cached["checks"][0]["label"] == "Q1: Arrays"
        assert cached["checks"][0]["status"] == "success"
        assert cached["export_ok"] is True
        assert cached["cell_errors"] == 0

    def test_load_missing_file(self, course_dir):
        assert load_cached_results(course_dir, "nonexistent.py") is None

    def test_load_corrupt_json(self, course_dir):
        cache_dir = course_dir / ".mograder" / "check_cache"
        cache_dir.mkdir(parents=True)
        (cache_dir / "bad.py.json").write_text("{corrupt")
        assert load_cached_results(course_dir, "bad.py") is None


class TestIsStale:
    def test_fresh(self, course_dir, notebook_result, tmp_path):
        nb = tmp_path / "hw1.py"
        nb.write_text("# notebook")
        mtime = nb.stat().st_mtime
        save_cached_results(course_dir, "hw1.py", notebook_result, mtime)
        cached = load_cached_results(course_dir, "hw1.py")
        assert not is_cache_stale(cached, nb)

    def test_modified(self, course_dir, notebook_result, tmp_path):
        nb = tmp_path / "hw1.py"
        nb.write_text("# notebook")
        # Cache with an older mtime
        save_cached_results(course_dir, "hw1.py", notebook_result, 0.0)
        cached = load_cached_results(course_dir, "hw1.py")
        assert is_cache_stale(cached, nb)

    def test_missing_key(self, tmp_path):
        nb = tmp_path / "hw1.py"
        nb.write_text("# notebook")
        assert is_cache_stale({}, nb)


class TestFormatCheckSummary:
    def test_none_cached(self):
        assert format_check_summary(None, False) == "---"

    def test_all_pass(self):
        cached = {
            "export_ok": True,
            "checks": [
                {"label": "Q1", "status": "success"},
                {"label": "Q2", "status": "success"},
                {"label": "Q3", "status": "success"},
            ],
        }
        assert format_check_summary(cached, False) == "3/3 PASS"

    def test_partial_pass(self):
        cached = {
            "export_ok": True,
            "checks": [
                {"label": "Q1", "status": "success"},
                {"label": "Q2", "status": "danger"},
                {"label": "Q3", "status": "success"},
                {"label": "Q4", "status": "danger"},
                {"label": "Q5", "status": "warn"},
            ],
        }
        assert format_check_summary(cached, False) == "2/5 PASS"

    def test_no_checks(self):
        cached = {"export_ok": True, "checks": []}
        assert format_check_summary(cached, False) == "No checks"

    def test_stale(self):
        cached = {
            "export_ok": True,
            "checks": [{"label": "Q1", "status": "success"}],
        }
        assert format_check_summary(cached, True) == "1/1 PASS (stale)"

    def test_export_failed(self):
        cached = {"export_ok": False}
        assert format_check_summary(cached, False) == "Export failed"
