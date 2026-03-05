"""SQLite gradebook for persistent grade storage."""

import json
import sqlite3
from datetime import datetime
from pathlib import Path

from mograder.cells import parse_auto_marks, parse_gta_feedback


class Gradebook:
    """SQLite-backed gradebook for storing grades and feedback.

    Uses WAL mode for safe concurrent access from multiple SSH sessions.
    """

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self._is_new = not self.db_path.exists()
        self._conn = sqlite3.connect(
            str(self.db_path),
            check_same_thread=False,
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._create_tables()

    @property
    def is_new(self) -> bool:
        """True if the database was freshly created (no prior file)."""
        return self._is_new

    def _create_tables(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS assignments (
                name            TEXT PRIMARY KEY,
                max_mark        REAL NOT NULL DEFAULT 100,
                marks_metadata  TEXT
            );
            CREATE TABLE IF NOT EXISTS submissions (
                assignment      TEXT NOT NULL REFERENCES assignments(name),
                student         TEXT NOT NULL,
                auto_mark       REAL,
                manual_mark     REAL,
                total_mark      REAL,
                feedback        TEXT NOT NULL DEFAULT '',
                cell_errors     INTEGER NOT NULL DEFAULT 0,
                tampered        TEXT NOT NULL DEFAULT '[]',
                check_results   TEXT NOT NULL DEFAULT '[]',
                graded_at       TEXT,
                autograded_at   TEXT NOT NULL DEFAULT (datetime('now')),
                PRIMARY KEY (assignment, student)
            );
            """
        )

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "Gradebook":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # --- Assignments ---

    def upsert_assignment(
        self,
        name: str,
        max_mark: float = 100,
        marks_metadata: dict | None = None,
    ) -> None:
        meta_json = json.dumps(marks_metadata) if marks_metadata else None
        self._conn.execute(
            """
            INSERT INTO assignments (name, max_mark, marks_metadata)
            VALUES (?, ?, ?)
            ON CONFLICT(name) DO UPDATE SET
                max_mark = excluded.max_mark,
                marks_metadata = excluded.marks_metadata
            """,
            (name, max_mark, meta_json),
        )
        self._conn.commit()

    def get_assignment(self, name: str) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM assignments WHERE name = ?", (name,)
        ).fetchone()
        if row is None:
            return None
        d = dict(row)
        if d["marks_metadata"]:
            d["marks_metadata"] = json.loads(d["marks_metadata"])
        return d

    # --- Submissions ---

    def save_autograde_result(
        self,
        assignment: str,
        student: str,
        check_results: list,
        cell_errors: int = 0,
        auto_mark: float | None = None,
        tampered: list[str] | None = None,
    ) -> None:
        """Upsert autograde results, preserving existing manual_mark/feedback."""
        checks_json = json.dumps(
            [{"label": c.label, "status": c.status} for c in check_results]
        )
        tampered_json = json.dumps(tampered or [])
        now = datetime.now().isoformat()

        self._conn.execute(
            """
            INSERT INTO submissions
                (assignment, student, auto_mark, cell_errors, tampered,
                 check_results, autograded_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(assignment, student) DO UPDATE SET
                auto_mark = excluded.auto_mark,
                cell_errors = excluded.cell_errors,
                tampered = excluded.tampered,
                check_results = excluded.check_results,
                autograded_at = excluded.autograded_at,
                total_mark = CASE
                    WHEN submissions.manual_mark IS NOT NULL
                         AND excluded.auto_mark IS NOT NULL
                    THEN excluded.auto_mark + submissions.manual_mark
                    WHEN submissions.manual_mark IS NOT NULL
                    THEN submissions.manual_mark
                    ELSE NULL
                END
            """,
            (
                assignment,
                student,
                auto_mark,
                cell_errors,
                tampered_json,
                checks_json,
                now,
            ),
        )
        self._conn.commit()

    def save_manual_grade(
        self,
        assignment: str,
        student: str,
        manual_mark: float | None,
        feedback: str = "",
    ) -> None:
        """Save GTA manual grade and feedback, recomputing total."""
        now = datetime.now().isoformat()

        # Get current auto_mark
        row = self._conn.execute(
            "SELECT auto_mark FROM submissions WHERE assignment = ? AND student = ?",
            (assignment, student),
        ).fetchone()

        if row is not None:
            auto_mark = row["auto_mark"]
            if manual_mark is not None and auto_mark is not None:
                total = auto_mark + manual_mark
            elif manual_mark is not None:
                total = manual_mark
            else:
                total = None

            self._conn.execute(
                """
                UPDATE submissions
                SET manual_mark = ?, feedback = ?, total_mark = ?, graded_at = ?
                WHERE assignment = ? AND student = ?
                """,
                (manual_mark, feedback, total, now, assignment, student),
            )
        else:
            total = manual_mark
            self._conn.execute(
                """
                INSERT INTO submissions
                    (assignment, student, manual_mark, feedback, total_mark, graded_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (assignment, student, manual_mark, feedback, total, now),
            )
        self._conn.commit()

    def get_submission(self, assignment: str, student: str) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM submissions WHERE assignment = ? AND student = ?",
            (assignment, student),
        ).fetchone()
        if row is None:
            return None
        d = dict(row)
        d["check_results"] = json.loads(d["check_results"])
        d["tampered"] = json.loads(d["tampered"])
        return d

    def list_submissions(self, assignment: str) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM submissions WHERE assignment = ? ORDER BY student",
            (assignment,),
        ).fetchall()
        result = []
        for row in rows:
            d = dict(row)
            d["check_results"] = json.loads(d["check_results"])
            d["tampered"] = json.loads(d["tampered"])
            result.append(d)
        return result

    # --- Grade collection ---

    def collect_grades(self, assignment: str) -> list[dict]:
        """Returns [{student, mark, auto_mark, feedback}, ...] for feedback/CSV."""
        rows = self._conn.execute(
            """
            SELECT student, total_mark, auto_mark, feedback
            FROM submissions WHERE assignment = ?
            ORDER BY student
            """,
            (assignment,),
        ).fetchall()
        return [
            {
                "student": r["student"],
                "mark": int(r["total_mark"]) if r["total_mark"] is not None else None,
                "auto_mark": int(r["auto_mark"])
                if r["auto_mark"] is not None
                else None,
                "feedback": r["feedback"] or "",
            }
            for r in rows
        ]

    def collect_student_marks(
        self, assignment_names: list[str]
    ) -> dict[str, dict[str, int | None]]:
        """Returns {student: {assignment: total_mark}} across assignments."""
        result: dict[str, dict[str, int | None]] = {}
        for aname in assignment_names:
            rows = self._conn.execute(
                "SELECT student, total_mark FROM submissions WHERE assignment = ?",
                (aname,),
            ).fetchall()
            for r in rows:
                student = r["student"]
                if student not in result:
                    result[student] = {}
                mark = int(r["total_mark"]) if r["total_mark"] is not None else None
                result[student][aname] = mark
        return result

    def count_graded(self, assignment: str) -> int:
        """Count submissions with a manual grade set."""
        row = self._conn.execute(
            "SELECT COUNT(*) as c FROM submissions WHERE assignment = ? AND graded_at IS NOT NULL",
            (assignment,),
        ).fetchone()
        return row["c"]

    # --- Migration ---

    def import_from_py(
        self,
        assignment: str,
        autograded_dir: Path,
        marks_metadata: dict | None = None,
    ) -> int:
        """Import existing grades from .py files into the DB.

        Returns count of submissions imported.
        """
        autograded_dir = Path(autograded_dir)
        if not autograded_dir.is_dir():
            return 0

        count = 0
        for f in sorted(autograded_dir.iterdir()):
            if f.suffix != ".py":
                continue
            student = f.stem
            lines = f.read_text().splitlines(keepends=True)
            manual_mark, feedback_text = parse_gta_feedback(lines)
            auto_mark = parse_auto_marks(lines)

            if manual_mark is not None and auto_mark is not None:
                total = auto_mark + manual_mark
            elif manual_mark is not None:
                total = manual_mark
            else:
                total = None

            self._conn.execute(
                """
                INSERT INTO submissions
                    (assignment, student, auto_mark, manual_mark, total_mark, feedback)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(assignment, student) DO UPDATE SET
                    auto_mark = COALESCE(submissions.auto_mark, excluded.auto_mark),
                    manual_mark = COALESCE(submissions.manual_mark, excluded.manual_mark),
                    total_mark = COALESCE(submissions.total_mark, excluded.total_mark),
                    feedback = CASE
                        WHEN submissions.feedback != '' THEN submissions.feedback
                        ELSE excluded.feedback
                    END
                """,
                (assignment, student, auto_mark, manual_mark, total, feedback_text),
            )
            count += 1

        self._conn.commit()
        return count
