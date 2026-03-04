from mograder.cells import (
    FEEDBACK_MARKER,
    MARKS_MARKER,
    VERIFICATION_MARKER,
    has_grading_cells,
    inject_grading_cells,
    parse_auto_marks,
    parse_gta_feedback,
    parse_marks_metadata,
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
        '    _marks = {"Q1": 10, "Q2": 15, "Analysis": 75}\n',
        "    # --- display ---\n",
        "    return\n",
    ]


def test_parse_marks_metadata_valid():
    lines = _make_marks_cell_lines()
    result = parse_marks_metadata(lines)
    assert result == {"Q1": 10, "Q2": 15, "Analysis": 75}


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
