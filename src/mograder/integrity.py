"""Integrity checking: detect and fix tampering with check/marks cells."""

import dataclasses
import re

from marimo._ast.codegen import generate_filecontents_from_ir
from marimo._convert.converters import MarimoConvert
from marimo._schemas.serialization import NotebookSerializationV1

from mograder.cells import MARKS_MARKER
from mograder.markers import _hash_cell

# Pattern to extract question key from check() calls, e.g. check("Q1: ...")
_CHECK_CALL_RE = re.compile(r"""check\(\s*["']([^"':]+)""")


@dataclasses.dataclass
class IntegrityResult:
    """Result of an integrity check between source and submitted notebooks."""

    tampered_checks: list[str]  # question keys with modified check cells
    tampered_marks: bool  # marks cell was modified
    fixed_source: str  # reassembled notebook with source cells reinjected


def _extract_check_key(code: str) -> str | None:
    """Extract question key from a check cell's code."""
    m = _CHECK_CALL_RE.search(code)
    return m.group(1).strip() if m else None


def _is_check_cell(code: str) -> bool:
    """Detect whether a cell is a check cell."""
    return _CHECK_CALL_RE.search(code) is not None


def _is_marks_cell(code: str) -> bool:
    """Detect whether a cell is the marks cell."""
    return MARKS_MARKER in code


@dataclasses.dataclass
class CellIntegrityResult:
    """Result of cell-level integrity check between release and submitted."""

    tampered_cells: list[str]  # descriptions of modified non-solution cells
    fixed_source: str  # reassembled with release cells reinjected


def _is_solution_cell(code: str) -> bool:
    """A release cell is a solution cell if it contains the placeholder."""
    return "# YOUR CODE HERE" in code


def check_cell_integrity(release_text: str, submitted_text: str) -> CellIntegrityResult:
    """Compare all non-solution cells between release and submitted notebooks.

    Solution cells (containing ``# YOUR CODE HERE``) are left as-is since
    students are expected to modify them. Every other release cell must appear
    unchanged in the submission; missing or modified cells are reinjected from
    the release version.
    """
    release_ir = MarimoConvert.from_py(release_text).to_ir()
    submitted_ir = MarimoConvert.from_py(submitted_text).to_ir()

    # Separate release cells into solution and non-solution
    non_solution_codes: set[str] = set()
    for cell in release_ir.cells:
        if not _is_solution_cell(cell.code):
            non_solution_codes.add(cell.code)

    # Build set of submitted cell codes for quick lookup
    submitted_codes: set[str] = {cell.code for cell in submitted_ir.cells}

    # Find missing/modified non-solution cells
    tampered_cells: list[str] = []
    missing_cells = []
    for cell in release_ir.cells:
        if _is_solution_cell(cell.code):
            continue
        if cell.code not in submitted_codes:
            snippet = cell.code.strip().split("\n")[0][:60]
            tampered_cells.append(f"modified/missing: {snippet}")
            missing_cells.append(cell)

    # Build fixed notebook: start with submitted cells, replace/reinject
    # For each submitted cell that matches a non-solution release cell, keep it.
    # For submitted cells that don't match any release non-solution cell AND
    # are not solution cells from the submission, they might be tampered versions.
    # Strategy: keep all submitted cells, then append any missing release cells.
    new_cells = list(submitted_ir.cells)
    for cell in missing_cells:
        # Insert before last cell (if __name__ guard)
        if new_cells:
            new_cells.insert(len(new_cells) - 1, cell)
        else:
            new_cells.append(cell)

    new_ir = NotebookSerializationV1(
        app=submitted_ir.app,
        header=submitted_ir.header,
        version=submitted_ir.version,
        cells=new_cells,
        violations=submitted_ir.violations,
        valid=submitted_ir.valid,
        filename=submitted_ir.filename,
    )
    fixed_source = generate_filecontents_from_ir(new_ir)

    return CellIntegrityResult(
        tampered_cells=tampered_cells,
        fixed_source=fixed_source,
    )


_ASSIGNMENT_NAME_RE = re.compile(r'#\s*mograder-assignment\s*=\s*"([^"]+)"')
_CELL_HASHES_RE = re.compile(r'#\s*mograder-cell-hashes\s*=\s*"([^"]+)"')


def parse_assignment_name(text: str) -> str | None:
    """Extract mograder-assignment value from PEP 723 metadata."""
    m = _ASSIGNMENT_NAME_RE.search(text)
    return m.group(1) if m else None


def parse_cell_hashes(text: str) -> list[str] | None:
    """Extract mograder-cell-hashes as a list of hex strings."""
    m = _CELL_HASHES_RE.search(text)
    if not m:
        return None
    return m.group(1).split(",")


@dataclasses.dataclass
class CellHashWarning:
    """Warning about a modified non-solution cell."""

    index: int  # 0-based index among non-solution cells
    snippet: str  # first line of the cell for display


