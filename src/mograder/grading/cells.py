"""Notebook cell manipulation: marker validation, solution stripping,
grading cell injection, and mark/feedback parsing."""

import ast
import hashlib
import re
import sys
import zipfile
from pathlib import Path

from mograder.core._utils import rel as _rel
from mograder.core.models import CheckResult

# ---------------------------------------------------------------------------
# Marker constants
# ---------------------------------------------------------------------------

SOLUTION_BEGIN = "### BEGIN SOLUTION"
SOLUTION_END = "### END SOLUTION"
HIDDEN_TESTS_BEGIN = "### BEGIN HIDDEN TESTS"
HIDDEN_TESTS_END = "### END HIDDEN TESTS"
SUBMIT_MARKER = "# === MOGRADER: SUBMIT ==="

VERIFICATION_MARKER = "# === MOGRADER: VERIFICATION SUMMARY ==="
FEEDBACK_MARKER = "# === MOGRADER: MARKER FEEDBACK ==="
MARKS_MARKER = "# === MOGRADER: MARKS ==="
SCORES_MARKER = "# MOGRADER_SCORES_CELL"

# ---------------------------------------------------------------------------
# Solution stripping helpers (from markers.py)
# ---------------------------------------------------------------------------

_SIMPLE_NAME_RE = re.compile(r"^[a-zA-Z_]\w*$")
_ASSIGN_RE = re.compile(r"^\s*([a-zA-Z_]\w*)\s*=")
_TUPLE_ASSIGN_RE = re.compile(r"^\s*\(?([a-zA-Z_]\w*(?:\s*,\s*[a-zA-Z_]\w*)*)\)?\s*=")


def _extract_assigned_names(line: str) -> list[str]:
    """Extract all variable names from an assignment LHS (simple or tuple)."""
    m = _TUPLE_ASSIGN_RE.match(line)
    if not m:
        return []
    return [n.strip() for n in m.group(1).split(",") if n.strip()]


def _extract_return_names(line: str) -> list[str]:
    """Extract simple variable names from a return statement.

    Returns names only when every component of the return expression is a
    bare identifier (e.g. ``return x`` or ``return x, y``).  Complex
    expressions like ``return x.value + 1`` yield an empty list.
    """
    m = re.match(r"^\s*return\s+(.+)$", line)
    if not m:
        return []
    expr = m.group(1).strip()
    # Single name: return result
    if _SIMPLE_NAME_RE.match(expr):
        return [expr]
    # Tuple with optional parens: return (x, y) or return x, y
    if expr.startswith("(") and expr.endswith(")"):
        expr = expr[1:-1].strip()
    if expr.endswith(","):
        expr = expr[:-1].strip()
    parts = [p.strip() for p in expr.split(",")]
    if all(_SIMPLE_NAME_RE.match(p) for p in parts):
        return parts
    return []


def _find_sentinel_vars(lines: list[str]) -> dict[int, list[str]]:
    """Identify variables needing sentinels for each solution block.

    Returns a mapping from solution-block index (0-based count of BEGIN
    SOLUTION markers) to the list of variable names that should be
    initialised as ``name = ...`` before the ``# YOUR CODE HERE``
    placeholder.

    A variable needs a sentinel when it appears in a ``return`` statement
    after the corresponding END SOLUTION but is **not** already assigned
    between the beginning of the enclosing scope and the BEGIN SOLUTION
    marker.
    """
    # First pass: locate all solution blocks
    blocks: list[tuple[int, int, str]] = []  # (begin_idx, end_idx, indent)
    stack_begin: int | None = None
    stack_indent = ""
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped == SOLUTION_BEGIN:
            stack_begin = i
            stack_indent = line[: len(line) - len(line.lstrip())]
        elif stripped == SOLUTION_END and stack_begin is not None:
            blocks.append((stack_begin, i, stack_indent))
            stack_begin = None

    result: dict[int, list[str]] = {}
    for block_idx, (begin, end, indent) in enumerate(blocks):
        # Scan forward from END SOLUTION to find return statements
        # Stop at next BEGIN SOLUTION, end of file, or a line at lower
        # indentation (different scope).
        return_names: list[str] = []
        for j in range(end + 1, len(lines)):
            fwd = lines[j]
            fwd_stripped = fwd.strip()
            if not fwd_stripped:
                continue
            if fwd_stripped == SOLUTION_BEGIN:
                break
            # Stop when we leave the scope (lower indentation)
            fwd_indent = fwd[: len(fwd) - len(fwd.lstrip())]
            if len(fwd_indent) < len(indent):
                break
            names = _extract_return_names(fwd)
            return_names.extend(names)
            if names or fwd_stripped.startswith("return"):
                break  # found the return, stop scanning

        if not return_names:
            continue

        # Collect names already assigned before BEGIN SOLUTION in this scope
        pre_assigned: set[str] = set()
        for j in range(begin - 1, -1, -1):
            prev = lines[j]
            prev_stripped = prev.strip()
            if not prev_stripped:
                continue
            # Stop scanning when we leave the enclosing scope
            prev_indent = prev[: len(prev) - len(prev.lstrip())]
            if prev_stripped and len(prev_indent) < len(indent):
                break
            for _name in _extract_assigned_names(prev):
                pre_assigned.add(_name)

        orphaned = [n for n in return_names if n not in pre_assigned]
        if orphaned:
            result[block_idx] = orphaned

    return result


