"""Which assignments are open for marking, and what a marker may open.

Markers (e.g. GTAs, ``MOGRADER_MARKERS``) see an assignment in the formgrader
only once an instructor has opened it for marking, typically after
autograding. The open set is ``marking.json`` (a JSON list of assignment
names) in the course directory.
"""

from __future__ import annotations

import json
from pathlib import Path

MARKING_FILE = "marking.json"


def marking_open(course_dir: Path) -> set[str]:
    """Names of the assignments open for marking (empty if none or unreadable)."""
    try:
        data = json.loads((Path(course_dir) / MARKING_FILE).read_text(encoding="utf-8"))
        return {str(n) for n in data}
    except (OSError, ValueError, TypeError):
        return set()


def set_marking_open(course_dir: Path, name: str, is_open: bool) -> None:
    """Open or close ``name`` for marking (atomic write)."""
    names = marking_open(course_dir)
    (names.add if is_open else names.discard)(name)
    path = Path(course_dir) / MARKING_FILE
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(sorted(names)) + "\n", encoding="utf-8")
    tmp.replace(path)


def marker_may_edit(path: str | Path, course_dir: Path, autograded_dir: str) -> bool:
    """A marker may open only an autograded submission of an assignment that is
    open for marking: ``<course>/<autograded_dir>/<assignment>/<file>``."""
    root = (Path(course_dir) / autograded_dir).resolve()
    try:
        rel = Path(path).resolve().relative_to(root)
    except (ValueError, OSError):
        return False
    return len(rel.parts) >= 2 and rel.parts[0] in marking_open(course_dir)
