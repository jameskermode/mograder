"""Directory scanning for formgrader dashboard."""

from dataclasses import dataclass, field
from pathlib import Path

from mograder.cells import (
    has_grading_cells,
    parse_auto_marks,
    parse_gta_feedback,
    parse_marks_metadata,
)


@dataclass
class SubmissionInfo:
    """Status of a single student submission."""

    student: str
    submitted_path: Path | None = None
    autograded_path: Path | None = None
    has_grading_cells: bool = False
    mark: int | None = None
    auto_mark: int | None = None
    feedback_text: str = ""
    graded: bool = False
    feedback_exported: bool = False


@dataclass
class AssignmentInfo:
    """Aggregated status of an assignment across pipeline stages."""

    name: str
    source_path: Path | None = None
    release_path: Path | None = None
    has_source: bool = False
    has_release: bool = False
    num_submitted: int = 0
    num_autograded: int = 0
    num_graded: int = 0
    num_feedback: int = 0
    submissions: list[SubmissionInfo] = field(default_factory=list)


def scan_course(course_dir: Path) -> list[AssignmentInfo]:
    """Scan a course directory and return status for each assignment.

    Walks ``source/``, ``release/``, ``submitted/``, ``autograded/``,
    and ``feedback/`` subdirectories to build a per-assignment overview.
    """
    course_dir = Path(course_dir)
    assignments: dict[str, AssignmentInfo] = {}

    def _ensure(name: str) -> AssignmentInfo:
        if name not in assignments:
            assignments[name] = AssignmentInfo(name=name)
        return assignments[name]

    # Scan source/
    source_dir = course_dir / "source"
    if source_dir.is_dir():
        for d in sorted(source_dir.iterdir()):
            if d.is_dir():
                py_files = list(d.glob("*.py"))
                if py_files:
                    info = _ensure(d.name)
                    info.has_source = True
                    info.source_path = py_files[0]

    # Scan release/
    release_dir = course_dir / "release"
    if release_dir.is_dir():
        for d in sorted(release_dir.iterdir()):
            if d.is_dir():
                py_files = list(d.glob("*.py"))
                if py_files:
                    info = _ensure(d.name)
                    info.has_release = True
                    info.release_path = py_files[0]

    # Scan submitted/
    submitted_dir = course_dir / "submitted"
    if submitted_dir.is_dir():
        for d in sorted(submitted_dir.iterdir()):
            if d.is_dir():
                py_files = [f for f in d.iterdir() if f.suffix == ".py"]
                if py_files:
                    info = _ensure(d.name)
                    info.num_submitted = len(py_files)

    # Scan autograded/
    autograded_dir = course_dir / "autograded"
    if autograded_dir.is_dir():
        for d in sorted(autograded_dir.iterdir()):
            if d.is_dir():
                py_files = [f for f in d.iterdir() if f.suffix == ".py"]
                if py_files:
                    info = _ensure(d.name)
                    info.num_autograded = len(py_files)
                    graded_count = 0
                    for f in py_files:
                        lines = f.read_text().splitlines(keepends=True)
                        mark, _ = parse_gta_feedback(lines)
                        if mark is not None:
                            graded_count += 1
                    info.num_graded = graded_count

    # Scan feedback/
    feedback_dir = course_dir / "feedback"
    if feedback_dir.is_dir():
        for d in sorted(feedback_dir.iterdir()):
            if d.is_dir():
                html_files = [f for f in d.iterdir() if f.suffix == ".html"]
                if html_files:
                    info = _ensure(d.name)
                    info.num_feedback = len(html_files)

    return sorted(assignments.values(), key=lambda a: a.name)


def scan_submissions(course_dir: Path, assignment: str) -> list[SubmissionInfo]:
    """Scan per-student submission details for an assignment.

    Checks ``submitted/``, ``autograded/``, and ``feedback/`` directories
    to build a detailed per-student view.
    """
    course_dir = Path(course_dir)
    students: dict[str, SubmissionInfo] = {}

    def _ensure(name: str) -> SubmissionInfo:
        if name not in students:
            students[name] = SubmissionInfo(student=name)
        return students[name]

    # Submitted
    sub_dir = course_dir / "submitted" / assignment
    if sub_dir.is_dir():
        for f in sub_dir.iterdir():
            if f.suffix == ".py":
                info = _ensure(f.stem)
                info.submitted_path = f

    # Autograded
    auto_dir = course_dir / "autograded" / assignment
    if auto_dir.is_dir():
        for f in auto_dir.iterdir():
            if f.suffix == ".py":
                info = _ensure(f.stem)
                info.autograded_path = f
                lines = f.read_text().splitlines(keepends=True)
                info.has_grading_cells = has_grading_cells(lines)
                mark, feedback_text = parse_gta_feedback(lines)
                auto_mark = parse_auto_marks(lines)
                info.auto_mark = auto_mark
                info.feedback_text = feedback_text
                if auto_mark is not None and mark is not None:
                    info.mark = auto_mark + mark
                    info.graded = True
                elif auto_mark is None and mark is not None:
                    info.mark = mark
                    info.graded = True
                else:
                    info.graded = False

    # Feedback HTML
    fb_dir = course_dir / "feedback" / assignment
    if fb_dir.is_dir():
        for f in fb_dir.iterdir():
            if f.suffix == ".html":
                if f.stem in students:
                    students[f.stem].feedback_exported = True

    return sorted(students.values(), key=lambda s: s.student)


def collect_student_marks(
    course_dir: Path,
    assignments: list[AssignmentInfo],
) -> dict[str, dict[str, int | None]]:
    """Build ``{student_id: {assignment_name: mark | None}}`` across all assignments."""
    course_dir = Path(course_dir)
    result: dict[str, dict[str, int | None]] = {}

    for a in assignments:
        auto_dir = course_dir / "autograded" / a.name
        if not auto_dir.is_dir():
            continue
        for f in auto_dir.iterdir():
            if f.suffix != ".py":
                continue
            student = f.stem
            if student not in result:
                result[student] = {}
            lines = f.read_text().splitlines(keepends=True)
            mark, _ = parse_gta_feedback(lines)
            auto_mark = parse_auto_marks(lines)
            if auto_mark is not None and mark is not None:
                result[student][a.name] = auto_mark + mark
            elif auto_mark is None and mark is not None:
                result[student][a.name] = mark
            else:
                result[student][a.name] = None

    return result


def get_max_marks(
    course_dir: Path,
    assignments: list[AssignmentInfo],
) -> dict[str, int | float]:
    """Return ``{assignment_name: max_mark}`` from source notebooks.

    Uses ``parse_marks_metadata`` when a marks cell exists, otherwise 100.
    """
    course_dir = Path(course_dir)
    result: dict[str, int | float] = {}
    for a in assignments:
        if a.source_path and a.source_path.is_file():
            lines = a.source_path.read_text().splitlines(keepends=True)
            marks = parse_marks_metadata(lines)
            result[a.name] = sum(marks.values()) if marks else 100
        else:
            result[a.name] = 100
    return result
