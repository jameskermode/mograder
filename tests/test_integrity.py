"""Tests for integrity checking of check/marks cells."""

from mograder.grading.integrity import (
    check_cell_integrity,
    check_integrity,
    parse_assignment_name,
    parse_cell_hashes,
    validate_cell_hashes,
)
from mograder.grading.cells import _inject_cell_hashes

# -- Minimal notebook templates -----------------------------------------------

_HEADER = """\
import marimo

__generated_with = "0.20.0"
app = marimo.App()

"""

_FOOTER = """\
if __name__ == "__main__":
    app.run()
"""


def _cell(code: str, hide_code: bool = False) -> str:
    """Build a single marimo cell string.

    *code* should be unindented; this function adds the 4-space indent
    required inside the ``def _():`` body.
    """
    decorator = "@app.cell(hide_code=True)" if hide_code else "@app.cell"
    indented = "\n".join(
        ("    " + line) if line.strip() else "" for line in code.splitlines()
    )
    return f"""\
{decorator}
def _():
{indented}
    return


"""


def _notebook(*cells: str) -> str:
    """Assemble cells into a complete marimo notebook."""
    return _HEADER + "".join(cells) + _FOOTER


# -- Source notebooks ----------------------------------------------------------

SOURCE_HOLISTIC = _notebook(
    _cell("import marimo as mo\nfrom mograder.runtime import check", hide_code=True),
    _cell(
        'check(\n    "Q1: Palindrome",\n    [\n        (True, "ok"),\n    ],\n)',
        hide_code=True,
    ),
    _cell(
        'check(\n    "Q2: Counter",\n    [\n        (True, "ok"),\n    ],\n)',
        hide_code=True,
    ),
)

SOURCE_WITH_MARKS = _notebook(
    _cell(
        "import marimo as mo\n"
        "from mograder.runtime import Grader\n"
        "# === MOGRADER: MARKS ===\n"
        '_marks = {"Q1": 10, "Q2": 20}\n'
        "grader = Grader(_marks)\n"
        "check = grader.check",
        hide_code=True,
    ),
    _cell(
        'check(\n    "Q1: Add",\n    [\n        (1 + 1 == 2, "ok"),\n    ],\n)',
        hide_code=True,
    ),
    _cell(
        'check(\n    "Q2: Mul",\n    [\n        (2 * 3 == 6, "ok"),\n    ],\n)',
        hide_code=True,
    ),
)


# -- Tests ---------------------------------------------------------------------


def test_no_tampering():
    """Identical source and submitted → nothing tampered."""
    result = check_integrity(SOURCE_HOLISTIC, SOURCE_HOLISTIC)
    assert result.tampered_checks == []
    assert result.tampered_marks is False


def test_tampered_check_cell():
    """Modified check cell → detected and reinjected."""
    submitted = SOURCE_HOLISTIC.replace(
        '(True, "ok")',
        '(True, "hacked")',
        1,  # only replace first occurrence (Q1)
    )
    result = check_integrity(SOURCE_HOLISTIC, submitted)
    assert "Q1" in result.tampered_checks
    assert "Q2" not in result.tampered_checks
    assert result.tampered_marks is False
    assert '(True, "ok")' in result.fixed_source


def test_tampered_marks_cell():
    """Modified marks cell → detected and reinjected."""
    submitted = SOURCE_WITH_MARKS.replace(
        '_marks = {"Q1": 10, "Q2": 20}',
        '_marks = {"Q1": 100, "Q2": 200}',
    )
    result = check_integrity(SOURCE_WITH_MARKS, submitted)
    assert result.tampered_marks is True
    assert '{"Q1": 10, "Q2": 20}' in result.fixed_source


def test_deleted_check_cell():
    """Removed check cell → detected and reinjected."""
    submitted = _notebook(
        _cell(
            "import marimo as mo\nfrom mograder.runtime import check", hide_code=True
        ),
        _cell(
            'check(\n    "Q1: Palindrome",\n    [\n        (True, "ok"),\n    ],\n)',
            hide_code=True,
        ),
        # Q2 check cell removed
    )
    result = check_integrity(SOURCE_HOLISTIC, submitted)
    assert "Q2" in result.tampered_checks
    assert "Q2: Counter" in result.fixed_source


def test_multiple_tampered():
    """Multiple check cells + marks all tampered → all detected."""
    submitted = (
        SOURCE_WITH_MARKS.replace(
            '_marks = {"Q1": 10, "Q2": 20}',
            '_marks = {"Q1": 999, "Q2": 999}',
        )
        .replace(
            '(1 + 1 == 2, "ok")',
            '(True, "hacked")',
        )
        .replace(
            '(2 * 3 == 6, "ok")',
            '(True, "hacked")',
        )
    )
    result = check_integrity(SOURCE_WITH_MARKS, submitted)
    assert result.tampered_marks is True
    assert "Q1" in result.tampered_checks
    assert "Q2" in result.tampered_checks


def test_no_marks_cell():
    """Holistic notebook (no marks) → only checks compared."""
    submitted = SOURCE_HOLISTIC.replace('(True, "ok")', '(True, "hacked")', 1)
    result = check_integrity(SOURCE_HOLISTIC, submitted)
    assert result.tampered_marks is False
    assert "Q1" in result.tampered_checks


def test_extra_student_cell_not_flagged():
    """Extra cells added by student → not flagged as tampering."""
    submitted = _notebook(
        _cell(
            "import marimo as mo\nfrom mograder.runtime import check", hide_code=True
        ),
        _cell("x = 42"),
        _cell(
            'check(\n    "Q1: Palindrome",\n    [\n        (True, "ok"),\n    ],\n)',
            hide_code=True,
        ),
        _cell(
            'check(\n    "Q2: Counter",\n    [\n        (True, "ok"),\n    ],\n)',
            hide_code=True,
        ),
        _cell("y = x + 1"),
    )
    result = check_integrity(SOURCE_HOLISTIC, submitted)
    assert result.tampered_checks == []
    assert result.tampered_marks is False


