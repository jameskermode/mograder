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

    def mark_fetched(self, username: str, name: str) -> None:
        """Touch .fetched: when the user's copy was last taken from the release."""
        d = self.assignment_path(username, name).parent
        d.mkdir(parents=True, exist_ok=True)
        (d / ".fetched").touch()

    def release_updated(self, username: str, name: str) -> bool:
        """Whether the release was republished after the user's copy was taken.

        Uses the .fetched marker (falling back to .uploaded for copies made
        before it existed). False if the user has no copy or no release.
        """
        nb = self.assignment_path(username, name)
        release = self.release_path(name)
        if not nb.exists() or release is None:
            return False
        for marker in (".fetched", ".uploaded"):
            m = nb.parent / marker
            if m.exists():
                return release.stat().st_mtime > m.stat().st_mtime
        return False

    def fetch_release(self, username: str, name: str) -> Path | None:
        """Give the user the latest release, never losing their work.

        With no copy yet, copies the release; otherwise archives the current
        copy as ``<name>.bak.<timestamp>.py`` first (see ``reset_to_release``).
        Returns the archive path, or None if there was no copy to archive.
        """
        nb = self.assignment_path(username, name)
        if nb.exists():
            return self.reset_to_release(username, name)
        release = self.release_path(name)
        if release is None:
            raise FileNotFoundError(name)
        self.ensure_dir(username, name)
        shutil.copy2(str(release), str(nb))
        self.copy_support_files(username, name)
        self.mark_uploaded(username, name)
        self.mark_fetched(username, name)
        return None

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

    def mark_submitted(self, username: str, assignment: str) -> None:
        """Touch .submitted marker."""
        d = self.assignment_path(username, assignment).parent
        d.mkdir(parents=True, exist_ok=True)
        (d / ".submitted").touch()

    # -- visibility --
    #
    # One JSON file at the release_dir root maps item name to
    # {"visible_from": ISO datetime with offset} or {"hidden": true}; items
    # not listed are visible. Kept outside the item directories so that
    # republishing an item leaves its schedule alone, and so it can be set
    # before the item is published.

    VISIBILITY_FILE = ".visibility.json"

    def read_visibility(self) -> dict[str, dict]:
        if self.release_dir is None:
            return {}
        f = self.release_dir / self.VISIBILITY_FILE
        if not f.is_file():
            return {}
        import json

        return json.loads(f.read_text(encoding="utf-8"))

    def write_visibility(self, data: dict[str, dict]) -> None:
        import json

        if self.release_dir is None:
            raise ValueError("No release directory")
        self.release_dir.mkdir(parents=True, exist_ok=True)
        f = self.release_dir / self.VISIBILITY_FILE
        tmp = f.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(f)

    def visibility(
        self, name: str, now: float | None = None
    ) -> tuple[bool, str | None]:
        """Return ``(visible_to_students, visible_from)`` for an item."""
        from datetime import datetime, timezone

        entry = self.read_visibility().get(name)
        if not entry:
            return True, None
        if entry.get("hidden"):
            return False, None
        opens = entry.get("visible_from")
        if not opens:
            return True, None
        current = (
            datetime.fromtimestamp(now, timezone.utc)
            if now is not None
            else datetime.now(timezone.utc)
        )
        return current >= datetime.fromisoformat(opens), opens

    # -- reset --

    def copy_support_files(self, username: str, name: str) -> list[str]:
        """Copy a release's supporting files (data, images, helper modules)
        into the user's directory, next to their copy of the notebook.

        The notebook itself, previews (.html), zips and manifests are left
        out, and existing files are never overwritten (the student may have
        changed them). Edit sessions run in the user's directory, so without
        these files notebook-relative paths would fail. Returns the names
        copied.
        """
        if self.release_dir is None:
            return []
        src = self.release_dir / name
        if not src.is_dir():
            return []
        dest = self.ensure_dir(username, name)
        copied = []
        for f in sorted(src.iterdir()):
            if (
                not f.is_file()
                or f.name.startswith(".")
                or f.name in (f"{name}.py", "files.json")
                or f.suffix in (".html", ".zip")
            ):
                continue
            target = dest / f.name
            if not target.exists():
                shutil.copy2(f, target)
                copied.append(f.name)
        return copied

    def reset_to_release(self, username: str, assignment: str) -> Path | None:
        """Archive existing notebook and optionally copy from release.

        Returns the archive path, or None if no existing file to archive.
        """
        nb = self.assignment_path(username, assignment)
        if not nb.exists():
            return None

        # Archive existing (never overwrite an earlier archive)
        ts = time.strftime("%Y%m%dT%H%M%S")
        archive = nb.with_suffix(f".bak.{ts}.py")
        n = 1
        while archive.exists():
            archive = nb.with_suffix(f".bak.{ts}-{n}.py")
            n += 1
        shutil.move(str(nb), str(archive))

        # Remove markers
        for marker in (".uploaded", ".exported"):
            m = nb.parent / marker
            m.unlink(missing_ok=True)

        # Copy from release if available
        release = self.release_path(assignment)
        if release is not None:
            shutil.copy2(str(release), str(nb))
            self.copy_support_files(username, assignment)
            self.mark_uploaded(username, assignment)
            self.mark_fetched(username, assignment)

        return archive

    # -- listing --

    def _read_manifest(self, name: str) -> dict:
        """Read ``files.json`` manifest for a release item."""
        if self.release_dir is None:
            return {}
        manifest = self.release_dir / name / "files.json"
        if manifest.is_file():
            import json

            return json.loads(manifest.read_text(encoding="utf-8"))
        return {}

    def item_type(self, name: str) -> str:
        """Return ``'lecture'`` or ``'assignment'`` for a release item.

        Reads from the ``files.json`` manifest first, then falls back to
        ``mograder-type`` in the notebook's PEP 723 block.
        """
        manifest = self._read_manifest(name)
        t = manifest.get("type")
        if t:
            return t
        # Fallback: read from notebook metadata
        if self.release_dir:
            nb = self.release_dir / name / f"{name}.py"
            if nb.is_file():
                from mograder.grading.cells import read_notebook_type

                return read_notebook_type(nb.read_text(encoding="utf-8"))
        return "assignment"

    def _list_all_items(self) -> list[str]:
        """List all dirs in release_dir that contain a matching .py file."""
        if self.release_dir is None or not self.release_dir.is_dir():
            return []
        return sorted(
            d.name
            for d in self.release_dir.iterdir()
            if d.is_dir() and (d / f"{d.name}.py").is_file()
        )

    def list_assignments(self) -> list[str]:
        """List available assignments (not lectures or demos) from release_dir."""
        return [
            name
            for name in self._list_all_items()
            if self.item_type(name) not in ("lecture", "demo")
        ]

    def list_demos(self) -> list[str]:
        """Demos: run-only notebooks reached by deep link (``/run/<name>/``),
        never listed on the dashboard and not subject to the schedule."""
        return [
            name for name in self._list_all_items() if self.item_type(name) == "demo"
        ]

    def list_lectures(self) -> list[str]:
        """List available lectures from release_dir."""
        return [
            name for name in self._list_all_items() if self.item_type(name) == "lecture"
        ]