def validate_markers(lines: list[str], filepath: str) -> list[str]:
    """Check that all solution and hidden-test markers are properly paired.

    Returns a list of error messages (empty if valid).
    """
    errors = []
    in_solution = False
    in_hidden = False
    sol_start_line = 0
    hidden_start_line = 0

    for i, line in enumerate(lines, 1):
        stripped = line.strip()

        if stripped == SOLUTION_BEGIN:
            if in_solution:
                errors.append(
                    f"{filepath}:{i}: nested {SOLUTION_BEGIN} "
                    f"(previous opened at line {sol_start_line})"
                )
            if in_hidden:
                errors.append(
                    f"{filepath}:{i}: {SOLUTION_BEGIN} inside hidden tests block "
                    f"(opened at line {hidden_start_line})"
                )
            in_solution = True
            sol_start_line = i

        elif stripped == SOLUTION_END:
            if not in_solution:
                errors.append(
                    f"{filepath}:{i}: {SOLUTION_END} without matching {SOLUTION_BEGIN}"
                )
            in_solution = False

        elif stripped == HIDDEN_TESTS_BEGIN:
            if in_hidden:
                errors.append(
                    f"{filepath}:{i}: nested {HIDDEN_TESTS_BEGIN} "
                    f"(previous opened at line {hidden_start_line})"
                )
            if in_solution:
                errors.append(
                    f"{filepath}:{i}: {HIDDEN_TESTS_BEGIN} inside solution block "
                    f"(opened at line {sol_start_line})"
                )
            in_hidden = True
            hidden_start_line = i

        elif stripped == HIDDEN_TESTS_END:
            if not in_hidden:
                errors.append(
                    f"{filepath}:{i}: {HIDDEN_TESTS_END} without matching "
                    f"{HIDDEN_TESTS_BEGIN}"
                )
            in_hidden = False

    if in_solution:
        errors.append(f"{filepath}:{sol_start_line}: unclosed {SOLUTION_BEGIN}")
    if in_hidden:
        errors.append(f"{filepath}:{hidden_start_line}: unclosed {HIDDEN_TESTS_BEGIN}")

    return errors


def strip_solutions(lines: list[str]) -> list[str]:
    """Remove solution blocks from source lines.

    Lines between BEGIN SOLUTION / END SOLUTION are replaced with
    ``# YOUR CODE HERE`` and ``pass`` at the correct indentation.
    The ``pass`` ensures empty function bodies remain syntactically valid.

    When a ``return`` statement after END SOLUTION references simple
    variable names that are only defined inside the removed solution block,
    sentinel assignments (``name = ...``) are inserted before the
    placeholder so the return does not raise :class:`NameError`.
    """
    sentinels = _find_sentinel_vars(lines)

    output = []
    in_solution = False
    solution_indent = ""
    block_idx = -1

    for line in lines:
        stripped = line.strip()

        if stripped == SOLUTION_BEGIN:
            in_solution = True
            block_idx += 1
            solution_indent = line[: len(line) - len(line.lstrip())]
            continue

        if stripped == SOLUTION_END:
            in_solution = False
            # Insert sentinels for orphaned return variables
            for name in sentinels.get(block_idx, []):
                output.append(f"{solution_indent}{name} = ...\n")
            output.append(f"{solution_indent}# YOUR CODE HERE\n")
            output.append(f"{solution_indent}pass\n")
            continue

        if not in_solution:
            output.append(line)

    return output


def count_markers(lines: list[str]) -> int:
    """Count solution blocks."""
    return sum(1 for line in lines if line.strip() == SOLUTION_BEGIN)


def count_hidden_markers(lines: list[str]) -> int:
    """Count hidden test blocks."""
    return sum(1 for line in lines if line.strip() == HIDDEN_TESTS_BEGIN)


def strip_hidden_tests(lines: list[str]) -> list[str]:
    """Remove hidden test blocks from source lines.

    Lines between BEGIN HIDDEN TESTS / END HIDDEN TESTS are replaced with
    a single ``# HIDDEN TESTS`` placeholder comment at the correct indentation.
    """
    output = []
    in_hidden = False
    hidden_indent = ""

    for line in lines:
        stripped = line.strip()

        if stripped == HIDDEN_TESTS_BEGIN:
            in_hidden = True
            hidden_indent = line[: len(line) - len(line.lstrip())]
            continue

        if stripped == HIDDEN_TESTS_END:
            in_hidden = False
            output.append(f"{hidden_indent}# HIDDEN TESTS\n")
            continue

        if not in_hidden:
            output.append(line)

    return output


