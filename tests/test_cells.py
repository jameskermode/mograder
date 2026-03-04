from mograder.cells import (
    FEEDBACK_MARKER,
    VERIFICATION_MARKER,
    has_grading_cells,
    inject_grading_cells,
    parse_gta_feedback,
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
    name_pos = text.index('if __name__')
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
    text = text.replace('_feedback = ""', '_feedback = "Good analysis of the DP approach"')
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
