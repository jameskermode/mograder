from mograder.cells import MARKS_MARKER
from mograder.markers import (
    SOLUTION_BEGIN,
    SOLUTION_END,
    augment_check_function,
    count_markers,
    has_marks_cell,
    inject_state_cell,
    process_file,
    strip_solutions,
    transform_marks_cell,
    validate_markers,
)


# --- validate_markers ---


def test_validate_valid_markers():
    lines = [
        f"    {SOLUTION_BEGIN}\n",
        "    x = 1\n",
        f"    {SOLUTION_END}\n",
    ]
    assert validate_markers(lines, "test.py") == []


def test_validate_nested_solution():
    lines = [
        f"    {SOLUTION_BEGIN}\n",
        f"    {SOLUTION_BEGIN}\n",
        f"    {SOLUTION_END}\n",
    ]
    errors = validate_markers(lines, "test.py")
    assert len(errors) == 1
    assert "nested" in errors[0]


def test_validate_orphan_end():
    lines = [f"    {SOLUTION_END}\n"]
    errors = validate_markers(lines, "test.py")
    assert len(errors) == 1
    assert "without matching" in errors[0]


def test_validate_unclosed_solution():
    lines = [f"    {SOLUTION_BEGIN}\n", "    x = 1\n"]
    errors = validate_markers(lines, "test.py")
    assert len(errors) == 1
    assert "unclosed" in errors[0]


# --- strip_solutions ---


def test_strip_solutions_replaces_with_placeholder():
    lines = [
        "    x = 0\n",
        f"    {SOLUTION_BEGIN}\n",
        "    x = 42\n",
        f"    {SOLUTION_END}\n",
        "    print(x)\n",
    ]
    result = strip_solutions(lines)
    assert "    # YOUR CODE HERE\n" in result
    assert "    pass\n" in result
    assert "    x = 42\n" not in result
    assert "    x = 0\n" in result
    assert "    print(x)\n" in result


def test_strip_solutions_preserves_indentation():
    lines = [
        f"        {SOLUTION_BEGIN}\n",
        "        deep = True\n",
        f"        {SOLUTION_END}\n",
    ]
    result = strip_solutions(lines)
    assert "        # YOUR CODE HERE\n" in result
    assert "        pass\n" in result


def test_strip_nonmarker_code_unchanged():
    lines = ["x = 1\n", "y = 2\n", "print(x + y)\n"]
    assert strip_solutions(lines) == lines


# --- count_markers ---


def test_count_markers():
    lines = [
        f"    {SOLUTION_BEGIN}\n",
        f"    {SOLUTION_END}\n",
        f"    {SOLUTION_BEGIN}\n",
        f"    {SOLUTION_END}\n",
    ]
    assert count_markers(lines) == 2


# --- process_file ---


def test_process_file_writes_output(tmp_path, fixtures_dir):
    source = fixtures_dir / "staff_notebook.py"
    out_dir = tmp_path / "release"
    assert process_file(source, out_dir) is True
    dest = out_dir / source.name
    assert dest.exists()
    content = dest.read_text()
    assert "# YOUR CODE HERE" in content
    assert SOLUTION_BEGIN not in content


def test_process_file_dry_run(tmp_path, fixtures_dir, capsys):
    source = fixtures_dir / "staff_notebook.py"
    out_dir = tmp_path / "release"
    assert process_file(source, out_dir, dry_run=True) is True
    assert not (out_dir / source.name).exists()
    captured = capsys.readouterr()
    assert "DRY-RUN" in captured.out


def test_process_file_validate_only(fixtures_dir, capsys):
    source = fixtures_dir / "staff_notebook.py"
    assert process_file(source, None, validate_only=True) is True
    captured = capsys.readouterr()
    assert "VALID" in captured.out


def test_process_file_no_markers(tmp_path, capsys):
    source = tmp_path / "plain.py"
    source.write_text("x = 1\n")
    assert process_file(source, tmp_path) is True
    captured = capsys.readouterr()
    assert "SKIP" in captured.out


def test_process_file_invalid_markers(tmp_path):
    source = tmp_path / "bad.py"
    source.write_text(f"    {SOLUTION_BEGIN}\n")  # unclosed
    assert process_file(source, tmp_path) is False


# --- marks cell transforms ---


