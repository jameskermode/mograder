"""SQLite gradebook for persistent grade storage."""

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from mograder.cells import parse_auto_marks, parse_marker_feedback


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
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._create_tables()
        self._migrate()

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
                marks_metadata  TEXT,
                auto_check_keys TEXT
            );
            CREATE TABLE IF NOT EXISTS students (
                username  TEXT PRIMARY KEY,
                full_name TEXT NOT NULL
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
                updated_at      TEXT,
                PRIMARY KEY (assignment, student)
            );
            """
        )

    def _migrate(self) -> None:
        """Add columns that may be missing in existing databases."""
        for stmt in [
            "ALTER TABLE submissions ADD COLUMN updated_at TEXT",
            "ALTER TABLE assignments ADD COLUMN auto_check_keys TEXT",
            "ALTER TABLE submissions ADD COLUMN penalty_pct REAL",
            "ALTER TABLE submissions ADD COLUMN penalised_mark REAL",
            "ALTER TABLE submissions ADD COLUMN submitted_at TEXT",
        ]:
            try:
                self._conn.execute(stmt)
                self._conn.commit()
            except sqlite3.OperationalError:
                pass  # column already exists

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "Gradebook":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    @contextmanager
    def write_lock(self, timeout: float = 10.0):
        """Acquire an exclusive file lock on ``{db_path}.lock``.

        Uses ``fcntl.flock`` (Unix) so that concurrent writers (e.g. autograde
        and formgrader) are serialised.  On Windows the lock is a no-op (SQLite
        WAL + busy_timeout provide basic protection).
        """
        if os.name == "nt":
            yield
            return

        import fcntl
        import time

        lock_path = Path(str(self.db_path) + ".lock")
        fd = lock_path.open("w")
        deadline = time.monotonic() + timeout
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() > deadline:
                    fd.close()
                    raise TimeoutError(
                        f"Could not acquire write lock on {lock_path} within {timeout}s"
                    )
                time.sleep(0.1)
        try:
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            fd.close()

    # --- Assignments ---

    def upsert_assignment(
        self,
        name: str,
        max_mark: float = 100,
        marks_metadata: dict | None = None,
        auto_check_keys: list[str] | None = None,
    ) -> None:
        meta_json = json.dumps(marks_metadata) if marks_metadata else None
        keys_json = json.dumps(sorted(auto_check_keys)) if auto_check_keys else None
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO assignments (name, max_mark, marks_metadata, auto_check_keys)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                    max_mark = excluded.max_mark,
                    marks_metadata = excluded.marks_metadata,
                    auto_check_keys = excluded.auto_check_keys
                """,
                (name, max_mark, meta_json, keys_json),
            )

    def get_assignment(self, name: str) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM assignments WHERE name = ?", (name,)
        ).fetchone()
        if row is None:
            return None
        d = dict(row)
        if d["marks_metadata"]:
            d["marks_metadata"] = json.loads(d["marks_metadata"])
        if d.get("auto_check_keys"):
            d["auto_check_keys"] = json.loads(d["auto_check_keys"])
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
            [
                {"label": c.label, "status": c.status, "hidden": c.hidden}
                for c in check_results
            ]
        )
        tampered_json = json.dumps(tampered or [])
        now = datetime.now().isoformat()

        with self._conn:
            self._conn.execute(
                """
                INSERT INTO submissions
                    (assignment, student, auto_mark, cell_errors, tampered,
                     check_results, autograded_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(assignment, student) DO UPDATE SET
                    auto_mark = excluded.auto_mark,
                    cell_errors = excluded.cell_errors,
                    tampered = excluded.tampered,
                    check_results = excluded.check_results,
                    autograded_at = excluded.autograded_at,
                    updated_at = excluded.updated_at,
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
                    now,
                ),
            )

    def save_manual_grade(
        self,
        assignment: str,
        student: str,
        manual_mark: float | None,
        feedback: str = "",
        total_mark: float | None = None,
        expected_updated_at: str | None = None,
    ) -> bool:
        """Save manual grade and feedback.

        If *total_mark* is provided it is used directly (e.g. after scaling
        a 0-100 slider to the manual portion). Otherwise total is computed
        as ``auto_mark + manual_mark``.

        If *expected_updated_at* is given and the current ``updated_at`` in the
        database differs, the write is skipped and ``False`` is returned
        (optimistic locking — the caller should warn about a conflict).
        Returns ``True`` on successful save.
        """
        now = datetime.now().isoformat()

        # Get current auto_mark (and check for stale data)
        row = self._conn.execute(
            "SELECT auto_mark, updated_at FROM submissions WHERE assignment = ? AND student = ?",
            (assignment, student),
        ).fetchone()

        if row is not None:
            if (
                expected_updated_at is not None
                and row["updated_at"] != expected_updated_at
            ):
                return False  # stale — conflict detected

            if total_mark is not None:
                total = total_mark
            else:
                auto_mark = row["auto_mark"]
                if manual_mark is not None and auto_mark is not None:
                    total = auto_mark + manual_mark
                elif manual_mark is not None:
                    total = manual_mark
                else:
                    total = None

            with self._conn:
                self._conn.execute(
                    """
                    UPDATE submissions
                    SET manual_mark = ?, feedback = ?, total_mark = ?,
                        graded_at = ?, updated_at = ?
                    WHERE assignment = ? AND student = ?
                    """,
                    (manual_mark, feedback, total, now, now, assignment, student),
                )
        else:
            total = total_mark if total_mark is not None else manual_mark
            with self._conn:
                self._conn.execute(
                    """
                    INSERT INTO submissions
                        (assignment, student, manual_mark, feedback,
                         total_mark, graded_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (assignment, student, manual_mark, feedback, total, now, now),
                )
        return True

    def save_penalty(
        self,
        assignment: str,
        student: str,
        penalty_pct: float,
        penalised_mark: float,
        submitted_at: str | None = None,
    ) -> None:
        """Save late penalty data for a submission."""
        now = datetime.now().isoformat()
        with self._conn:
            self._conn.execute(
                """
                UPDATE submissions
                SET penalty_pct = ?, penalised_mark = ?, submitted_at = ?,
                    updated_at = ?
                WHERE assignment = ? AND student = ?
                """,
                (penalty_pct, penalised_mark, submitted_at, now, assignment, student),
            )

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
        """Returns [{student, mark, auto_mark, feedback, ...}, ...] for feedback/CSV."""
        rows = self._conn.execute(
            """
            SELECT student, total_mark, auto_mark, feedback,
                   penalty_pct, penalised_mark, submitted_at
            FROM submissions WHERE assignment = ?
            ORDER BY student
            """,
            (assignment,),
        ).fetchall()
        result = []
        for r in rows:
            d = {
                "student": r["student"],
                "mark": int(r["total_mark"]) if r["total_mark"] is not None else None,
                "auto_mark": int(r["auto_mark"])
                if r["auto_mark"] is not None
                else None,
                "feedback": r["feedback"] or "",
            }
            if r["penalty_pct"] is not None:
                d["penalty_pct"] = r["penalty_pct"]
                d["penalised_mark"] = (
                    int(r["penalised_mark"])
                    if r["penalised_mark"] is not None
                    else None
                )
            result.append(d)
        return result

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

    # --- Students ---

    def upsert_students(self, mapping: dict[str, str]) -> None:
        """Bulk insert or replace student name mappings."""
        with self._conn:
            self._conn.executemany(
                "INSERT OR REPLACE INTO students (username, full_name) VALUES (?, ?)",
                mapping.items(),
            )

    def get_name_lookup(self) -> dict[str, str]:
        """Return {username: full_name} for all students."""
        rows = self._conn.execute("SELECT username, full_name FROM students").fetchall()
        return {r["username"]: r["full_name"] for r in rows}

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

        now = datetime.now().isoformat()
        count = 0
        with self._conn:
            for f in sorted(autograded_dir.iterdir()):
                if f.suffix != ".py":
                    continue
                student = f.stem
                lines = f.read_text().splitlines(keepends=True)
                manual_mark, feedback_text = parse_marker_feedback(lines)
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
                        (assignment, student, auto_mark, manual_mark,
                         total_mark, feedback, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(assignment, student) DO UPDATE SET
                        auto_mark = COALESCE(submissions.auto_mark, excluded.auto_mark),
                        manual_mark = COALESCE(submissions.manual_mark, excluded.manual_mark),
                        total_mark = COALESCE(submissions.total_mark, excluded.total_mark),
                        feedback = CASE
                            WHEN submissions.feedback != '' THEN submissions.feedback
                            ELSE excluded.feedback
                        END,
                        updated_at = excluded.updated_at
                    """,
                    (
                        assignment,
                        student,
                        auto_mark,
                        manual_mark,
                        total,
                        feedback_text,
                        now,
                    ),
                )
                count += 1

        return count