def extract_hidden_tests(lines: list[str]) -> list[tuple[str, list[str]]]:
    """Extract hidden test blocks as ``(indent, lines)`` tuples.

    Each tuple contains the indentation prefix and the list of lines
    (with their original indentation) from one hidden-test block.
    Used during autograde to reinject hidden tests into submitted notebooks.
    """
    blocks: list[tuple[str, list[str]]] = []
    current_lines: list[str] = []
    in_hidden = False
    indent = ""

    for line in lines:
        stripped = line.strip()

        if stripped == HIDDEN_TESTS_BEGIN:
            in_hidden = True
            indent = line[: len(line) - len(line.lstrip())]
            current_lines = []
            continue

        if stripped == HIDDEN_TESTS_END:
            in_hidden = False
            blocks.append((indent, current_lines))
            continue

        if in_hidden:
            current_lines.append(line)

    return blocks


def convert_markdown_cells(lines: list[str]) -> list[str]:
    """Convert stripped markdown answer cells to editable mo.md() blocks.

    After ``strip_solutions()``, markdown answer cells look like::

        response_text = "placeholder text"
        # YOUR CODE HERE
        pass
        mo.md(response_text)

    This function converts them to::

        mo.md(r\\"\\"\\"
        placeholder text
        \\"\\"\\")

    so that students see a clean editable markdown cell instead of ugly
    placeholder code.
    """
    output = []
    i = 0
    while i < len(lines):
        # Try to match the 4-line pattern
        if i + 3 < len(lines):
            line0 = lines[i]
            line1 = lines[i + 1]
            line2 = lines[i + 2]
            line3 = lines[i + 3]
            m = re.match(r'^(\s*)response_text\s*=\s*["\'](.+?)["\']\s*$', line0)
            if (
                m
                and line1.strip() == "# YOUR CODE HERE"
                and line2.strip() == "pass"
                and line3.strip() == "mo.md(response_text)"
            ):
                indent = m.group(1)
                placeholder = m.group(2)
                output.append(f'{indent}mo.md(r"""\n')
                output.append(f"{indent}{placeholder}\n")
                output.append(f'{indent}""")\n')
                i += 4
                continue
        output.append(lines[i])
        i += 1
    return output


def build_submit_cell(server_url: str, assignment_name: str) -> str:
    """Build a submit cell that uses ``mograder.remote.submit()``.

    Returns source text for two marimo cells (username input + submit action).
    """
    return f'''\

@app.cell(hide_code=True)
def _(mo):
    {SUBMIT_MARKER}
    import os as _os
    # Hide submit form when running from a dashboard or hub (they handle
    # submission themselves).  Show in WASM, Molab, and standalone mode.
    mo.stop(_os.environ.get("MOGRADER_DASHBOARD") == "1")
    submit_username = mo.ui.text(label="Username", placeholder="Enter your username")
    submit_btn = mo.ui.run_button(label="Submit")
    mo.hstack([submit_username, submit_btn])
    return (submit_btn, submit_username)


@app.cell(hide_code=True)
def _(submit_btn, submit_username, mo):
    mo.stop(not submit_btn.value or not submit_username.value)
    from mograder.remote import submit as submit_fn
    submit_result = submit_fn("{server_url}", "{assignment_name}", __file__, submit_username.value)
    mo.callout(mo.md(f"**Submitted!** Status: {{submit_result}}"), kind="success")
    return


'''


def strip_submit_cells(text: str) -> str:
    """Remove the submit cell pair injected by :func:`build_submit_cell`.

    The submit cell uses ``mo.ui.run_button`` which makes ``marimo export``
    wait indefinitely for a click in headless mode.  Grader snapshots in
    ``submitted/`` must therefore not contain it.

    Returns *text* unchanged if no submit cell is present.
    """
    from marimo._ast.codegen import generate_filecontents_from_ir
    from marimo._convert.converters import MarimoConvert
    from marimo._schemas.serialization import NotebookSerializationV1

    ir = MarimoConvert.from_py(text).to_ir()
    to_drop: set[int] = set()
    for i, cell in enumerate(ir.cells):
        if SUBMIT_MARKER in cell.code:
            to_drop.add(i)
            # The generated submit cell is followed by a dependent cell that
            # references ``submit_btn``; drop it too so the remaining cells
            # don't NameError on a missing input.
            for j in range(i + 1, len(ir.cells)):
                if "submit_btn" in ir.cells[j].code:
                    to_drop.add(j)
                    break
    if not to_drop:
        return text
    new_cells = [c for i, c in enumerate(ir.cells) if i not in to_drop]
    new_ir = NotebookSerializationV1(
        app=ir.app,
        header=ir.header,
        version=ir.version,
        cells=new_cells,
        violations=ir.violations,
        valid=ir.valid,
        filename=ir.filename,
    )
    return generate_filecontents_from_ir(new_ir)


