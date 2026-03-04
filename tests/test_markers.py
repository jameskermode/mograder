from mograder.markers import (
    SOLUTION_BEGIN,
    SOLUTION_END,
    count_markers,
    process_file,
    strip_solutions,
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
