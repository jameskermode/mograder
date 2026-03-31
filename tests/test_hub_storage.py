"""Tests for hub StorageManager (Phase 2)."""

import time

import pytest

from mograder.hub.storage import StorageManager


@pytest.fixture
def sm(tmp_path):
    """StorageManager with temporary directories."""
    notebooks = tmp_path / "notebooks"
    notebooks.mkdir()
    release = tmp_path / "release"
    release.mkdir()
    return StorageManager(notebooks_dir=notebooks, release_dir=release)


@pytest.fixture
def sm_no_release(tmp_path):
    """StorageManager without a release dir."""
    notebooks = tmp_path / "notebooks"
    notebooks.mkdir()
    return StorageManager(notebooks_dir=notebooks, release_dir=None)


class TestPathSafety:
    def test_path_traversal_username(self, sm):
        """../ in username raises ValueError."""
        with pytest.raises(ValueError, match="escapes"):
            sm._safe_path("../etc", "hw1")

    def test_path_traversal_assignment(self, sm):
        """../ in assignment raises ValueError."""
        with pytest.raises(ValueError, match="escapes"):
            sm._safe_path("alice", "../../etc")

    def test_safe_path_normal(self, sm):
        """Normal paths resolve under notebooks_dir."""
        p = sm._safe_path("alice", "hw1")
        assert str(p).startswith(str(sm.notebooks_dir))


class TestAssignmentPath:
    def test_assignment_path_structure(self, sm):
        """assignment_path returns notebooks_dir/username/assignment/assignment.py."""
        p = sm.assignment_path("alice", "hw1")
        assert p == sm.notebooks_dir / "alice" / "hw1" / "hw1.py"

    def test_assignment_path_traversal(self, sm):
        with pytest.raises(ValueError):
            sm.assignment_path("../root", "hw1")


class TestReleasePath:
    def test_release_path_exists(self, sm):
        """release_path returns path when release file exists."""
        rd = sm.release_dir / "hw1"
        rd.mkdir(parents=True)
        (rd / "hw1.py").write_text("# release")
        assert sm.release_path("hw1") == rd / "hw1.py"

    def test_release_path_missing(self, sm):
        """release_path returns None when no release file."""
        assert sm.release_path("hw1") is None

    def test_release_path_no_release_dir(self, sm_no_release):
        """release_path returns None when release_dir is None."""
        assert sm_no_release.release_path("hw1") is None

    def test_has_release_true(self, sm):
        rd = sm.release_dir / "hw1"
        rd.mkdir(parents=True)
        (rd / "hw1.py").write_text("# release")
        assert sm.has_release("hw1") is True

    def test_has_release_false(self, sm):
        assert sm.has_release("hw1") is False


class TestEnsureDir:
    def test_ensure_dir_creates_parents(self, sm):
        """ensure_dir creates nested directories."""
        p = sm.ensure_dir("alice", "hw1")
        assert p.is_dir()
        assert p == sm.notebooks_dir / "alice" / "hw1"


class TestAssignmentStatus:
    def test_not_started(self, sm):
        """No file → not_started."""
        assert sm.assignment_status("alice", "hw1") == "not_started"

    def test_uploaded(self, sm):
        """File + .uploaded marker → uploaded."""
        d = sm.ensure_dir("alice", "hw1")
        nb = d / "hw1.py"
        nb.write_text("# student code")
        sm.mark_uploaded("alice", "hw1")
        assert sm.assignment_status("alice", "hw1") == "uploaded"

    def test_modified(self, sm):
        """File mtime > .uploaded mtime → modified."""
        d = sm.ensure_dir("alice", "hw1")
        nb = d / "hw1.py"
        nb.write_text("# student code")
        sm.mark_uploaded("alice", "hw1")
        # Touch notebook to make it newer
        time.sleep(0.05)
        nb.write_text("# modified code")
        assert sm.assignment_status("alice", "hw1") == "modified"

    def test_exported(self, sm):
        """Export marker mtime >= file mtime → exported."""
        d = sm.ensure_dir("alice", "hw1")
        nb = d / "hw1.py"
        nb.write_text("# student code")
        sm.mark_uploaded("alice", "hw1")
        time.sleep(0.05)
        sm.mark_exported("alice", "hw1")
        assert sm.assignment_status("alice", "hw1") == "exported"


class TestMarkers:
    def test_mark_uploaded_creates_marker(self, sm):
        d = sm.ensure_dir("alice", "hw1")
        (d / "hw1.py").write_text("# code")
        sm.mark_uploaded("alice", "hw1")
        assert (d / ".uploaded").exists()

    def test_mark_exported_creates_marker(self, sm):
        d = sm.ensure_dir("alice", "hw1")
        (d / "hw1.py").write_text("# code")
        sm.mark_exported("alice", "hw1")
        assert (d / ".exported").exists()


