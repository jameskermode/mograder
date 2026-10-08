"""Per-session memory measurement and estimates for hub admission control.

The hub samples each session's memory (its marimo process and every
descendant, e.g. the kernel) and keeps the peak per item in
``session_memory.json`` in the course directory. Admission control uses an
estimate per item: the larger of that measured peak and a calibrated value
from ``session_mb.json`` (``{"<item>": MB, ..., "default": MB}``, written by
the instructor or a calibration run), falling back to ``--session-mb``.

Memory is PSS (proportional set size) where available: pages shared between
sessions (libraries from a shared venv) are split between them, so the sum
over sessions approximates what they really use. RSS would count shared pages
once per process. Linux only (``/proc``); elsewhere nothing is measured.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

log = logging.getLogger("mograder.hub")

MEASURED_FILE = "session_memory.json"
CALIBRATED_FILE = "session_mb.json"


def children_map() -> dict[int, list[int]]:
    """Parent pid -> child pids, from /proc (empty where /proc is absent)."""
    children: dict[int, list[int]] = {}
    try:
        entries = os.listdir("/proc")
    except OSError:
        return children
    for entry in entries:
        if not entry.isdigit():
            continue
        try:
            with open(f"/proc/{entry}/stat", encoding="utf-8") as f:
                stat = f.read()
        except OSError:
            continue
        # comm (field 2) may contain spaces; ppid follows the closing paren
        ppid = int(stat.rsplit(")", 1)[1].split()[1])
        children.setdefault(ppid, []).append(int(entry))
    return children


def process_mb(pid: int) -> int:
    """PSS of one process in MB (RSS if PSS is unreadable; 0 if gone)."""
    for path, key in (
        (f"/proc/{pid}/smaps_rollup", "Pss:"),
        (f"/proc/{pid}/status", "VmRSS:"),
    ):
        try:
            with open(path, encoding="utf-8") as f:
                for line in f:
                    if line.startswith(key):
                        return int(line.split()[1]) // 1024
        except OSError:
            continue
    return 0


def tree_mb(pid: int, children: dict[int, list[int]]) -> int:
    """Memory of a process and all its descendants, in MB."""
    total, stack, seen = 0, [pid], set()
    while stack:
        p = stack.pop()
        if p in seen:
            continue
        seen.add(p)
        total += process_mb(p)
        stack.extend(children.get(p, ()))
    return total


class MemoryLedger:
    """Measured peaks and calibrated estimates of session memory per item."""

    def __init__(self, course_dir: Path | None, default_mb: int = 0):
        self.default_mb = default_mb
        self.measured_path = Path(course_dir) / MEASURED_FILE if course_dir else None
        self.calibrated_path = (
            Path(course_dir) / CALIBRATED_FILE if course_dir else None
        )
        self.measured: dict[str, int] = self._load(self.measured_path)
        self._dirty = False

    @staticmethod
    def _load(path: Path | None) -> dict[str, int]:
        if path is None or not path.exists():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return {str(k): int(v) for k, v in data.items()}
        except (OSError, ValueError, TypeError, AttributeError):
            log.warning("ignoring unreadable %s", path)
            return {}

    def calibrated(self) -> dict[str, int]:
        """Read on each call, so edits take effect without a restart."""
        return self._load(self.calibrated_path)

    def estimate(self, item: str) -> int:
        cal = self.calibrated()
        base = cal.get(item, cal.get("default", self.default_mb))
        return max(base, self.measured.get(item, 0))

    def record(self, item: str, mb: int) -> None:
        if mb > self.measured.get(item, 0):
            self.measured[item] = mb
            self._dirty = True

    def save(self) -> None:
        if not self._dirty or self.measured_path is None:
            return
        tmp = self.measured_path.with_suffix(".tmp")
        try:
            tmp.write_text(
                json.dumps(dict(sorted(self.measured.items())), indent=1) + "\n",
                encoding="utf-8",
            )
            tmp.replace(self.measured_path)
            self._dirty = False
        except OSError:
            log.exception("could not write %s", self.measured_path)