def _inject_before_main(lines: list[str], cell_text: str) -> list[str]:
    """Insert *cell_text* before the ``if __name__`` guard."""
    insert_idx = None
    for i, line in enumerate(lines):
        if line.strip().startswith("if __name__"):
            insert_idx = i
            break
    if insert_idx is None:
        insert_idx = len(lines)
    return lines[:insert_idx] + cell_text.splitlines(keepends=True) + lines[insert_idx:]


def _inject_hidden_tests_metadata(lines: list[str]) -> list[str]:
    """Insert ``mograder-hidden-tests = true`` into a PEP 723 script block.

    If no PEP 723 block is found, the lines are returned unchanged.
    """
    close_idx = None
    in_block = False
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped == "# /// script":
            in_block = True
        elif in_block and stripped == "# ///":
            close_idx = i
            break

    if close_idx is None:
        return lines

    new_line = "# mograder-hidden-tests = true\n"
    return lines[:close_idx] + [new_line] + lines[close_idx:]


def _inject_assignment_metadata(lines: list[str], assignment_name: str) -> list[str]:
    """Insert ``mograder-assignment`` into a PEP 723 script block.

    If no PEP 723 block is found, the lines are returned unchanged.
    """
    # Find the closing # /// line
    close_idx = None
    in_block = False
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped == "# /// script":
            in_block = True
        elif in_block and stripped == "# ///":
            close_idx = i
            break

    if close_idx is None:
        return lines

    new_line = f'# mograder-assignment = "{assignment_name}"\n'
    return lines[:close_idx] + [new_line] + lines[close_idx:]


def _inject_type_metadata(lines: list[str], notebook_type: str) -> list[str]:
    """Insert ``mograder-type`` into a PEP 723 script block.

    If no PEP 723 block exists, one is created after the first line
    (``import marimo``).
    """
    close_idx = None
    in_block = False
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped == "# /// script":
            in_block = True
        elif in_block and stripped == "# ///":
            close_idx = i
            break

    new_line = f'# mograder-type = "{notebook_type}"\n'

    if close_idx is not None:
        return lines[:close_idx] + [new_line] + lines[close_idx:]

    # No PEP 723 block — create a minimal one after ``import marimo``
    insert_after = 0
    for i, line in enumerate(lines):
        if line.strip().startswith("import marimo"):
            insert_after = i + 1
            break

    block = [
        "\n",
        "# /// script\n",
        new_line,
        "# ///\n",
        "\n",
    ]
    return lines[:insert_after] + block + lines[insert_after:]


def read_notebook_type(text: str) -> str:
    """Read ``mograder-type`` from a PEP 723 script block.

    Returns ``"lecture"``, ``"assignment"``, etc.  Defaults to
    ``"assignment"`` when no metadata is found.
    """
    m = re.search(r'^# mograder-type\s*=\s*"([^"]+)"', text, re.MULTILINE)
    return m.group(1) if m else "assignment"


def strip_layout_metadata(lines: list[str]) -> list[str]:
    """Remove ``layout_file`` and ``html_head_file`` kwargs from ``marimo.App(...)``.

    Handles both single-line and multi-line ``App()`` calls.  Preserves
    other keyword arguments (``width``, ``app_title``, etc.).
    """
    text = "".join(lines)

    # Match the full marimo.App(...) call (may span multiple lines)
    m = re.search(r"(marimo\.App\()([^)]*)\)", text, re.DOTALL)
    if m is None:
        return lines

    prefix = m.group(1)  # "marimo.App("
    args_str = m.group(2)

    # Remove layout_file=... and html_head_file=... kwargs
    cleaned = re.sub(
        r"""\s*(?:layout_file|html_head_file)\s*=\s*(?:"[^"]*"|'[^']*'),?""",
        "",
        args_str,
    )
    # Clean up: remove leading/trailing commas and whitespace
    cleaned = re.sub(r",\s*$", "", cleaned.strip())
    cleaned = re.sub(r"^\s*,", "", cleaned.strip())

    if cleaned.strip():
        # Other kwargs remain — reconstruct with them
        replacement = f"{prefix}{cleaned})"
    else:
        # No kwargs left
        replacement = f"{prefix})"

    text = text[: m.start()] + replacement + text[m.end() :]
    return text.splitlines(keepends=True)


def rewrite_notebook_links(lines: list[str]) -> list[str]:
    """Rewrite inter-notebook links for hub deployment.

    - Lecture links ``[text](../Name/Name.py)`` where Name starts with
      ``L`` become ``[text](/run/Name/)``
    - Assignment links ``[text](../Name/Name.py)`` where Name starts with
      ``A`` are stripped to plain text: just ``text``
    """
    text = "".join(lines)

    # Lecture links: ../L-Name/L-Name.py → /run/L-Name/
    text = re.sub(
        r"\[([^\]]+)\]\(\.\./((L[^/]+)/\3\.py)\)",
        r"[\1](/run/\3/)",
        text,
    )

    # Assignment links: ../A-Name/A-Name.py → plain text (strip link)
    text = re.sub(
        r"\[([^\]]+)\]\(\.\./((A[^/]+)/\3\.py)\)",
        r"\1",
        text,
    )

    return text.splitlines(keepends=True)


