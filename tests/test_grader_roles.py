"""Formgrader roles: instructors, markers (GTAs) and marking access."""

from __future__ import annotations

import pytest
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from mograder.grader.asgi import InstructorOnly, resolve_user
from mograder.grader.marking import marker_may_edit, marking_open, set_marking_open

INSTR = {"prof"}
MARK = {"gta1", "gta2"}
PROXY = {"10.0.0.5"}


def _user(ip, header, *, instructors=INSTR, markers=MARK, local_proxy=False):
    return resolve_user(
        ip,
        header,
        instructors=instructors,
        markers=markers,
        trusted_proxies=PROXY,
        trust_local_proxy=local_proxy,
    )


class TestResolveUser:
    def test_localhost_without_header_is_instructor(self):
        assert _user("127.0.0.1", None)["is_instructor"]
        assert _user("127.0.0.1", None, local_proxy=True)["is_instructor"]

    def test_localhost_header_ignored_unless_local_proxy_trusted(self):
        # without the opt-in, local access stays instructor (old behaviour)
        assert _user("127.0.0.1", "gta1")["is_instructor"]

    def test_tunnelled_identities(self):
        """Through an SSH tunnel (localhost) the proxy's header decides."""
        u = _user("127.0.0.1", "gta1", local_proxy=True)
        assert u == {"username": "gta1", "is_instructor": False, "is_marker": True}
        assert _user("127.0.0.1", "prof", local_proxy=True)["is_instructor"]
        assert _user("127.0.0.1", "stranger", local_proxy=True) is None

    def test_trusted_proxy(self):
        assert _user("10.0.0.5", "prof")["is_instructor"]
        assert _user("10.0.0.5", "gta2")["is_marker"]
        assert _user("10.0.0.5", "stranger") is None
        assert _user("10.0.0.5", None) is None

    def test_untrusted_source_refused(self):
        assert _user("192.0.2.1", "prof") is None

    def test_no_marker_list_makes_others_markers(self):
        u = _user("10.0.0.5", "someone", markers=set())
        assert u["is_marker"] and not u["is_instructor"]

    def test_no_roles_configured_keeps_everyone_instructor(self):
        assert _user("10.0.0.5", "someone", instructors=set(), markers=set())[
            "is_instructor"
        ]


def _wrapped(user):
    async def ok(request):
        return PlainTextResponse("ok")

    inner = InstructorOnly(Starlette(routes=[Route("/", ok)]))

    async def app(scope, receive, send):
        scope["user"] = user
        await inner(scope, receive, send)

    return TestClient(app)


@pytest.mark.parametrize(
    "user,status",
    [
        ({"username": "", "is_instructor": True, "is_marker": False}, 200),
        ({"username": "gta1", "is_instructor": False, "is_marker": True}, 403),
    ],
)
def test_edit_api_is_instructor_only(user, status):
    assert _wrapped(user).get("/").status_code == status


class TestMarking:
    def test_open_close(self, tmp_path):
        assert marking_open(tmp_path) == set()
        set_marking_open(tmp_path, "A3", True)
        set_marking_open(tmp_path, "A4", True)
        set_marking_open(tmp_path, "A4", False)
        assert marking_open(tmp_path) == {"A3"}

    def test_unreadable_file_means_nothing_open(self, tmp_path):
        (tmp_path / "marking.json").write_text("{oops", encoding="utf-8")
        assert marking_open(tmp_path) == set()

    def test_marker_may_edit(self, tmp_path):
        sub = tmp_path / "autograded" / "A3" / "alice.py"
        sub.parent.mkdir(parents=True)
        sub.write_text("", encoding="utf-8")
        other = tmp_path / "autograded" / "A4" / "bob.py"
        source = tmp_path / "source" / "A3" / "A3.py"
        assert not marker_may_edit(sub, tmp_path, "autograded")  # not open yet
        set_marking_open(tmp_path, "A3", True)
        assert marker_may_edit(sub, tmp_path, "autograded")
        assert not marker_may_edit(other, tmp_path, "autograded")  # A4 closed
        assert not marker_may_edit(source, tmp_path, "autograded")  # solutions
        escape = (
            tmp_path / "autograded" / "A3" / ".." / ".." / "source" / "A3" / "A3.py"
        )
        assert not marker_may_edit(escape, tmp_path, "autograded")
