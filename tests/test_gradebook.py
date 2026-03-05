"""Tests for mograder.gradebook — SQLite gradebook."""

from mograder.cells import inject_grading_cells
from mograder.gradebook import Gradebook
from mograder.models import CheckResult


def _minimal_notebook() -> str:
    return (
        "import marimo\n"
        "app = marimo.App()\n"
        "\n"
        "if __name__ == '__main__':\n"
        "    app.run()\n"
    )


def _make_autograded(graded=False, mark=65) -> str:
    lines = _minimal_notebook().splitlines(keepends=True)
    checks = [CheckResult("Q1: Foo", "success")]
    injected = inject_grading_cells(lines, checks)
    text = "".join(injected)
    if graded:
        text = text.replace("_mark = None", f"_mark = {mark}")
        text = text.replace('_feedback = ""', '_feedback = "Good work"')
    return text


def _make_autograded_with_marks(graded=False, manual_mark=70) -> str:
    lines = _minimal_notebook().splitlines(keepends=True)
    checks = [CheckResult("Q1: Computation", "success")]
    marks = {"Q1": 10, "Analysis": 90}
    injected = inject_grading_cells(lines, checks, marks=marks)
    text = "".join(injected)
    if graded:
        text = text.replace("_mark = None", f"_mark = {manual_mark}")
        text = text.replace('_feedback = ""', '_feedback = "Solid analysis"')
    return text


# --- Gradebook lifecycle ---


def test_gradebook_create_and_close(tmp_path):
    db = tmp_path / "test.db"
    gb = Gradebook(db)
    assert gb.is_new
    gb.close()
    assert db.exists()


def test_gradebook_context_manager(tmp_path):
    db = tmp_path / "test.db"
    with Gradebook(db) as gb:
        assert gb.is_new
    assert db.exists()


def test_gradebook_not_new_on_reopen(tmp_path):
    db = tmp_path / "test.db"
    with Gradebook(db):
        pass
    with Gradebook(db) as gb:
        assert not gb.is_new


# --- Assignments ---


def test_upsert_assignment(tmp_path):
    with Gradebook(tmp_path / "test.db") as gb:
        gb.upsert_assignment("hw1", max_mark=100)
        a = gb.get_assignment("hw1")
        assert a is not None
        assert a["name"] == "hw1"
        assert a["max_mark"] == 100
        assert a["marks_metadata"] is None


def test_upsert_assignment_with_marks(tmp_path):
    with Gradebook(tmp_path / "test.db") as gb:
        marks = {"Q1": 10, "Q2": 90}
        gb.upsert_assignment("hw1", max_mark=100, marks_metadata=marks)
        a = gb.get_assignment("hw1")
        assert a["marks_metadata"] == marks


def test_upsert_assignment_update(tmp_path):
    with Gradebook(tmp_path / "test.db") as gb:
        gb.upsert_assignment("hw1", max_mark=50)
        gb.upsert_assignment("hw1", max_mark=100)
        a = gb.get_assignment("hw1")
        assert a["max_mark"] == 100


def test_get_assignment_missing(tmp_path):
    with Gradebook(tmp_path / "test.db") as gb:
        assert gb.get_assignment("missing") is None


# --- Submissions ---


def test_save_autograde_result(tmp_path):
    with Gradebook(tmp_path / "test.db") as gb:
        gb.upsert_assignment("hw1")
        checks = [CheckResult("Q1: Test", "success")]
        gb.save_autograde_result("hw1", "alice", checks, cell_errors=1, auto_mark=10)

        sub = gb.get_submission("hw1", "alice")
        assert sub is not None
        assert sub["auto_mark"] == 10
        assert sub["cell_errors"] == 1
        assert sub["manual_mark"] is None
        assert sub["total_mark"] is None
        assert len(sub["check_results"]) == 1
        assert sub["check_results"][0]["label"] == "Q1: Test"