def validate_cell_hashes(text: str) -> list[CellHashWarning]:
    """Compare embedded cell hashes against actual cell contents.

    Returns warnings for each non-solution cell whose hash doesn't match.
    Returns an empty list if no hashes are embedded (graceful degradation).
    """
    hashes = parse_cell_hashes(text)
    if hashes is None:
        return []

    ir = MarimoConvert.from_py(text).to_ir()
    warnings: list[CellHashWarning] = []
    hash_idx = 0
    for cell in ir.cells:
        if "# YOUR CODE HERE" in cell.code:
            continue
        if hash_idx < len(hashes):
            actual = _hash_cell(cell.code)
            if actual != hashes[hash_idx]:
                snippet = cell.code.strip().split("\n")[0][:60]
                warnings.append(CellHashWarning(index=hash_idx, snippet=snippet))
        hash_idx += 1

    return warnings


def fix_modified_cells(release_text: str, submitted_text: str) -> CellIntegrityResult:
    """Replace modified non-solution cells with their release versions.

    Unlike :func:`check_cell_integrity`, this matches non-solution cells by
    their positional index and replaces them in-place rather than appending.
    """
    release_ir = MarimoConvert.from_py(release_text).to_ir()
    submitted_ir = MarimoConvert.from_py(submitted_text).to_ir()

    # Build ordered list of non-solution cells from release
    release_nonsol = []
    for i, cell in enumerate(release_ir.cells):
        if not _is_solution_cell(cell.code):
            release_nonsol.append((i, cell))

    # Build ordered list of non-solution cells from submitted
    submitted_nonsol_indices = []
    for i, cell in enumerate(submitted_ir.cells):
        if not _is_solution_cell(cell.code):
            submitted_nonsol_indices.append(i)

    tampered: list[str] = []
    new_cells = list(submitted_ir.cells)

    for ns_idx, (_, rel_cell) in enumerate(release_nonsol):
        if ns_idx >= len(submitted_nonsol_indices):
            break
        sub_idx = submitted_nonsol_indices[ns_idx]
        sub_cell = new_cells[sub_idx]
        if sub_cell.code != rel_cell.code:
            snippet = sub_cell.code.strip().split("\n")[0][:60]
            tampered.append(f"modified: {snippet}")
            new_cells[sub_idx] = dataclasses.replace(sub_cell, code=rel_cell.code)

    new_ir = NotebookSerializationV1(
        app=submitted_ir.app,
        header=submitted_ir.header,
        version=submitted_ir.version,
        cells=new_cells,
        violations=submitted_ir.violations,
        valid=submitted_ir.valid,
        filename=submitted_ir.filename,
    )
    fixed_source = generate_filecontents_from_ir(new_ir)

    return CellIntegrityResult(
        tampered_cells=tampered,
        fixed_source=fixed_source,
    )


def check_integrity(source_text: str, submitted_text: str) -> IntegrityResult:
    """Compare check/marks cells between source and submitted notebooks.

    Detects cells where the student has modified check() calls or the marks
    definition, reinjects the source versions, and returns the result.
    """
    source_ir = MarimoConvert.from_py(source_text).to_ir()
    submitted_ir = MarimoConvert.from_py(submitted_text).to_ir()

    # Build source lookup
    source_checks: dict[str, str] = {}  # question_key → cell code
    source_marks_code: str | None = None
    for cell in source_ir.cells:
        if _is_marks_cell(cell.code):
            source_marks_code = cell.code
        elif _is_check_cell(cell.code):
            key = _extract_check_key(cell.code)
            if key:
                source_checks[key] = cell.code

    # Walk submitted cells, compare and fix
    tampered_checks: list[str] = []
    tampered_marks = False
    seen_check_keys: set[str] = set()
    new_cells = []

    for cell in submitted_ir.cells:
        if _is_marks_cell(cell.code):
            if source_marks_code is not None and cell.code != source_marks_code:
                tampered_marks = True
                cell = dataclasses.replace(cell, code=source_marks_code)
            new_cells.append(cell)
        elif _is_check_cell(cell.code):
            key = _extract_check_key(cell.code)
            if key and key in source_checks:
                seen_check_keys.add(key)
                if cell.code != source_checks[key]:
                    tampered_checks.append(key)
                    cell = dataclasses.replace(cell, code=source_checks[key])
            new_cells.append(cell)
        else:
            new_cells.append(cell)

    # Detect deleted check cells: source checks not found in submitted
    missing_keys = set(source_checks) - seen_check_keys
    for key in sorted(missing_keys):
        tampered_checks.append(key)
        # Find the source cell and append before the last cell (if __name__)
        for src_cell in source_ir.cells:
            if (
                _is_check_cell(src_cell.code)
                and _extract_check_key(src_cell.code) == key
            ):
                # Insert before last cell
                if new_cells:
                    new_cells.insert(len(new_cells) - 1, src_cell)
                else:
                    new_cells.append(src_cell)
                break

    # Reassemble
    new_ir = NotebookSerializationV1(
        app=submitted_ir.app,
        header=submitted_ir.header,
        version=submitted_ir.version,
        cells=new_cells,
        violations=submitted_ir.violations,
        valid=submitted_ir.valid,
        filename=submitted_ir.filename,
    )
    fixed_source = generate_filecontents_from_ir(new_ir)

    return IntegrityResult(
        tampered_checks=tampered_checks,
        tampered_marks=tampered_marks,
        fixed_source=fixed_source,
    )
