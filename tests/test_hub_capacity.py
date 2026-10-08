"""Hub capacity controls: per-session thread caps and admission control."""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest
from starlette.testclient import TestClient

from mograder.hub import spawner
from mograder.hub.app import create_hub_app
from mograder.hub.spawner import BUSY_MESSAGE, HubBusy, SessionManager, thread_env


def _notebook(root, username, assignment):
    d = root / username / assignment
    d.mkdir(parents=True, exist_ok=True)
    nb = d / f"{assignment}.py"
    nb.write_text("import marimo\napp = marimo.App()\n", encoding="utf-8")
    return nb


class TestThreadEnv:
    def test_off_by_default(self):
        assert thread_env(0) == {}

    def test_caps_thread_pools(self):
        env = thread_env(2)
        assert env["OMP_NUM_THREADS"] == "2"
        assert env["OPENBLAS_NUM_THREADS"] == "2"
        assert env["MKL_NUM_THREADS"] == "2"
        assert "XLA_FLAGS" not in env  # XLA can only be made single-threaded

    def test_single_thread_includes_xla(self, monkeypatch):
        monkeypatch.setenv("XLA_FLAGS", "--xla_foo=1")
        flags = thread_env(1)["XLA_FLAGS"]
        assert flags.startswith("--xla_foo=1 ")
        assert "--xla_cpu_multi_thread_eigen=false" in flags

    def test_session_env_carries_cap(self, tmp_path):
        sm = SessionManager(notebooks_dir=tmp_path, session_threads=2)
        nb = _notebook(tmp_path, "alice", "hw1")
        assert sm._build_env("alice", nb)["OMP_NUM_THREADS"] == "2"

    def test_session_env_uncapped_by_default(self, tmp_path):
        sm = SessionManager(notebooks_dir=tmp_path)
        nb = _notebook(tmp_path, "alice", "hw1")
        assert "OMP_NUM_THREADS" not in sm._build_env("alice", nb)


class TestAdmission:
    def test_refuses_new_session_when_memory_low(self, tmp_path):
        sm = SessionManager(notebooks_dir=tmp_path, min_free_mb=2048)
        _notebook(tmp_path, "alice", "hw1")
        with (
            patch.object(spawner, "mem_available_mb", return_value=1000),
            patch.object(sm, "_spawn_process") as spawn,
        ):
            with pytest.raises(HubBusy):
                asyncio.run(sm.get_or_spawn("alice", "hw1"))
        spawn.assert_not_called()
        assert sm._reserved_ports == set()

    def test_admits_when_memory_ok(self, tmp_path):
        sm = SessionManager(notebooks_dir=tmp_path, min_free_mb=2048)
        _notebook(tmp_path, "alice", "hw1")

        async def fake_spawn(username, assignment, nb, port):
            from unittest.mock import MagicMock

            proc = MagicMock()
            proc.returncode = None
            return (proc, port)

        with (
            patch.object(spawner, "mem_available_mb", return_value=8000),
            patch.object(sm, "_spawn_process", side_effect=fake_spawn),
        ):
            session = asyncio.run(sm.get_or_spawn("alice", "hw1"))
        assert session.username == "alice"

    def test_existing_session_kept_when_memory_low(self, tmp_path):
        """A student already working is never refused."""
        sm = SessionManager(notebooks_dir=tmp_path, min_free_mb=2048)
        _notebook(tmp_path, "alice", "hw1")

        async def fake_spawn(username, assignment, nb, port):
            from unittest.mock import MagicMock

            proc = MagicMock()
            proc.returncode = None
            return (proc, port)

        with patch.object(sm, "_spawn_process", side_effect=fake_spawn):
            with patch.object(spawner, "mem_available_mb", return_value=8000):
                first = asyncio.run(sm.get_or_spawn("alice", "hw1"))
            with patch.object(spawner, "mem_available_mb", return_value=100):
                again = asyncio.run(sm.get_or_spawn("alice", "hw1"))
        assert again is first

    def test_disabled_by_default(self, tmp_path):
        sm = SessionManager(notebooks_dir=tmp_path)
        with patch.object(spawner, "mem_available_mb", return_value=1):
            sm._check_capacity()  # no exception

    def test_unknown_memory_admits(self, tmp_path):
        sm = SessionManager(notebooks_dir=tmp_path, min_free_mb=2048)
        with patch.object(spawner, "mem_available_mb", return_value=None):
            sm._check_capacity()

    def test_deep_link_returns_503_with_message(self, tmp_path):
        notebooks, release = tmp_path / "nb", tmp_path / "rel"
        notebooks.mkdir()
        (release / "hw1").mkdir(parents=True)
        (release / "hw1" / "hw1.py").write_text("# release", encoding="utf-8")
        app = create_hub_app(
            tmp_path,
            dev=True,
            notebooks_dir=notebooks,
            release_dir=release,
            min_free_mb=2048,
        )
        client = TestClient(
            app, raise_server_exceptions=False, headers={"X-Remote-User": "dev-user"}
        )
        with patch.object(spawner, "mem_available_mb", return_value=500):
            resp = client.post("/start-edit-deep/hw1")
        assert resp.status_code == 503
        assert resp.json()["detail"] == BUSY_MESSAGE


def test_mem_available_reads_proc_meminfo():
    mb = spawner.mem_available_mb()
    assert mb is None or mb > 0
