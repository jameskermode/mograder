"""Tests for scheduled visibility of hub items."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from click.testing import CliRunner
from starlette.testclient import TestClient

from mograder.core.auth import INSTRUCTOR_USER, make_token
from mograder.hub.app import create_hub_app
from mograder.hub.storage import StorageManager

SECRET = "test-secret"
LECTURE = '# /// script\n# [tool.mograder]\n# mograder-type = "lecture"\n# ///\n'


def _iso(days: float) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()


@pytest.fixture
def hub(tmp_path):
    notebooks = tmp_path / "hub-notebooks"
    release = tmp_path / "hub-release"
    notebooks.mkdir()
    release.mkdir()
    for name, text in [("A1", "# a1\n"), ("A2", "# a2\n"), ("L01", LECTURE)]:
        d = release / name
        d.mkdir()
        (d / f"{name}.py").write_text(text)
    (release / "L01" / "files.json").write_text(json.dumps({"type": "lecture"}))
    app = create_hub_app(
        tmp_path,
        notebooks_dir=notebooks,
        release_dir=release,
        secret=SECRET,
    )

    def client(user):
        token = make_token(SECRET, user)
        return TestClient(
            app,
            raise_server_exceptions=False,
            headers={"Authorization": f"Bearer {token}"},
        )

    return SimpleNamespace(
        app=app,
        notebooks=notebooks,
        release=release,
        student=client("alice"),
        instructor=client(INSTRUCTOR_USER),
    )


def _set(hub, items, replace=False):
    resp = hub.instructor.post("/visibility", json={"items": items, "replace": replace})
    assert resp.status_code == 200, resp.text
    return resp.json()


class TestStorage:
    def test_unlisted_items_are_visible(self, tmp_path):
        s = StorageManager(tmp_path / "nb", tmp_path / "rel")
        assert s.visibility("A1") == (True, None)

    def test_hidden_and_dates(self, tmp_path):
        s = StorageManager(tmp_path / "nb", tmp_path / "rel")
        future, past = _iso(7), _iso(-7)
        s.write_visibility(
            {
                "A1": {"hidden": True},
                "A2": {"visible_from": future},
                "A3": {"visible_from": past},
            }
        )
        assert s.visibility("A1") == (False, None)
        assert s.visibility("A2") == (False, future)
        assert s.visibility("A3") == (True, past)


class TestSetVisibility:
    def test_students_cannot_set_or_read(self, hub):
        assert hub.student.get("/visibility").status_code == 403
        resp = hub.student.post("/visibility", json={"items": {"A1": {"hidden": True}}})
        assert resp.status_code == 403

    def test_naive_datetime_rejected(self, hub):
        resp = hub.instructor.post(
            "/visibility", json={"items": {"A1": {"visible_from": "2027-01-11T09:00"}}}
        )
        assert resp.status_code == 400

    def test_bad_name_rejected(self, hub):
        resp = hub.instructor.post("/visibility", json={"items": {"../x": {}}})
        assert resp.status_code == 400

    def test_empty_entry_makes_visible_and_replace(self, hub):
        _set(hub, {"A1": {"hidden": True}, "A2": {"hidden": True}})
        assert _set(hub, {"A1": {}}) == {"A2": {"hidden": True}}
        assert _set(hub, {"L01": {"hidden": True}}, replace=True) == {
            "L01": {"hidden": True}
        }

    def test_survives_republish(self, hub):
        _set(hub, {"A1": {"hidden": True}})
        resp = hub.instructor.post(
            "/publish/A1", files={"files": ("A1.py", b"# new\n", "text/x-python")}
        )
        assert resp.status_code == 200
        assert hub.instructor.get("/visibility").json() == {"A1": {"hidden": True}}


class TestStudentAccess:
    def test_listing_hides_closed_items(self, hub):
        _set(hub, {"A1": {"hidden": True}, "L01": {"visible_from": _iso(3)}})
        names = {i["name"] for i in hub.student.get("/assignments").json()}
        assert names == {"A2"}

    def test_instructor_listing_shows_all_with_state(self, hub):
        opens = _iso(3)
        _set(hub, {"A1": {"hidden": True}, "L01": {"visible_from": opens}})
        items = {i["name"]: i for i in hub.instructor.get("/assignments").json()}
        assert set(items) == {"A1", "A2", "L01"}
        assert items["A1"]["visible"] is False
        assert items["L01"]["visible_from"] == datetime.fromisoformat(opens).isoformat()
        assert items["A2"]["visible"] is True

    def test_open_after_date(self, hub):
        _set(hub, {"A1": {"visible_from": _iso(-1)}})
        names = {i["name"] for i in hub.student.get("/assignments").json()}
        assert "A1" in names

    def test_deep_links_and_downloads_blocked(self, hub):
        _set(hub, {"A1": {"visible_from": _iso(3)}, "L01": {"hidden": True}})
        r = hub.student.post("/start-edit-deep/A1")
        assert r.status_code == 404
        assert r.json()["detail"].startswith("Not available until")
        assert hub.student.post("/start-run/L01").json()["detail"] == "Not available"
        assert hub.student.get("/release/A1/A1.py").status_code == 404
        assert hub.student.post("/download-release/alice/A1").status_code == 404
        assert not (hub.notebooks / "alice" / "A1").exists()

    def test_existing_copy_keeps_access(self, hub):
        d = hub.notebooks / "alice" / "A1"
        d.mkdir(parents=True)
        (d / "A1.py").write_text("# my work\n")
        _set(hub, {"A1": {"hidden": True}})
        names = {i["name"] for i in hub.student.get("/assignments").json()}
        assert "A1" in names
        fake = SimpleNamespace(port=1234)
        with patch.object(
            hub.app.state.session_mgr, "get_or_spawn", AsyncMock(return_value=fake)
        ):
            assert hub.student.post("/start-edit-deep/A1").status_code == 200

    def test_instructor_bypasses(self, hub):
        _set(hub, {"A1": {"hidden": True}})
        assert hub.instructor.get("/release/A1/A1.py").status_code == 200


class TestScheduleCLI:
    def _run(self, tmp_path, toml, published=("L01-Intro", "A1-Setup", "A2-Extra")):
        from mograder.cli import cli as main

        f = tmp_path / "schedule.toml"
        f.write_text(toml)
        calls = []

        def fake_api(base, token, method, path, **kw):
            calls.append((method, path, kw.get("json")))
            if path == "/assignments":
                return [
                    {"name": n, "type": "lecture" if n[0] == "L" else "assignment"}
                    for n in published
                ]
            if method == "POST":
                return {}
            return {}

        with patch("mograder.cli._hub_api", fake_api):
            result = CliRunner().invoke(
                main, ["hub", "schedule", str(f), "--url", "http://hub", "--token", "t"]
            )
        assert result.exit_code == 0, result.output
        posts = [c[2] for c in calls if c[0] == "POST"]
        return posts[0] if posts else None

    def test_weeks_items_and_hide_unlisted(self, tmp_path):
        body = self._run(
            tmp_path,
            """