def test_save_autograde_preserves_manual_grade(tmp_path):
    """Re-autograde should preserve existing manual_mark and feedback."""
    with Gradebook(tmp_path / "test.db") as gb:
        gb.upsert_assignment("hw1")
        checks = [CheckResult("Q1: Test", "success")]
        gb.save_autograde_result("hw1", "alice", checks, auto_mark=10)
        gb.save_manual_grade("hw1", "alice", 70, "Good")

        # Re-autograde
        gb.save_autograde_result("hw1", "alice", checks, auto_mark=15)
        sub = gb.get_submission("hw1", "alice")
        assert sub["auto_mark"] == 15
        assert sub["manual_mark"] == 70
        assert sub["total_mark"] == 85
        assert sub["feedback"] == "Good"


def test_save_manual_grade(tmp_path):
    with Gradebook(tmp_path / "test.db") as gb:
        gb.upsert_assignment("hw1")
        checks = [CheckResult("Q1: Test", "success")]
        gb.save_autograde_result("hw1", "alice", checks, auto_mark=10)
        gb.save_manual_grade("hw1", "alice", 60, "Nice work")

        sub = gb.get_submission("hw1", "alice")
        assert sub["manual_mark"] == 60
        assert sub["total_mark"] == 70
        assert sub["feedback"] == "Nice work"
        assert sub["graded_at"] is not None


def test_save_manual_grade_holistic(tmp_path):
    """Without auto_mark, total = manual_mark."""
    with Gradebook(tmp_path / "test.db") as gb:
        gb.upsert_assignment("hw1")
        checks = [CheckResult("Q1: Test", "success")]
        gb.save_autograde_result("hw1", "alice", checks)
        gb.save_manual_grade("hw1", "alice", 75, "")

        sub = gb.get_submission("hw1", "alice")
        assert sub["total_mark"] == 75


def test_save_manual_grade_no_prior_submission(tmp_path):
    """Manual grade for a student not yet autograded."""
    with Gradebook(tmp_path / "test.db") as gb:
        gb.upsert_assignment("hw1")
        gb.save_manual_grade("hw1", "alice", 80, "Great")

        sub = gb.get_submission("hw1", "alice")
        assert sub["total_mark"] == 80
        assert sub["manual_mark"] == 80


def test_save_manual_grade_none(tmp_path):
    """Setting manual_mark to None clears the grade."""
    with Gradebook(tmp_path / "test.db") as gb:
        gb.upsert_assignment("hw1")
        checks = [CheckResult("Q1: Test", "success")]
        gb.save_autograde_result("hw1", "alice", checks, auto_mark=10)
        gb.save_manual_grade("hw1", "alice", None)

        sub = gb.get_submission("hw1", "alice")
        assert sub["total_mark"] is None


def test_get_submission_missing(tmp_path):
    with Gradebook(tmp_path / "test.db") as gb:
        assert gb.get_submission("hw1", "nobody") is None


def test_list_submissions(tmp_path):
    with Gradebook(tmp_path / "test.db") as gb:
        gb.upsert_assignment("hw1")
        checks = [CheckResult("Q1", "success")]
        gb.save_autograde_result("hw1", "bob", checks, auto_mark=5)
        gb.save_autograde_result("hw1", "alice", checks, auto_mark=10)

        subs = gb.list_submissions("hw1")
        assert len(subs) == 2
        assert subs[0]["student"] == "alice"
        assert subs[1]["student"] == "bob"


def test_save_autograde_with_tampered(tmp_path):
    with Gradebook(tmp_path / "test.db") as gb:
        gb.upsert_assignment("hw1")
        checks = [CheckResult("Q1", "success")]
        gb.save_autograde_result("hw1", "alice", checks, tampered=["check(Q1)"])

        sub = gb.get_submission("hw1", "alice")
        assert sub["tampered"] == ["check(Q1)"]


# --- Grade collection ---


