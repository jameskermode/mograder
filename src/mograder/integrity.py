"""Integrity checking: detect and fix tampering with check/marks cells."""

import dataclasses
import re

from marimo._ast.codegen import generate_filecontents_from_ir
from marimo._convert.converters import MarimoConvert
from marimo._schemas.serialization import NotebookSerializationV1

from mograder.cells import MARKS_MARKER

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