def _make_notebook_with_marks():
    """Minimal marimo notebook with check function and marks cell."""
    return [
        "import marimo\n",
        "app = marimo.App()\n",
        "\n",
        "@app.cell\n",
        "def _():\n",
        "    import marimo as mo\n",
        "    return (mo,)\n",
        "\n",
        "\n",
        "@app.cell(hide_code=True)\n",
        "def _(mo):\n",
        "    def check(label, checks):\n",
        '        """Run checks."""\n',
        "        failures = [msg for ok, msg in checks if not ok]\n",
        "        if not checks:\n",
        '            return mo.callout(mo.md(f"**{label}** — waiting"), kind="warn")\n',
        "        if failures:\n",
        '            return mo.callout(mo.md(f"**{label}** — failed"), kind="danger")\n',
        '        return mo.callout(mo.md(f"**{label}** — passed"), kind="success")\n',
        "\n",
        "    return (check,)\n",
        "\n",
        "\n",
        "@app.cell(hide_code=True)\n",
        "def _(mo):\n",
        f"    {MARKS_MARKER}\n",
        '    _marks = {"Q1": 10, "Q2": 15, "Analysis": 75}\n',
        "    # --- display (do not edit below) ---\n",
        "    _total = sum(_marks.values())\n",
        '    mo.callout(mo.md(f"**Total marks available: {_total}**"), kind="neutral")\n',
        "    return (_marks,)\n",
        "\n",
        "\n",
        'if __name__ == "__main__":\n',
        "    app.run()\n",
    ]


def test_has_marks_cell_true():
    lines = _make_notebook_with_marks()
    assert has_marks_cell(lines) is True


def test_has_marks_cell_false():
    lines = ["import marimo\n", "app = marimo.App()\n"]
    assert has_marks_cell(lines) is False


def test_inject_state_cell():
    lines = _make_notebook_with_marks()
    result = inject_state_cell(lines)
    text = "".join(result)
    assert "_check_state, _set_check = mo.state({})" in text
    # State cell should appear before the check function cell
    state_pos = text.index("_check_state, _set_check")
    check_pos = text.index("def check(label")
    assert state_pos < check_pos


def test_inject_state_cell_no_check_function():
    lines = ["import marimo\n", "app = marimo.App()\n"]
    assert inject_state_cell(lines) == lines


def test_augment_check_function():
    lines = _make_notebook_with_marks()
    result = augment_check_function(lines)
    text = "".join(result)
    # Should have _set_check in parameters
    assert "_set_check" in text
    # Should have tracking lines
    assert '_key = label.split(":")[0].strip()' in text
    assert "_passed = bool(checks) and all(ok for ok, _ in checks)" in text
    assert "_set_check(lambda prev: {**prev, _key: _passed})" in text


def test_augment_check_function_no_check():
    lines = ["import marimo\n", "app = marimo.App()\n"]
    assert augment_check_function(lines) == lines


def test_transform_marks_cell():
    lines = _make_notebook_with_marks()
    result = transform_marks_cell(lines)
    text = "".join(result)
    # Should have _check_state in params
    assert "_check_state" in text
    # Should have reactive display
    assert "_results = _check_state()" in text
    assert "_auto = sum(v for k, v in _marks.items() if _results.get(k))" in text
    assert "Your Score" in text


def test_transform_marks_cell_no_marker():
    lines = ["import marimo\n", "app = marimo.App()\n"]
    assert transform_marks_cell(lines) == lines


def test_process_file_with_marks(tmp_path):
    """Full pipeline: strip solutions + apply marks transforms."""
    source = tmp_path / "notebook.py"
    # Create notebook with solution markers AND marks cell
    lines = [
        "import marimo\n",
        "app = marimo.App()\n",
        "\n",
        "@app.cell\n",
        "def _():\n",
        "    import marimo as mo\n",
        "    return (mo,)\n",
        "\n",
        "\n",
        "@app.cell(hide_code=True)\n",
        "def _(mo):\n",
        "    def check(label, checks):\n",
        '        """Run checks."""\n',
        "        failures = [msg for ok, msg in checks if not ok]\n",
        "        if not checks:\n",
        '            return mo.callout(mo.md(f"**{label}** — waiting"), kind="warn")\n',
        "        if failures:\n",
        '            return mo.callout(mo.md(f"**{label}** — failed"), kind="danger")\n',
        '        return mo.callout(mo.md(f"**{label}** — passed"), kind="success")\n',
        "\n",
        "    return (check,)\n",
        "\n",
        "\n",
        "@app.cell\n",
        "def _():\n",
        f"    {SOLUTION_BEGIN}\n",
        "    x = 42\n",
        f"    {SOLUTION_END}\n",
        "    return (x,)\n",
        "\n",
        "\n",
        "@app.cell(hide_code=True)\n",
        "def _(mo):\n",
        f"    {MARKS_MARKER}\n",
        '    _marks = {"Q1": 10, "Analysis": 90}\n',
        "    # --- display (do not edit below) ---\n",
        "    _total = sum(_marks.values())\n",
        '    mo.callout(mo.md(f"**Total marks available: {_total}**"), kind="neutral")\n',
        "    return (_marks,)\n",
        "\n",
        "\n",
        'if __name__ == "__main__":\n',
        "    app.run()\n",
    ]
    source.write_text("".join(lines))
    out_dir = tmp_path / "release"
    assert process_file(source, out_dir) is True

    dest = out_dir / source.name
    content = dest.read_text()
    # Solution stripped
    assert "# YOUR CODE HERE" in content
    assert "x = 42" not in content
    # Marks transforms applied
    assert "_check_state, _set_check = mo.state({})" in content
    assert "_results = _check_state()" in content
