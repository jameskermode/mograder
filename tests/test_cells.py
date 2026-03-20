from mograder.cells import (
    FEEDBACK_MARKER,
    MARKS_MARKER,
    VERIFICATION_MARKER,
    has_grading_cells,
    inject_grading_cells,
    parse_auto_marks,
    parse_gta_feedback,
    parse_marks_metadata,
    write_gta_feedback,
)
from mograder.models import CheckResult


def _make_notebook_lines():
    """Minimal marimo notebook source."""
    return [
        "import marimo\n",
        "app = marimo.App()\n",
        "\n",
        "@app.cell\n",
        "def _():\n",
        "    x = 1\n",
        "    return\n",
        "\n",
        "\n",
        'if __name__ == "__main__":\n',
        "    app.run()\n",
    ]


def _make_checks():
    return [
        CheckResult("Q1: Computation", "success"),
        CheckResult("Q2: Greeting", "danger"),
        CheckResult("Q3: Analysis", "warn"),
    ]


def test_inject_before_if_name():
    lines = _make_notebook_lines()
    checks = _make_checks()
    result = inject_grading_cells(lines, checks, cell_errors=1)
    text = "".join(result)
    assert VERIFICATION_MARKER in text
    assert FEEDBACK_MARKER in text
    # if __name__ should still be present and come after the injected cells
    assert 'if __name__ == "__main__"' in text
    marker_pos = text.index(VERIFICATION_MARKER)
    name_pos = text.index("if __name__")
    assert marker_pos < name_pos


def test_inject_check_data():
    lines = _make_notebook_lines()
    checks = _make_checks()
    result = inject_grading_cells(lines, checks, cell_errors=3)
    text = "".join(result)
    assert '"Q1: Computation", "PASS"' in text
    assert '"Q2: Greeting", "FAIL"' in text
    assert '"Q3: Analysis", "WAIT"' in text
    assert "_cell_errors = 3" in text


def test_inject_empty_checks_valid_syntax():
    """inject_grading_cells with no checks must produce valid Python."""
    import ast

    lines = _make_notebook_lines()
    # No checks, no marks
    result = inject_grading_cells(lines, [], cell_errors=0)
    text = "".join(result)
    ast.parse(text)  # would raise SyntaxError on `[,]`
    assert VERIFICATION_MARKER in text
    assert "_mograder_checks = []" in text

    # No checks, with marks
    marks = {"Q1": 10, "Q2": 15}
    result = inject_grading_cells(lines, [], cell_errors=0, marks=marks)
    text = "".join(result)
    ast.parse(text)
    assert "_mograder_checks = []" in text
    assert "_mograder_marks" in text


def test_inject_idempotent():
    lines = _make_notebook_lines()
    checks = _make_checks()
    first = inject_grading_cells(lines, checks)
    second = inject_grading_cells(first, checks)
    assert first == second


def test_has_grading_cells():
    lines = _make_notebook_lines()
    assert has_grading_cells(lines) is False
    injected = inject_grading_cells(lines, _make_checks())
    assert has_grading_cells(injected) is True


def test_parse_gta_feedback_ungraded():
    lines = _make_notebook_lines()
    checks = _make_checks()
    injected = inject_grading_cells(lines, checks)
    mark, feedback = parse_gta_feedback(injected)
    assert mark is None
    assert feedback == ""


def test_parse_gta_feedback_graded():
    lines = _make_notebook_lines()
    checks = _make_checks()
    injected = inject_grading_cells(lines, checks)
    # Simulate GTA editing: replace _mark = None with _mark = 65
    text = "".join(injected)
    text = text.replace("_mark = None", "_mark = 65")
    text = text.replace(
        '_feedback = ""', '_feedback = "Good analysis of the DP approach"'
    )
    modified = text.splitlines(keepends=True)
    mark, feedback = parse_gta_feedback(modified)
    assert mark == 65
    assert feedback == "Good analysis of the DP approach"


def test_parse_gta_feedback_no_marker():
    lines = _make_notebook_lines()
    mark, feedback = parse_gta_feedback(lines)
    assert mark is None
    assert feedback == ""


