"""'View as': instructors temporarily see the hub as a student (optionally as
of a date) and the grader as a marker; it can only reduce privileges."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from starlette.testclient import TestClient

from mograder.core import view_as
from mograder.core.auth import make_token
from mograder.grader.asgi import resolve_user
from mograder.hub.app import create_hub_app

SECRET = "test-secret"


def _iso(days: float) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()


class TestCore:
    def test_parse(self):
        assert view_as.parse(None) is None
        assert view_as.parse("student") == ("student", None)
        role, as_of = view_as.parse("student|2027-01-18T09:00:00+00:00")
        assert role == "student" and as_of.startswith("2027-01-18T09:00")
        assert view_as.parse("student|garbage") == ("student", None)

    def test_apply_only_reduces_instructors(self):
        prof = {"username": "prof", "is_instructor": True}
        stud = {"username": "alice", "is_instructor": False}
        switched = view_as.apply(prof, "student", {"student"})
        assert switched["is_instructor"] is False
        assert switched["is_student"] and switched["real_is_instructor"]
        # a student's cookie changes nothing (no as_of, no role)
        assert view_as.apply(stud, "student|2099-01-01", {"student"}) == stud
        # a role the app does not offer is ignored
        assert view_as.apply(prof, "marker", {"student"})["is_instructor"]

    def test_cookie_roundtrip(self):
        header = view_as.cookie_header("student", "2027-01-18T09:00:00+00:00")
        value = header.decode().split(";")[0].split("=", 1)[1]
        assert view_as.parse(value)[0] == "student"
        assert view_as.read_cookie([(b"cookie", b"x=1; " + header.split(b";")[0])])
        assert b"Max-Age=0" in view_as.cookie_header(None)


def test_grader_instructor_views_as_marker():
    user = resolve_user(
        "127.0.0.1",
        "prof",
        instructors={"prof"},
        markers={"gta"},
        trusted_proxies=set(),
        trust_local_proxy=True,
    )
    seen = view_as.apply(user, "marker", {"marker"})
    assert seen["is_marker"] and not seen["is_instructor"]


@pytest.fixture
def hub(tmp_path):
    notebooks, release = tmp_path / "hub-notebooks", tmp_path / "hub-release"
    notebooks.mkdir()
    for name in ("A1", "A2"):
        (release / name).mkdir(parents=True)
        (release / name / f"{name}.py").write_text(f"# {name}\n", encoding="utf-8")
    app = create_hub_app(
        tmp_path,
        notebooks_dir=notebooks,
        release_dir=release,
        secret=SECRET,
        instructors={"prof"},
    )
    # A2 opens in 10 days
    app.state.storage.write_visibility({"A2": {"visible_from": _iso(10)}})

    def client(user):
        return TestClient(
            app,
            raise_server_exceptions=False,
            headers={"Authorization": f"Bearer {make_token(SECRET, user)}"},
        )

    return client


def _names(client):
    resp = client.get("/assignments")
    assert resp.status_code == 200, resp.text
    return sorted(a["name"] for a in resp.json())


def test_sso_instructor_sees_scheduled_items(hub):
    assert _names(hub("prof")) == ["A1", "A2"]
    assert _names(hub("alice")) == ["A1"]


def test_view_as_student_now_and_as_of(hub):
    prof = hub("prof")
    r = prof.get("/view-as?role=student", follow_redirects=False)
    assert (
        r.status_code == 303 and "mograder_view_as=student" in r.headers["set-cookie"]
    )
    assert _names(prof) == ["A1"]  # as a student today: A2 not open yet
    date = (datetime.now(timezone.utc) + timedelta(days=11)).date().isoformat()
    prof.get(f"/view-as?role=student&as_of={date}T09:00", follow_redirects=False)
    assert _names(prof) == ["A1", "A2"]  # as a student in 11 days
    prof.get("/view-as?role=", follow_redirects=False)
    assert _names(prof) == ["A1", "A2"]  # back to instructor


def test_students_cannot_switch_or_time_travel(hub):
    alice = hub("alice")
    assert alice.get("/view-as?role=student", follow_redirects=False).status_code == 403
    alice.cookies.set(view_as.COOKIE, "student|2099-01-01T00:00:00+00:00")
    assert _names(alice) == ["A1"]  # a forged cookie changes nothing