start = 2027-01-11
time = "09:00"
hide_unlisted = true
[weeks]
1 = ["L01"]
2 = ["A1-Setup"]
[items]
"A9-Later" = 2027-03-01T14:30:00
""",
        )
        assert body["replace"] is True
        items = body["items"]
        # prefix resolved against published names; GMT in January
        assert items["L01-Intro"] == {"visible_from": "2027-01-11T09:00:00+00:00"}
        assert items["A1-Setup"] == {"visible_from": "2027-01-18T09:00:00+00:00"}
        assert items["A9-Later"] == {"visible_from": "2027-03-01T14:30:00+00:00"}
        assert items["A2-Extra"] == {"hidden": True}

    def test_summer_time_offset(self, tmp_path):
        body = self._run(tmp_path, 'start = 2027-04-05\n[weeks]\n1 = ["L01"]\n')
        assert body["items"]["L01-Intro"] == {
            "visible_from": "2027-04-05T09:00:00+01:00"
        }


class TestSupportFiles:
    """Student copies get the release's data and images (edit sessions run there)."""

    def _release_with_data(self, hub):
        d = hub.release / "A1"
        (d / "data.csv").write_text("x\n1\n")
        (d / "fig.png").write_bytes(b"png")
        (d / "A1.html").write_text("<html>")
        (d / "A1.zip").write_bytes(b"zip")
        (d / "files.json").write_text("{}")

    def test_copy_support_files(self, hub):
        self._release_with_data(hub)
        storage = hub.app.state.storage
        assert storage.copy_support_files("alice", "A1") == ["data.csv", "fig.png"]
        mine = hub.notebooks / "alice" / "A1" / "data.csv"
        mine.write_text("changed\n")
        assert storage.copy_support_files("alice", "A1") == []
        assert mine.read_text() == "changed\n"  # never overwritten

    def test_deep_link_copies_support_files(self, hub):
        self._release_with_data(hub)
        fake = SimpleNamespace(port=1234)
        with patch.object(
            hub.app.state.session_mgr, "get_or_spawn", AsyncMock(return_value=fake)
        ):
            assert hub.student.post("/start-edit-deep/A1").status_code == 200
        names = sorted(
            p.name
            for p in (hub.notebooks / "alice" / "A1").iterdir()
            if not p.name.startswith(".")
        )
        assert names == ["A1.py", "data.csv", "fig.png"]

    def test_lecture_edit_copy(self, hub):
        """Lectures can be opened as the student's own editable copy."""
        fake = SimpleNamespace(port=1234)
        with patch.object(
            hub.app.state.session_mgr, "get_or_spawn", AsyncMock(return_value=fake)
        ):
            r = hub.student.post("/start-edit-deep/L01")
        assert r.status_code == 200
        assert r.json()["url"] == "edit/user/alice/L01/"
        assert (hub.notebooks / "alice" / "L01" / "L01.py").read_text() == LECTURE