class TestReset:
    def test_reset_to_release(self, sm):
        """Reset archives existing and copies from release."""
        # Set up release
        rd = sm.release_dir / "hw1"
        rd.mkdir(parents=True)
        (rd / "hw1.py").write_text("# release version")

        # Set up student file
        d = sm.ensure_dir("alice", "hw1")
        nb = d / "hw1.py"
        nb.write_text("# student modified")
        sm.mark_uploaded("alice", "hw1")

        result = sm.reset_to_release("alice", "hw1")
        assert result is not None
        # New file should be the release version
        assert nb.read_text() == "# release version"
        # A backup should exist
        baks = list(d.glob("*.bak.*.py"))
        assert len(baks) == 1
        assert baks[0].read_text() == "# student modified"

    def test_reset_archive_only(self, sm_no_release):
        """No release → archive only, file removed."""
        d = sm_no_release.ensure_dir("alice", "hw1")
        nb = d / "hw1.py"
        nb.write_text("# student work")

        result = sm_no_release.reset_to_release("alice", "hw1")
        # Returns the archive path
        assert result is not None
        assert not nb.exists()
        baks = list(d.glob("*.bak.*.py"))
        assert len(baks) == 1

    def test_reset_no_existing_file(self, sm):
        """Reset when no existing file returns None."""
        result = sm.reset_to_release("alice", "hw1")
        assert result is None


class TestListAssignments:
    def test_list_assignments(self, sm):
        """list_assignments returns directory names from release_dir."""
        (sm.release_dir / "hw1").mkdir()
        (sm.release_dir / "hw1" / "hw1.py").write_text("# hw1")
        (sm.release_dir / "hw2").mkdir()
        (sm.release_dir / "hw2" / "hw2.py").write_text("# hw2")
        result = sm.list_assignments()
        assert sorted(result) == ["hw1", "hw2"]

    def test_list_assignments_no_release(self, sm_no_release):
        """No release_dir → empty list."""
        assert sm_no_release.list_assignments() == []

    def test_list_assignments_excludes_lectures(self, sm):
        """list_assignments filters out items with type=lecture in manifest."""
        import json

        (sm.release_dir / "hw1").mkdir()
        (sm.release_dir / "hw1" / "hw1.py").write_text("# hw1")
        (sm.release_dir / "L01").mkdir()
        (sm.release_dir / "L01" / "L01.py").write_text("# lecture")
        (sm.release_dir / "L01" / "files.json").write_text(
            json.dumps({"files": ["L01.py"], "type": "lecture"})
        )
        assert sm.list_assignments() == ["hw1"]


class TestLectures:
    def test_item_type_from_manifest(self, sm):
        """item_type reads type from files.json manifest."""
        import json

        d = sm.release_dir / "L01"
        d.mkdir()
        (d / "L01.py").write_text("# lecture")
        (d / "files.json").write_text(
            json.dumps({"files": ["L01.py"], "type": "lecture"})
        )
        assert sm.item_type("L01") == "lecture"

    def test_item_type_from_pep723(self, sm):
        """item_type falls back to PEP 723 mograder-type metadata."""
        d = sm.release_dir / "L01"
        d.mkdir()
        (d / "L01.py").write_text(
            'import marimo\n\n# /// script\n# mograder-type = "lecture"\n# ///\n\napp = marimo.App()\n'
        )
        assert sm.item_type("L01") == "lecture"

    def test_item_type_default_assignment(self, sm):
        """item_type defaults to 'assignment' when no metadata."""
        d = sm.release_dir / "hw1"
        d.mkdir()
        (d / "hw1.py").write_text("import marimo\napp = marimo.App()\n")
        assert sm.item_type("hw1") == "assignment"

    def test_list_lectures(self, sm):
        """list_lectures returns only items with type=lecture."""
        import json

        (sm.release_dir / "hw1").mkdir()
        (sm.release_dir / "hw1" / "hw1.py").write_text("# hw1")
        (sm.release_dir / "L01").mkdir()
        (sm.release_dir / "L01" / "L01.py").write_text("# lecture")
        (sm.release_dir / "L01" / "files.json").write_text(
            json.dumps({"files": ["L01.py"], "type": "lecture"})
        )
        assert sm.list_lectures() == ["L01"]

    def test_list_lectures_empty(self, sm):
        """list_lectures returns empty when no lectures."""
        (sm.release_dir / "hw1").mkdir()
        (sm.release_dir / "hw1" / "hw1.py").write_text("# hw1")
        assert sm.list_lectures() == []