def test_collect_grades(tmp_path):
    with Gradebook(tmp_path / "test.db") as gb:
        gb.upsert_assignment("hw1")
        checks = [CheckResult("Q1", "success")]
        gb.save_autograde_result("hw1", "alice", checks, auto_mark=10)
        gb.save_manual_grade("hw1", "alice", 60, "Good")
        gb.save_autograde_result("hw1", "bob", checks, auto_mark=5)

        grades = gb.collect_grades("hw1")
        assert len(grades) == 2
        alice = next(g for g in grades if g["student"] == "alice")
        assert alice["mark"] == 70
        assert alice["auto_mark"] == 10
        assert alice["feedback"] == "Good"
        bob = next(g for g in grades if g["student"] == "bob")
        assert bob["mark"] is None


def test_collect_student_marks(tmp_path):
    with Gradebook(tmp_path / "test.db") as gb:
        gb.upsert_assignment("hw1")
        gb.upsert_assignment("hw2")
        checks = [CheckResult("Q1", "success")]
        gb.save_autograde_result("hw1", "alice", checks, auto_mark=10)
        gb.save_manual_grade("hw1", "alice", 60)
        gb.save_autograde_result("hw2", "alice", checks, auto_mark=20)
        gb.save_manual_grade("hw2", "alice", 30)

        result = gb.collect_student_marks(["hw1", "hw2"])
        assert result["alice"]["hw1"] == 70
        assert result["alice"]["hw2"] == 50


def test_count_graded(tmp_path):
    with Gradebook(tmp_path / "test.db") as gb:
        gb.upsert_assignment("hw1")
        checks = [CheckResult("Q1", "success")]
        gb.save_autograde_result("hw1", "alice", checks)
        gb.save_autograde_result("hw1", "bob", checks)
        gb.save_manual_grade("hw1", "alice", 80)

        assert gb.count_graded("hw1") == 1


# --- Migration ---


def test_import_from_py(tmp_path):
    auto_dir = tmp_path / "autograded" / "hw1"
    auto_dir.mkdir(parents=True)
    (auto_dir / "alice.py").write_text(_make_autograded(graded=True, mark=72))
    (auto_dir / "bob.py").write_text(_make_autograded(graded=False))

    with Gradebook(tmp_path / "test.db") as gb:
        gb.upsert_assignment("hw1")
        count = gb.import_from_py("hw1", auto_dir)
        assert count == 2

        alice = gb.get_submission("hw1", "alice")
        assert alice is not None
        assert alice["manual_mark"] == 72
        assert alice["feedback"] == "Good work"

        bob = gb.get_submission("hw1", "bob")
        assert bob is not None
        assert bob["manual_mark"] is None


def test_import_from_py_with_marks(tmp_path):
    auto_dir = tmp_path / "autograded" / "hw1"
    auto_dir.mkdir(parents=True)
    (auto_dir / "alice.py").write_text(
        _make_autograded_with_marks(graded=True, manual_mark=70)
    )

    with Gradebook(tmp_path / "test.db") as gb:
        marks = {"Q1": 10, "Analysis": 90}
        gb.upsert_assignment("hw1", max_mark=100, marks_metadata=marks)
        gb.import_from_py("hw1", auto_dir, marks_metadata=marks)

        alice = gb.get_submission("hw1", "alice")
        assert alice["auto_mark"] == 10
        assert alice["manual_mark"] == 70
        assert alice["total_mark"] == 80


def test_import_from_py_empty_dir(tmp_path):
    with Gradebook(tmp_path / "test.db") as gb:
        gb.upsert_assignment("hw1")
        count = gb.import_from_py("hw1", tmp_path / "nonexistent")
        assert count == 0


def test_import_preserves_existing(tmp_path):
    """Import should not overwrite existing manual grades."""
    auto_dir = tmp_path / "autograded" / "hw1"
    auto_dir.mkdir(parents=True)
    (auto_dir / "alice.py").write_text(_make_autograded(graded=True, mark=72))

    with Gradebook(tmp_path / "test.db") as gb:
        gb.upsert_assignment("hw1")
        gb.save_manual_grade("hw1", "alice", 90, "Excellent")
        gb.import_from_py("hw1", auto_dir)

        alice = gb.get_submission("hw1", "alice")
        # Existing manual grade should be preserved
        assert alice["manual_mark"] == 90
        assert alice["feedback"] == "Excellent"