def test_inject_no_if_name():
    """When there's no if __name__ block, cells are appended at the end."""
    lines = [
        "import marimo\n",
        "app = marimo.App()\n",
        "\n",
        "@app.cell\n",
        "def _():\n",
        "    x = 1\n",
        "    return\n",
    ]
    checks = _make_checks()
    result = inject_grading_cells(lines, checks)
    text = "".join(result)
    assert VERIFICATION_MARKER in text
    assert FEEDBACK_MARKER in text


# --- parse_marks_metadata ---


def _make_marks_cell_lines():
    return [
        "@app.cell(hide_code=True)\n",
        "def _(mo):\n",
        f"    {MARKS_MARKER}\n",
        '    _marks = {"Analysis": 75}\n',
        "    # --- display ---\n",
        "    return\n",
    ]


def test_parse_marks_metadata_from_dict():
    lines = _make_marks_cell_lines()
    result = parse_marks_metadata(lines)
    assert result == {"Analysis": 75}


def test_parse_marks_metadata_all_in_dict():
    """All marks must be listed in the _marks dict."""
    lines = [
        f"    {MARKS_MARKER}\n",
        '    _marks = {"Q1": 10, "Q2": 15, "Analysis": 60}\n',
        "    return\n",
    ]
    result = parse_marks_metadata(lines)
    assert result == {"Q1": 10, "Q2": 15, "Analysis": 60}


def test_parse_marks_metadata_no_marker():
    lines = _make_notebook_lines()
    assert parse_marks_metadata(lines) is None


def test_parse_marks_metadata_malformed():
    lines = [
        f"    {MARKS_MARKER}\n",
        "    _marks = not a dict\n",
    ]
    assert parse_marks_metadata(lines) is None


# --- parse_auto_marks ---


def test_parse_auto_marks():
    marks = {"Q1": 10, "Q2": 15, "Analysis": 75}
    checks = [
        CheckResult("Q1: Computation", "success"),
        CheckResult("Q2: Greeting", "danger"),
    ]
    injected = inject_grading_cells(_make_notebook_lines(), checks, marks=marks)
    result = parse_auto_marks(injected)
    assert result == 10  # Only Q1 passed


def test_parse_auto_marks_no_marks():
    """Without marks, parse_auto_marks returns None."""
    checks = _make_checks()
    injected = inject_grading_cells(_make_notebook_lines(), checks)
    assert parse_auto_marks(injected) is None


# --- _build_verification_cell with marks ---


def test_inject_with_marks_has_marks_column():
    marks = {"Q1": 10, "Q2": 20, "Analysis": 70}
    checks = [
        CheckResult("Q1: Computation", "success"),
        CheckResult("Q2: Greeting", "danger"),
    ]
    result = inject_grading_cells(_make_notebook_lines(), checks, marks=marks)
    text = "".join(result)
    assert "_mograder_marks" in text
    assert "| Check | Result | Marks |" in text
    assert "| **Total** |" in text


def test_inject_without_marks_unchanged():
    checks = _make_checks()
    result = inject_grading_cells(_make_notebook_lines(), checks)
    text = "".join(result)
    assert "_mograder_marks" not in text
    assert "| Check | Result |" in text


def test_inject_with_marks_manual_questions():
    """Manual questions (in marks but not in checks) appear in table."""
    marks = {"Q1": 10, "Analysis": 90}
    checks = [CheckResult("Q1: Computation", "success")]
    result = inject_grading_cells(_make_notebook_lines(), checks, marks=marks)
    text = "".join(result)
    assert "Analysis" in text


# --- _build_feedback_cell with marks ---


def test_inject_with_marks_feedback_shows_auto():
    marks = {"Q1": 10, "Q2": 20, "Analysis": 70}
    checks = [
        CheckResult("Q1: Computation", "success"),
        CheckResult("Q2: Greeting", "success"),
    ]
    result = inject_grading_cells(_make_notebook_lines(), checks, marks=marks)
    text = "".join(result)
    # Auto marks should be 10 + 20 = 30
    assert "Auto marks: 30/30" in text
    assert "out of 70" in text


# --- inject_grading_cells with marks auto_mark computation ---