# -- Cell integrity tests (release vs submitted) ------------------------------

# Release notebook: solution cells have "# YOUR CODE HERE"
RELEASE_NOTEBOOK = _notebook(
    _cell("import marimo as mo\nfrom mograder.runtime import check", hide_code=True),
    _cell("# Setup cell\nx = 42"),
    _cell("# YOUR CODE HERE\npass"),
    _cell(
        'check(\n    "Q1: Add",\n    [\n        (x == 42, "ok"),\n    ],\n)',
        hide_code=True,
    ),
)


def test_cell_integrity_no_tampering():
    """Release == submitted → no tampered cells."""
    result = check_cell_integrity(RELEASE_NOTEBOOK, RELEASE_NOTEBOOK)
    assert result.tampered_cells == []


def test_cell_integrity_modified_setup():
    """Non-solution cell changed → detected & reinjected."""
    submitted = RELEASE_NOTEBOOK.replace("x = 42", "x = 999")
    result = check_cell_integrity(RELEASE_NOTEBOOK, submitted)
    assert len(result.tampered_cells) > 0
    # The fixed source should contain the original setup code
    assert "x = 42" in result.fixed_source


def test_cell_integrity_solution_changed():
    """Solution cell changed → NOT flagged (student is allowed to modify)."""
    submitted = RELEASE_NOTEBOOK.replace(
        "# YOUR CODE HERE\npass", "# YOUR CODE HERE\nx = 1 + 1"
    )
    result = check_cell_integrity(RELEASE_NOTEBOOK, submitted)
    assert result.tampered_cells == []


def test_cell_integrity_extra_cell():
    """Student added extra cell → not flagged."""
    submitted = _notebook(
        _cell(
            "import marimo as mo\nfrom mograder.runtime import check", hide_code=True
        ),
        _cell("# Setup cell\nx = 42"),
        _cell("# YOUR CODE HERE\npass"),
        _cell("extra = 'student added this'"),
        _cell(
            'check(\n    "Q1: Add",\n    [\n        (x == 42, "ok"),\n    ],\n)',
            hide_code=True,
        ),
    )
    result = check_cell_integrity(RELEASE_NOTEBOOK, submitted)
    assert result.tampered_cells == []


def test_cell_integrity_deleted_cell():
    """Non-solution cell removed → detected & reinjected."""
    submitted = _notebook(
        _cell(
            "import marimo as mo\nfrom mograder.runtime import check", hide_code=True
        ),
        # Setup cell deleted
        _cell("# YOUR CODE HERE\npass"),
        _cell(
            'check(\n    "Q1: Add",\n    [\n        (x == 42, "ok"),\n    ],\n)',
            hide_code=True,
        ),
    )
    result = check_cell_integrity(RELEASE_NOTEBOOK, submitted)
    assert len(result.tampered_cells) > 0
    # The fixed source should have the setup cell reinjected
    assert "x = 42" in result.fixed_source


# -- Hash-based validation tests -----------------------------------------------


_HASH_NOTEBOOK_TEMPLATE = """\
# /// script
# requires-python = ">=3.11"
# ///

import marimo

__generated_with = "0.20.0"
app = marimo.App()


@app.cell
def _():
    x = 1
    return (x,)


@app.cell
def _():
    # YOUR CODE HERE
    pass
    return


@app.cell
def _(x):
    y = x + 1
    return (y,)


if __name__ == "__main__":
    app.run()
"""


def test_parse_assignment_name():
    text = '# mograder-assignment = "demo-hw"\nother stuff'
    assert parse_assignment_name(text) == "demo-hw"


def test_parse_assignment_name_missing():
    assert parse_assignment_name("no metadata here") is None


def test_parse_cell_hashes():
    text = '# mograder-cell-hashes = "abc12345,def67890"\nother'
    assert parse_cell_hashes(text) == ["abc12345", "def67890"]


def test_parse_cell_hashes_missing():
    assert parse_cell_hashes("no hashes") is None


def test_validate_cell_hashes_no_tampering():
    """Unmodified notebook → no warnings."""
    nb_with_hashes = _inject_cell_hashes(_HASH_NOTEBOOK_TEMPLATE)
    assert "mograder-cell-hashes" in nb_with_hashes
    warnings = validate_cell_hashes(nb_with_hashes)
    assert warnings == []


def test_validate_cell_hashes_modified_cell():
    """Modified non-solution cell → warning returned."""
    nb_with_hashes = _inject_cell_hashes(_HASH_NOTEBOOK_TEMPLATE)
    # Modify a non-solution cell
    modified = nb_with_hashes.replace("x = 1", "x = 999")
    warnings = validate_cell_hashes(modified)
    assert len(warnings) == 1
    assert "x = 999" in warnings[0].snippet


def test_validate_cell_hashes_solution_cell_modified():
    """Modified solution cell → no warning (allowed)."""
    nb_with_hashes = _inject_cell_hashes(_HASH_NOTEBOOK_TEMPLATE)
    # Modify the solution cell
    modified = nb_with_hashes.replace(
        "# YOUR CODE HERE\n    pass", "# YOUR CODE HERE\n    x = 42"
    )
    warnings = validate_cell_hashes(modified)
    assert warnings == []


def test_validate_cell_hashes_no_hashes():
    """Notebook without hashes → empty list (graceful degradation)."""
    assert validate_cell_hashes("plain notebook without PEP 723") == []
    assert validate_cell_hashes(_HASH_NOTEBOOK_TEMPLATE) == []
