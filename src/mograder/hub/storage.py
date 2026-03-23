"""Hub storage manager — file layout and status tracking."""

from __future__ import annotations

import os
import shutil
import time
from pathlib import Path


class StorageManager:
    """Manage per-student notebook directories and status markers."""

    def __init__(
        self,
        notebooks_dir: Path,
        release_dir: Path | None = None,
    ):
        self.notebooks_dir = Path(notebooks_dir).resolve()
        self.release_dir = Path(release_dir).resolve() if release_dir else None

    # -- path helpers --

    def _safe_path(self, *parts: str) -> Path:
        """Join *parts* onto notebooks_dir and verify result stays within it."""
        joined = self.notebooks_dir.joinpath(*parts).resolve()
        base = self.notebooks_dir
        if not (joined == base or str(joined).startswith(str(base) + os.sep)):
            raise ValueError(f"Path escapes base directory: {joined}")
        return joined

    def assignment_path(self, username: str, assignment: str) -> Path:
        """Return ``notebooks_dir/username/assignment/assignment.py``."""
        self._safe_path(username, assignment)  # validate
        return self.notebooks_dir / username / assignment / f"{assignment}.py"

    def release_path(self, assignment: str) -> Path | None:
        """Return release file path if it exists, else None."""
        if self.release_dir is None:
            return None
        p = self.release_dir / assignment / f"{assignment}.py"
        return p if p.is_file() else None

    def has_release(self, assignment: str) -> bool:
        return self.release_path(assignment) is not None

    def ensure_dir(self, username: str, assignment: str) -> Path:
        """Create and return ``notebooks_dir/username/assignment/``."""
        self._safe_path(username, assignment)  # validate
        d = self.notebooks_dir / username / assignment
        d.mkdir(parents=True, exist_ok=True)
        return d

    # -- status tracking --

    def assignment_status(self, username: str, assignment: str) -> str:
        """Return assignment status: not_started, uploaded, modified, exported."""
        nb = self.assignment_path(username, assignment)
        if not nb.exists():
            return "not_started"
        d = nb.parent
        exported_marker = d / ".exported"
        uploaded_marker = d / ".uploaded"

        nb_mtime = nb.stat().st_mtime

        if exported_marker.exists():
            if exported_marker.stat().st_mtime >= nb_mtime:
                return "exported"

        if uploaded_marker.exists():
            if uploaded_marker.stat().st_mtime >= nb_mtime:
                return "uploaded"
            return "modified"

        return "not_started"

    def mark_uploaded(self, username: str, assignment: str) -> None:
        """Touch .uploaded marker."""
        d = self.assignment_path(username, assignment).parent
        d.mkdir(parents=True, exist_ok=True)
        (d / ".uploaded").touch()

    def mark_exported(self, username: str, assignment: str) -> None:
        """Touch .exported marker."""
        d = self.assignment_path(username, assignment).parent
        d.mkdir(parents=True, exist_ok=True)
        (d / ".exported").touch()

    # -- reset --

    def reset_to_release(
        self, username: str, assignment: str
    ) -> Path | None:
        """Archive existing notebook and optionally copy from release.

        Returns the archive path, or None if no existing file to archive.
        """
        nb = self.assignment_path(username, assignment)
        if not nb.exists():
            return None

        # Archive existing
        ts = time.strftime("%Y%m%dT%H%M%S")
        archive = nb.with_suffix(f".bak.{ts}.py")
        shutil.move(str(nb), str(archive))

        # Remove markers
        for marker in (".uploaded", ".exported"):
            m = nb.parent / marker
            m.unlink(missing_ok=True)

        # Copy from release if available
        release = self.release_path(assignment)
        if release is not None:
            shutil.copy2(str(release), str(nb))
            self.mark_uploaded(username, assignment)

        return archive

    # -- listing --

    def list_assignments(self) -> list[str]:
        """List available assignments from release_dir."""
        if self.release_dir is None or not self.release_dir.is_dir():
            return []
        return sorted(
            d.name
            for d in self.release_dir.iterdir()
            if d.is_dir() and (d / f"{d.name}.py").is_file()
        )