def test_inject_with_marks_auto_mark_computation():
    marks = {"Q1": 10, "Q2": 20, "Q3": 5, "Manual": 65}
    checks = [
        CheckResult("Q1: Computation", "success"),
        CheckResult("Q2: Greeting", "danger"),
        CheckResult("Q3: Analysis", "success"),
    ]
    result = inject_grading_cells(_make_notebook_lines(), checks, marks=marks)
    text = "".join(result)
    # Auto marks: Q1 (10) + Q3 (5) = 15, auto total = 10 + 20 + 5 = 35
    assert "Auto marks: 15/35" in text
    assert "out of 65" in text


# --- parse_gta_feedback still works with marks-aware feedback ---


def test_verification_cell_fractional_marks():
    """Partial checks → fractional earned in generated code."""
    marks = {"Q1": 10, "Q2": 20}
    checks = [
        CheckResult("Q1: Computation", "partial", earned_weight=3.0, total_weight=5.0),
        CheckResult("Q2: Greeting", "success", earned_weight=2.0, total_weight=2.0),
    ]
    result = inject_grading_cells(_make_notebook_lines(), checks, marks=marks)
    text = "".join(result)
    # Should have 4-tuple format with weights
    assert "3.0, 5.0" in text
    assert "2.0, 2.0" in text
    assert "_ew, _tw" in text  # uses the weighted loop variable names


def test_parse_auto_marks_fractional():
    """4-tuple format with weights returns fractional marks."""
    marks = {"Q1": 10, "Q2": 20}
    checks = [
        CheckResult("Q1: Computation", "partial", earned_weight=3.0, total_weight=5.0),
        CheckResult("Q2: Greeting", "success", earned_weight=2.0, total_weight=2.0),
    ]
    injected = inject_grading_cells(_make_notebook_lines(), checks, marks=marks)
    result = parse_auto_marks(injected)
    # Q1: round(10*3/5,1)=6.0, Q2: round(20*2/2,1)=20.0
    assert result == 26.0


def test_parse_auto_marks_backward_compat():
    """2-tuple format (weight 0,0) still works — binary PASS/FAIL."""
    marks = {"Q1": 10, "Q2": 20}
    checks = [
        CheckResult("Q1: Computation", "success"),  # weights default 0,0
        CheckResult("Q2: Greeting", "danger"),
    ]
    injected = inject_grading_cells(_make_notebook_lines(), checks, marks=marks)
    result = parse_auto_marks(injected)
    assert result == 10.0  # Only Q1 passed


def test_parse_gta_feedback_with_marks():
    marks = {"Q1": 10, "Analysis": 90}
    checks = [CheckResult("Q1: Computation", "success")]
    injected = inject_grading_cells(_make_notebook_lines(), checks, marks=marks)
    text = "".join(injected)
    # Simulate GTA grading
    text = text.replace("_mark = None", "_mark = 70")
    text = text.replace('_feedback = ""', '_feedback = "Solid analysis"')
    modified = text.splitlines(keepends=True)
    mark, feedback = parse_gta_feedback(modified)
    assert mark == 70
    assert feedback == "Solid analysis"


# --- triple-quoted feedback parsing ---


def test_parse_gta_feedback_triple_quoted():
    """Triple-quoted multiline feedback parses correctly."""
    lines = _make_notebook_lines()
    checks = _make_checks()
    injected = inject_grading_cells(lines, checks)
    text = "".join(injected)
    text = text.replace("_mark = None", "_mark = 80")
    text = text.replace(
        '_feedback = ""',
        '_feedback = """Line one.\nLine two.\nLine three."""',
    )
    modified = text.splitlines(keepends=True)
    mark, feedback = parse_gta_feedback(modified)
    assert mark == 80
    assert "Line one." in feedback
    assert "Line two." in feedback
    assert "Line three." in feedback


def test_parse_gta_feedback_single_line_still_works():
    """Backward compat: single-line strings still parse correctly."""
    lines = _make_notebook_lines()
    checks = _make_checks()
    injected = inject_grading_cells(lines, checks)
    text = "".join(injected)
    text = text.replace("_mark = None", "_mark = 50")
    text = text.replace('_feedback = ""', '_feedback = "Simple feedback"')
    modified = text.splitlines(keepends=True)
    mark, feedback = parse_gta_feedback(modified)
    assert mark == 50
    assert feedback == "Simple feedback"