def _hash_cell(code: str) -> str:
    """Return first 8 hex chars of SHA-256 of the stripped cell code."""
    return hashlib.sha256(code.strip().encode()).hexdigest()[:8]


def _inject_cell_hashes(text: str) -> str:
    """Compute hashes of non-solution cells and inject into PEP 723 block.

    Non-solution cells are those NOT containing ``# YOUR CODE HERE``.
    """
    from marimo._convert.converters import MarimoConvert

    ir = MarimoConvert.from_py(text).to_ir()
    hashes = []
    for cell in ir.cells:
        if "# YOUR CODE HERE" not in cell.code:
            hashes.append(_hash_cell(cell.code))

    if not hashes:
        return text

    lines = text.splitlines(keepends=True)
    close_idx = None
    in_block = False
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped == "# /// script":
            in_block = True
        elif in_block and stripped == "# ///":
            close_idx = i
            break

    if close_idx is None:
        return text

    csv = ",".join(hashes)
    new_line = f'# mograder-cell-hashes = "{csv}"\n'
    lines = lines[:close_idx] + [new_line] + lines[close_idx:]
    return "".join(lines)


def process_file(
    source: Path,
    output_dir: Path | None,
    dry_run: bool = False,
    validate_only: bool = False,
    submit_url: str | None = None,
) -> bool:
    """Process a single notebook file. Returns True on success."""
    lines = source.read_text().splitlines(keepends=True)

    errors = validate_markers(lines, str(source))
    if errors:
        for err in errors:
            print(f"ERROR: {err}", file=sys.stderr)
        return False

    n_solutions = count_markers(lines)
    if n_solutions == 0:
        print(f"SKIP: {source} (no solution markers found)")
        return True

    if validate_only:
        print(f"VALID: {source} ({n_solutions} solution blocks)")
        return True

    n_hidden = count_hidden_markers(lines)
    student_lines = strip_solutions(lines)
    student_lines = strip_hidden_tests(student_lines)
    student_lines = convert_markdown_cells(student_lines)

    if submit_url:
        assignment_name = source.parent.name
        submit_cell = build_submit_cell(submit_url, assignment_name)
        student_lines = _inject_before_main(student_lines, submit_cell)

    if dry_run:
        n_removed = len(lines) - len(student_lines)
        msg = f"DRY-RUN: {_rel(source)} → {n_solutions} solution blocks stripped"
        if n_hidden:
            msg += f", {n_hidden} hidden test blocks stripped"
        msg += f", {n_removed} lines removed"
        print(msg)
        return True

    if output_dir is None:
        output_dir = Path("release")
    output_dir.mkdir(parents=True, exist_ok=True)
    dest = output_dir / source.name

    # Inject assignment metadata into PEP 723 block
    assignment_name = source.parent.name
    student_lines = _inject_assignment_metadata(student_lines, assignment_name)

    # Inject hidden-tests flag if any hidden test blocks were stripped
    if n_hidden > 0:
        student_lines = _inject_hidden_tests_metadata(student_lines)

    dest.write_text("".join(student_lines))

    # Inject cell hashes (needs parsed marimo IR, so operates on written text)
    text = dest.read_text()
    text = _inject_cell_hashes(text)
    dest.write_text(text)

    msg = f"OK: {_rel(source)} → {_rel(dest)} ({n_solutions} solution blocks stripped"
    if n_hidden:
        msg += f", {n_hidden} hidden test blocks stripped"
    msg += ")"
    print(msg)
    return True


