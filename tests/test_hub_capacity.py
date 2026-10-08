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
            sm._check_capacity("hw1")  # no exception

    def test_unknown_memory_admits(self, tmp_path):
        sm = SessionManager(notebooks_dir=tmp_path, min_free_mb=2048)
        with patch.object(spawner, "mem_available_mb", return_value=None):
            sm._check_capacity("hw1")

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


class TestProjectedAdmission:
    """Sessions grow after they start: admission reserves the growth to come."""

    def _sm(self, tmp_path, **kw):
        return SessionManager(
            notebooks_dir=tmp_path / "nb", course_dir=tmp_path, min_free_mb=2000, **kw
        )

    def _live(self, sm, item, mem_mb, user="u"):
        from mograder.hub.models import MarimoSession

        sm.sessions[(user, item)] = MarimoSession(
            username=user,
            assignment=item,
            port=1,
            process=None,
            notebook_path="x",
            mem_mb=mem_mb,
        )

    def test_burst_of_small_sessions_refused(self, tmp_path):
        """Free memory looks fine, but the young sessions will grow into it."""
        sm = self._sm(tmp_path, session_mb=1500)
        for i in range(4):
            self._live(sm, "A9", mem_mb=200, user=f"s{i}")
        # 4 x 1300 MB growth to come + 1500 for the new one = 6700 MB
        with patch.object(spawner, "mem_available_mb", return_value=8000):
            with pytest.raises(HubBusy):
                sm._check_capacity("A9")
        with patch.object(spawner, "mem_available_mb", return_value=9000):
            sm._check_capacity("A9")

    def test_grown_sessions_reserve_nothing_more(self, tmp_path):
        sm = self._sm(tmp_path, session_mb=1500)
        for i in range(4):
            self._live(sm, "A9", mem_mb=1600, user=f"s{i}")
        with patch.object(spawner, "mem_available_mb", return_value=3600):
            sm._check_capacity("A9")

    def test_spawns_under_way_count(self, tmp_path):
        sm = self._sm(tmp_path, session_mb=1500)
        sm._starting.extend(["A9", "A9"])
        with patch.object(spawner, "mem_available_mb", return_value=6000):
            with pytest.raises(HubBusy):
                sm._check_capacity("A9")  # 6000 - 3000 - 1500 < 2000

    def test_calibration_per_item(self, tmp_path):
        import json

        (tmp_path / "session_mb.json").write_text(
            json.dumps({"A9": 2500, "default": 500}), encoding="utf-8"
        )
        sm = self._sm(tmp_path, session_mb=100)
        assert sm.memory.estimate("A9") == 2500
        assert sm.memory.estimate("A3") == 500  # file default beats --session-mb
        sm.memory.record("A3", 900)  # measured peak above calibration wins
        assert sm.memory.estimate("A3") == 900


class TestMemoryLedger:
    def test_peaks_persist(self, tmp_path):
        from mograder.hub.memory import MemoryLedger

        led = MemoryLedger(tmp_path)
        led.record("A9", 1200)
        led.record("A9", 900)  # lower sample does not replace the peak
        led.save()
        assert MemoryLedger(tmp_path).measured == {"A9": 1200}

    def test_unreadable_files_ignored(self, tmp_path):
        from mograder.hub.memory import MemoryLedger

        (tmp_path / "session_mb.json").write_text("{not json", encoding="utf-8")
        assert MemoryLedger(tmp_path, default_mb=700).estimate("A1") == 700

    def test_sample_records_current_process(self, tmp_path):
        """On Linux the sampler measures a real process tree (else no-op)."""
        import os
        from types import SimpleNamespace

        from mograder.hub.memory import tree_mb
        from mograder.hub.models import MarimoSession

        sm = SessionManager(notebooks_dir=tmp_path, course_dir=tmp_path)
        sm.sessions[("u", "hw1")] = MarimoSession(
            username="u",
            assignment="hw1",
            port=1,
            process=SimpleNamespace(pid=os.getpid()),
            notebook_path="x",
        )
        sm.sample_memory()
        mine = tree_mb(os.getpid(), {})
        if mine:  # /proc available
            assert sm.sessions[("u", "hw1")].mem_mb > 0
            assert sm.memory.measured["hw1"] > 0