class TestPublishReplaces:
    def test_republish_removes_stale_files(self, hub):
        d = hub.release / "A1"
        (d / "A1.html").write_text("<html>old preview with solutions</html>")
        (d / ".venv").mkdir()
        resp = hub.instructor.post(
            "/publish/A1", files={"files": ("A1.py", b"# new\n", "text/x-python")}
        )
        assert resp.status_code == 200
        assert resp.json()["files"] == ["A1.py"]
        assert not (d / "A1.html").exists()
        assert (d / ".venv").is_dir()

    def test_traversal_rejected(self, hub):
        resp = hub.instructor.post(
            "/publish/A1", files={"files": ("../A2/A2.py", b"x", "text/x-python")}
        )
        assert resp.status_code == 400
        assert (hub.release / "A2" / "A2.py").read_text() == "# a2\n"


class TestGetLatest:
    """Fetching the release never loses the student's work."""

    def _copy(self, hub, name="A1", text="# my work\n"):
        d = hub.notebooks / "alice" / name
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{name}.py").write_text(text)
        return d

    def test_download_archives_existing_copy(self, hub):
        d = self._copy(hub)
        r = hub.student.post("/download-release/alice/A1")
        assert r.status_code == 200
        archive = r.json()["archive"]
        assert archive.startswith("A1.bak.")
        assert (d / archive).read_text() == "# my work\n"
        assert (d / "A1.py").read_text() == "# a1\n"

    def test_download_without_copy(self, hub):
        r = hub.student.post("/download-release/alice/A1")
        assert r.status_code == 200
        assert r.json()["archive"] is None
        assert (hub.notebooks / "alice" / "A1" / ".fetched").exists()

    def test_reset_twice_keeps_both_archives(self, hub):
        d = self._copy(hub, text="# first\n")
        assert hub.student.post("/reset/alice/A1").status_code == 200
        (d / "A1.py").write_text("# second\n")
        assert hub.student.post("/reset/alice/A1").status_code == 200
        backups = sorted(p.read_text() for p in d.glob("A1.bak.*.py"))
        assert backups == ["# first\n", "# second\n"]

    def test_update_available_after_republish(self, hub):
        import os
        import time

        storage = hub.app.state.storage
        assert hub.student.post("/download-release/alice/A1").status_code == 200
        assert storage.release_updated("alice", "A1") is False
        release = hub.release / "A1" / "A1.py"
        later = time.time() + 60
        os.utime(release, (later, later))
        assert storage.release_updated("alice", "A1") is True
        items = {i["name"]: i for i in hub.student.get("/assignments").json()}
        assert items["A1"]["updated"] is True

    def test_lecture_listing_reports_copy(self, hub):
        items = {i["name"]: i for i in hub.student.get("/assignments").json()}
        assert items["L01"]["has_copy"] is False
        self._copy(hub, name="L01", text=LECTURE)
        items = {i["name"]: i for i in hub.student.get("/assignments").json()}
        assert items["L01"]["has_copy"] is True