def build_release_zip(release_dir: Path) -> Path | None:
    """Create a zip of student-facing release files, excluding artifacts.

    Returns *None* (and removes any stale zip) when the directory contains
    only a single file — a zip that wraps one file adds no value.

    Uses a fixed timestamp so the zip is reproducible across runs.
    """
    zip_path = release_dir / f"{release_dir.name}.zip"
    _EXCLUDE_SUFFIXES = {".html", ".zip"}

    # Collect candidate files
    candidates = sorted(
        f
        for f in release_dir.iterdir()
        if f.is_file()
        and not f.name.startswith(".")
        and f.suffix not in _EXCLUDE_SUFFIXES
    )

    # Skip zip when there's only a single file (e.g. just the .py notebook)
    if len(candidates) <= 1:
        zip_path.unlink(missing_ok=True)
        return None

    # Fixed date_time for reproducible output (2025-01-01 00:00:00)
    _FIXED_TIME = (2025, 1, 1, 0, 0, 0)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in candidates:
            info = zipfile.ZipInfo(f.name, date_time=_FIXED_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(info, f.read_bytes())
    return zip_path


# ---------------------------------------------------------------------------
# Grading cell injection and parsing
# ---------------------------------------------------------------------------


def extract_marking_scale(source_lines: list[str]) -> str | None:
    """Extract the Marking Scale admonition from a source notebook.

    Looks for ``/// details | Marking Scale`` ... ``///`` block in markdown cells.
    Returns the markdown content (without the admonition wrapper), or None.
    """
    import textwrap

    text = "".join(source_lines)
    match = re.search(
        r"///\s*details\s*\|\s*Marking Scale\s*\n(.*?)\n\s*///",
        text,
        re.DOTALL,
    )
    if not match:
        return None
    content = match.group(1)
    lines = content.splitlines()
    # Skip directive lines (e.g. "    type: info") and blank lines at start
    start = 0
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("type:") or not stripped:
            start = i + 1
        else:
            break
    body = "\n".join(lines[start:])
    return textwrap.dedent(body).strip() or None


def parse_marks_metadata(source_lines: list[str]) -> dict[str, int | float] | None:
    """Extract marks metadata from a notebook.

    Reads ``_marks = {...}`` from the MARKS_MARKER cell. All question marks
    (both auto-checked and manual) must be listed in this single dict.

    Returns None if no MARKS_MARKER cell found.
    """
    text = "".join(source_lines)
    if MARKS_MARKER not in text:
        return None

    marker_idx = text.index(MARKS_MARKER)
    section = text[marker_idx:]

    dict_match = re.search(r"_marks\s*=\s*(\{[^}]+\})", section)
    if not dict_match:
        return None
    try:
        marks = ast.literal_eval(dict_match.group(1))
    except (ValueError, SyntaxError):
        return None

    return marks if marks else None


def parse_auto_marks(source_lines: list[str]) -> int | float | None:
    """Extract auto-scored marks from a verification cell with marks data.

    Looks for ``_mograder_marks`` and ``_mograder_checks`` in the verification
    cell and computes sum of marks for PASS checks.  Supports both 4-tuple
    format ``(label, status, earned_weight, total_weight)`` (fractional) and
    legacy 2-tuple format ``(label, status)`` (binary).

    Returns None if no marks data found in the verification cell.
    """
    text = "".join(source_lines)
    if VERIFICATION_MARKER not in text or "_mograder_marks" not in text:
        return None

    marker_idx = text.index(VERIFICATION_MARKER)
    section = text[marker_idx:]

    # Extract _mograder_marks dict
    marks_match = re.search(r"_mograder_marks\s*=\s*(\{[^}]+\})", section)
    if not marks_match:
        return None
    try:
        marks_dict = ast.literal_eval(marks_match.group(1))
    except (ValueError, SyntaxError):
        return None

    # Extract _mograder_checks list
    checks_match = re.search(r"_mograder_checks\s*=\s*\[(.*?)\]", section, re.DOTALL)
    if not checks_match:
        return None

    # Try 4-tuple format first: ("label", "status", earned_weight, total_weight)
    auto_mark = 0.0
    found_4tuple = False
    for m in re.finditer(
        r'\("([^"]+)",\s*"([^"]+)",\s*([0-9.]+),\s*([0-9.]+)\)',
        checks_match.group(1),
    ):
        found_4tuple = True
        label, status = m.group(1), m.group(2)
        ew, tw = float(m.group(3)), float(m.group(4))
        key = label.split(":")[0].strip()
        if key not in marks_dict:
            continue
        if tw > 0:
            auto_mark += round(marks_dict[key] * ew / tw, 1)
        elif status == "PASS":
            # Backward compat: tw=0 means old binary data
            auto_mark += marks_dict[key]

    if found_4tuple:
        return auto_mark

    # Fall back to 2-tuple format: ("label", "status")
    auto_mark_int = 0
    for m in re.finditer(r'\("([^"]+)",\s*"([^"]+)"\)', checks_match.group(1)):
        label, status = m.group(1), m.group(2)
        key = label.split(":")[0].strip()
        if status == "PASS" and key in marks_dict:
            auto_mark_int += marks_dict[key]

    return auto_mark_int


def _build_verification_cell(
    checks: list[CheckResult],
    cell_errors: int,
    marks: dict[str, int | float] | None = None,
) -> str:
    """Build the verification summary cell source."""
    # Map statuses and include weights for fractional marks
    status_map = []
    for c in checks:
        if c.status == "success":
            s = "PASS"
        elif c.status == "partial":
            s = "PARTIAL"
        elif c.status == "danger":
            s = "FAIL"
        else:
            s = "WAIT" if c.status == "warn" else "FAIL"
        label_display = f"{c.label} (hidden)" if c.hidden else c.label
        status_map.append(
            f'("{label_display}", "{s}", {c.earned_weight}, {c.total_weight})'
        )
    checks_list = ",\n        ".join(status_map)
    checks_block = f"\n        {checks_list},\n    " if checks_list else ""

    if marks is None:
        return f"""\

@app.cell(hide_code=True)
def _(mo):
    {VERIFICATION_MARKER}
    _mograder_checks = [{checks_block}]
    _cell_errors = {cell_errors}
    _table = "\\n".join(
        f"| {{_label}} | {{'PASS' if _s == 'PASS' else 'FAIL' if _s == 'FAIL' else 'PARTIAL' if _s == 'PARTIAL' else 'WAIT'}} |"
        for _label, _s, *_rest in _mograder_checks
    )
    mo.callout(mo.md(f"## Verification Summary\\n\\n"
        f"| Check | Result |\\n|-------|--------|\\n{{_table}}\\n\\n"
        f"Cell errors: {{_cell_errors}}"),
        kind="success" if all(_s == "PASS" for _, _s, *_rest in _mograder_checks) else "danger")
    return

"""

    # Build marks-aware version
    marks_repr = repr(marks)

    # Compute check keys for matching
    check_keys = {c.label.split(":")[0].strip() for c in checks}
    # Manual questions are those in marks but not in checks
    manual_keys = [k for k in marks if k not in check_keys]

    # Build manual rows string
    manual_rows = ""
    for k in manual_keys:
        manual_rows += f'    _table += "| {k} | — | ?/{marks[k]} |\\n"\n'

    return f"""\

@app.cell(hide_code=True)
def _(mo):
    {VERIFICATION_MARKER}
    _mograder_checks = [{checks_block}]
    _mograder_marks = {marks_repr}
    _cell_errors = {cell_errors}
    _auto_earned = 0
    _table = ""
    for _label, _s, _ew, _tw in _mograder_checks:
        _key = _label.split(":")[0].strip()
        _avail = _mograder_marks.get(_key, "")
        if _tw > 0 and isinstance(_avail, (int, float)):
            _earned = round(_avail * _ew / _tw, 1)
        elif _s == "PASS" and isinstance(_avail, (int, float)):
            _earned = _avail
        else:
            _earned = 0
        if isinstance(_avail, (int, float)):
            _auto_earned += _earned
        _marks_col = f"{{_earned}}/{{_avail}}" if _avail != "" else ""
        _table += f"| {{_label}} | {{_s}} | {{_marks_col}} |\\n"
{manual_rows}\
    _total_avail = sum(_mograder_marks.values())
    _table += f"| **Total** | | **{{_auto_earned}}/{{_total_avail}}** |\\n"
    mo.callout(mo.md(f"## Verification Summary\\n\\n"
        f"| Check | Result | Marks |\\n|-------|--------|-------|\\n{{_table}}\\n"
        f"Cell errors: {{_cell_errors}}"),
        kind="success" if all(_s == "PASS" for _, _s, _ew, _tw in _mograder_checks) else "danger")
    return

"""


def _build_feedback_cell(
    auto_mark: int | float | None = None,
    manual_available: int | float | None = None,
    total_available: int | float | None = None,
) -> str:
    """Build the marker feedback cell source."""
    if auto_mark is None:
        return f"""\
@app.cell
def _(mo):
    {FEEDBACK_MARKER}
    # Set the mark (0-100) and write 2-3 sentences of feedback, then save.
    _mark = None       # e.g. _mark = 65
    _feedback = ""     # e.g. _feedback = "Good analysis of the DP approach..."

    # --- display (do not edit below) ---
    if _mark is not None:
        mo.callout(mo.md(f"**Mark: {{_mark}}/100**\\n\\n{{_feedback}}"), kind="success")
    else:
        mo.callout(mo.md("**Awaiting marker feedback** — edit `_mark` and `_feedback` above"), kind="warn")
    return

"""

    def _fm(v):
        """Format mark: int if whole, else float."""
        return int(v) if isinstance(v, float) and v == int(v) else v

    _auto = _fm(auto_mark)
    _auto_total = _fm(total_available - manual_available)

    return f"""\
@app.cell
def _(mo):
    {FEEDBACK_MARKER}
    # Auto marks: {_auto}/{_auto_total}
    # Set _mark for manual questions (out of {manual_available}), then save.
    _mark = None       # e.g. _mark = {manual_available}
    _feedback = ""     # e.g. _feedback = "Good analysis of the DP approach..."

    # --- display (do not edit below) ---
    if _mark is not None:
        _total = {_auto} + _mark
        mo.callout(mo.md(f"**Mark: {{_total}}/{total_available}** (auto: {_auto}, manual: {{_mark}})\\n\\n{{_feedback}}"), kind="success")
    else:
        mo.callout(mo.md("**Awaiting marker feedback** — edit `_mark` (out of {manual_available}) and `_feedback` above\\n\\n"
            f"Auto marks so far: {_auto}/{_auto_total}"), kind="warn")
    return

"""


def has_grading_cells(source_lines: list[str]) -> bool:
    """Detect if grading cells are already injected."""
    text = "".join(source_lines)
    return VERIFICATION_MARKER in text or FEEDBACK_MARKER in text


def inject_grading_cells(
    source_lines: list[str],
    checks: list[CheckResult],
    cell_errors: int = 0,
    marks: dict[str, int | float] | None = None,
    source_check_keys: set[str] | None = None,
) -> list[str]:
    """Insert verification summary + marker feedback cells before ``if __name__``.

    Returns modified source lines. Idempotent: if grading cells already exist,
    returns the input unchanged.

    When ``marks`` is provided, the verification cell includes a marks column
    and the feedback cell is pre-configured for manual-only grading.

    ``source_check_keys``, if given, determines which marks-dict keys are
    auto-graded (have a ``check()`` call in the source notebook).  When omitted,
    keys are inferred from the student's executed checks — which may be
    incomplete if ``mo.stop`` guards prevented some checks from running.
    """
    if has_grading_cells(source_lines):
        return source_lines

    if marks is not None:
        # Compute auto marks (fractional) and manual available.
        # Prefer source_check_keys (from source notebook run) over student
        # checks, which may be incomplete due to mo.stop guards.
        check_keys = source_check_keys or {
            c.label.split(":")[0].strip() for c in checks
        }
        auto_mark = 0.0
        for c in checks:
            key = c.label.split(":")[0].strip()
            if key not in marks:
                continue
            avail = marks[key]
            if c.total_weight > 0:
                auto_mark += round(avail * c.earned_weight / c.total_weight, 1)
            elif c.status == "success":
                auto_mark += avail
        manual_available = sum(v for k, v in marks.items() if k not in check_keys)
        total_available = sum(marks.values())
        verification = _build_verification_cell(checks, cell_errors, marks)
        feedback = _build_feedback_cell(auto_mark, manual_available, total_available)
    else:
        verification = _build_verification_cell(checks, cell_errors)
        feedback = _build_feedback_cell()

    # Find the `if __name__` line
    insert_idx = None
    for i, line in enumerate(source_lines):
        if line.strip().startswith("if __name__"):
            insert_idx = i
            break

    if insert_idx is None:
        # Append at end
        insert_idx = len(source_lines)

    new_lines = (
        source_lines[:insert_idx]
        + (verification + feedback).splitlines(keepends=True)
        + source_lines[insert_idx:]
    )
    return new_lines


def parse_marker_feedback(source_lines: list[str]) -> tuple[int | None, str]:
    """Extract ``_mark`` and ``_feedback`` from a graded notebook.

    Looks for the MOGRADER: MARKER FEEDBACK marker and parses the variable
    assignments that follow it.

    Returns (mark, feedback) where mark is None if not yet graded.
    """
    text = "".join(source_lines)
    if FEEDBACK_MARKER not in text:
        return (None, "")

    # Find the feedback section
    marker_idx = text.index(FEEDBACK_MARKER)
    section = text[marker_idx:]

    # Parse _mark
    mark_match = re.search(r"_mark\s*=\s*(\d+|None)", section)
    mark = None
    if mark_match and mark_match.group(1) != "None":
        mark = int(mark_match.group(1))

    # Parse _feedback - try triple-quoted first, then single-line
    feedback = ""
    fb_match = re.search(r'_feedback\s*=\s*"""(.*?)"""', section, re.DOTALL)
    if not fb_match:
        fb_match = re.search(r"_feedback\s*=\s*'''(.*?)'''", section, re.DOTALL)
    if not fb_match:
        fb_match = re.search(r'_feedback\s*=\s*"((?:[^"\\]|\\.)*)"', section)
    if not fb_match:
        fb_match = re.search(r"_feedback\s*=\s*'((?:[^'\\]|\\.)*)'", section)
    if fb_match:
        feedback = fb_match.group(1)

    return (mark, feedback)


def write_marker_feedback(file_path: Path, mark: int | None, feedback: str) -> None:
    """Write ``_mark`` and ``_feedback`` values into a graded notebook.

    The file must contain a MOGRADER: MARKER FEEDBACK marker cell.
    Always writes ``_feedback`` as a triple-quoted string.

    Raises ValueError if the feedback marker is not found.
    """
    text = file_path.read_text()
    if FEEDBACK_MARKER not in text:
        raise ValueError(f"No {FEEDBACK_MARKER} found in {file_path}")

    # Replace _mark value
    mark_str = str(mark) if mark is not None else "None"
    text = re.sub(r"_mark\s*=\s*(\d+|None)", f"_mark = {mark_str}", text)

    # Escape triple quotes in feedback
    safe_feedback = feedback.replace('"""', r"\"\"\"")

    # Replace _feedback value — try triple-quoted patterns first, then single-line
    replacement = f'_feedback = """{safe_feedback}"""'

    # Try triple-double-quoted
    new_text, count = re.subn(
        r'_feedback\s*=\s*""".*?"""', replacement, text, count=1, flags=re.DOTALL
    )
    if count == 0:
        # Try triple-single-quoted
        new_text, count = re.subn(
            r"_feedback\s*=\s*'''.*?'''", replacement, text, count=1, flags=re.DOTALL
        )
    if count == 0:
        # Try double-quoted single-line
        new_text, count = re.subn(
            r'_feedback\s*=\s*"(?:[^"\\]|\\.)*"', replacement, text, count=1
        )
    if count == 0:
        # Try single-quoted single-line
        new_text, count = re.subn(
            r"_feedback\s*=\s*'(?:[^'\\]|\\.)*'", replacement, text, count=1
        )

    file_path.write_text(new_text)
