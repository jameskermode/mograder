"""Demos on the hub: run-only (code hidden), deep links only, never listed."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from starlette.testclient import TestClient

from mograder.core.auth import INSTRUCTOR_USER, make_token
from mograder.hub.app import create_hub_app
from mograder.hub.spawner import SessionManager

SECRET = "test-secret"


@pytest.fixture
def hub(tmp_path):
    notebooks, release = tmp_path / "hub-notebooks", tmp_path / "hub-release"
    notebooks.mkdir()
    for name, kind in (("A1", "assignment"), ("L01", "lecture"), ("gp-demo", "demo")):
        d = release / name
        d.mkdir(parents=True)
        (d / f"{name}.py").write_text(f"# {name}\n", encoding="utf-8")
        (d / "files.json").write_text(json.dumps({"type": kind}), encoding="utf-8")
    app = create_hub_app(
        tmp_path, notebooks_dir=notebooks, release_dir=release, secret=SECRET
    )
    spawn = AsyncMock(return_value=SimpleNamespace(port=1234))
    app.state.session_mgr.get_or_spawn_run = spawn

    def client(user):
        return TestClient(
            app,
            raise_server_exceptions=False,
            headers={"Authorization": f"Bearer {make_token(SECRET, user)}"},
        )

    return SimpleNamespace(
        app=app,
        spawn=spawn,
        student=client("alice"),
        instructor=client(INSTRUCTOR_USER),
    )


def test_demos_not_listed(hub):
    for c in (hub.student, hub.instructor):
        assert sorted(i["name"] for i in c.get("/assignments").json()) == ["A1", "L01"]
    assert hub.app.state.storage.list_demos() == ["gp-demo"]
    assert "gp-demo" not in hub.app.state.storage.list_assignments()


def test_demo_runs_with_code_hidden(hub):
    r = hub.student.post("/start-run/gp-demo")
    assert r.status_code == 200, r.text
    assert r.json()["url"] == "run/user/alice/gp-demo/"
    assert hub.spawn.await_args.kwargs["include_code"] is False
    hub.student.post("/start-run/L01")
    assert hub.spawn.await_args.kwargs["include_code"] is True


def test_demo_no_copies_or_source_for_students(hub):
    assert hub.student.post("/start-edit-deep/gp-demo").status_code == 400
    assert hub.student.post("/download-release/alice/gp-demo").status_code == 400
    assert hub.student.get("/release/gp-demo/gp-demo.py").status_code == 400
    # instructors may still fetch the source
    assert hub.instructor.get("/release/gp-demo/gp-demo.py").status_code == 200


def test_publish_type_validated(hub):
    r = hub.instructor.post("/publish/x?type=bogus", files={"files": ("x.py", b"#")})
    assert r.status_code == 400


def test_run_command_hides_code_for_demos(tmp_path):
    sm = SessionManager(notebooks_dir=tmp_path)
    nb = Path(tmp_path / "d.py")
    lecture = sm._build_run_command("u", "L01", nb, 18000)
    demo = sm._build_run_command("u", "gp-demo", nb, 18000, include_code=False)
    assert "--include-code" in lecture and "--include-code" not in demo


def test_deep_link_page_leaves_no_history_entry(hub):
    """The spinner page replaces itself with the session (location.replace),
    so the browser's Back button returns to the linking page instead of
    re-entering the spinner, which would forward to the session again."""
    html = hub.student.get("/run/gp-demo/").text
    assert "window.location.replace(" in html
    assert "window.location.href=" not in html