# --- write_gta_feedback ---


def test_write_gta_feedback(tmp_path):
    """write_gta_feedback writes mark + multiline feedback correctly."""
    lines = _make_notebook_lines()
    checks = _make_checks()
    injected = inject_grading_cells(lines, checks)
    nb_path = tmp_path / "test.py"
    nb_path.write_text("".join(injected))

    write_gta_feedback(nb_path, 75, "Good work.\nNeeds improvement on Q2.")

    modified = nb_path.read_text().splitlines(keepends=True)
    mark, feedback = parse_gta_feedback(modified)
    assert mark == 75
    assert "Good work." in feedback
    assert "Needs improvement on Q2." in feedback


def test_write_gta_feedback_roundtrip(tmp_path):
    """Write, read, overwrite, read again — single-line upgrades to triple-quote."""
    lines = _make_notebook_lines()
    checks = _make_checks()
    injected = inject_grading_cells(lines, checks)
    nb_path = tmp_path / "test.py"
    nb_path.write_text("".join(injected))

    # First write
    write_gta_feedback(nb_path, 60, "Initial feedback")
    mark, feedback = parse_gta_feedback(nb_path.read_text().splitlines(keepends=True))
    assert mark == 60
    assert feedback == "Initial feedback"

    # Overwrite with multiline
    write_gta_feedback(nb_path, 85, "Updated.\nMultiline now.")
    mark, feedback = parse_gta_feedback(nb_path.read_text().splitlines(keepends=True))
    assert mark == 85
    assert "Updated." in feedback
    assert "Multiline now." in feedback


def test_write_gta_feedback_no_marker(tmp_path):
    """Raises ValueError on a file without the feedback marker."""
    import pytest

    nb_path = tmp_path / "plain.py"
    nb_path.write_text("x = 1\n")

    with pytest.raises(ValueError, match="MOGRADER"):
        write_gta_feedback(nb_path, 50, "feedback")


def test_write_gta_feedback_none_mark(tmp_path):
    """Writing None mark resets to ungraded state."""
    lines = _make_notebook_lines()
    checks = _make_checks()
    injected = inject_grading_cells(lines, checks)
    nb_path = tmp_path / "test.py"
    nb_path.write_text("".join(injected))

    # First set a mark
    write_gta_feedback(nb_path, 70, "Some feedback")
    # Then reset
    write_gta_feedback(nb_path, None, "")
    mark, feedback = parse_gta_feedback(nb_path.read_text().splitlines(keepends=True))
    assert mark is None


# --- source_check_keys regression ---


def test_inject_source_check_keys_uses_full_denominator():
    """When source_check_keys is provided, auto denominator reflects all
    auto-graded questions even if student checks are incomplete (mo.stop
    guards prevented some from running).

    Regression test: without source_check_keys, a student who fails
    everything would show Auto: 0/15 instead of 0/40 because only the
    checks that ran (Q2) would be counted.
    """
    marks = {"Q1": 10, "Q2": 15, "Q3": 15, "Analysis": 60}
    # Student only has Q2 check result (Q1 and Q3 stopped by mo.stop guards)
    student_checks = [CheckResult("Q2: Finite differences", "danger")]
    # Source notebook has all three check() calls
    source_keys = {"Q1", "Q2", "Q3"}

    result = inject_grading_cells(
        _make_notebook_lines(),
        student_checks,
        marks=marks,
        source_check_keys=source_keys,
    )
    text = "".join(result)
    # Auto total should be Q1+Q2+Q3 = 40, NOT just Q2 = 15
    assert "Auto marks: 0/40" in text
    # Manual should be Analysis = 60
    assert "out of 60" in text


def test_inject_without_source_check_keys_falls_back_to_student_checks():
    """Without source_check_keys, falls back to inferring from student checks."""
    marks = {"Q1": 10, "Q2": 15, "Analysis": 75}
    checks = [
        CheckResult("Q1: Array creation", "success"),
        CheckResult("Q2: Finite differences", "danger"),
    ]
    result = inject_grading_cells(_make_notebook_lines(), checks, marks=marks)
    text = "".join(result)
    # Both Q1 and Q2 are in student checks, so auto total = 25
    assert "Auto marks: 10/25" in text
