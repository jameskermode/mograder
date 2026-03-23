"""Tests for hub SessionManager (Phase 4)."""

from __future__ import annotations

import asyncio
import time
from unittest.mock import MagicMock, patch

import pytest

from mograder.hub.models import MarimoSession
from mograder.hub.spawner import SessionManager


@pytest.fixture
def notebooks_dir(tmp_path):
    d = tmp_path / "notebooks"
    d.mkdir()
    return d


@pytest.fixture
def sm(notebooks_dir):
    return SessionManager(notebooks_dir=notebooks_dir, session_ttl=60)


def _create_notebook(notebooks_dir, username, assignment):
    """Create a notebook file for testing."""
    d = notebooks_dir / username / assignment
    d.mkdir(parents=True, exist_ok=True)
    nb = d / f"{assignment}.py"
    nb.write_text("import marimo\napp = marimo.App()\n")
    return nb


def _fake_popen(pid=12345):
    """Create a mock Popen with a .pid and .returncode."""
    proc = MagicMock()
    proc.pid = pid
    proc.returncode = None  # running
    proc.poll.return_value = None
    proc.wait = MagicMock()
    return proc


class TestGetOrSpawn:
    def test_creates_session(self, sm, notebooks_dir):
        """get_or_spawn creates a new MarimoSession."""
        _create_notebook(notebooks_dir, "alice", "hw1")

        with patch.object(sm, "_spawn_process") as mock_spawn:
            proc = _fake_popen()
            mock_spawn.return_value = (proc, 18000)
            session = asyncio.run(sm.get_or_spawn("alice", "hw1"))

        assert isinstance(session, MarimoSession)
        assert session.username == "alice"
        assert session.assignment == "hw1"
        assert session.port == 18000
        assert session.process is proc

    def test_reuses_live_session(self, sm, notebooks_dir):
        """Second call returns same session, updates last_seen."""
        _create_notebook(notebooks_dir, "alice", "hw1")

        async def run():
            proc = _fake_popen()
            with patch.object(sm, "_spawn_process", return_value=(proc, 18000)) as ms:
                s1 = await sm.get_or_spawn("alice", "hw1")
                old_last_seen = s1.last_seen
                await asyncio.sleep(0.05)
                s2 = await sm.get_or_spawn("alice", "hw1")
                return s1, s2, old_last_seen, ms

        s1, s2, old_last_seen, ms = asyncio.run(run())
        assert s1 is s2
        assert s2.last_seen > old_last_seen
        ms.assert_called_once()

    def test_file_not_found(self, sm):
        """No notebook file raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            asyncio.run(sm.get_or_spawn("alice", "hw1"))

    def test_concurrent_spawn_same_key(self, sm, notebooks_dir):
        """Two concurrent calls for same key only spawn once."""
        _create_notebook(notebooks_dir, "alice", "hw1")
        call_count = 0

        async def slow_spawn(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            await asyncio.sleep(0.05)
            return (_fake_popen(), 18000)

        with patch.object(sm, "_spawn_process", side_effect=slow_spawn):

            async def run():
                return await asyncio.gather(
                    sm.get_or_spawn("alice", "hw1"),
                    sm.get_or_spawn("alice", "hw1"),
                )

            s1, s2 = asyncio.run(run())

        assert s1 is s2
        assert call_count == 1


class TestTerminate:
    def test_kills_and_removes(self, sm, notebooks_dir):
        """terminate removes session from map."""
        _create_notebook(notebooks_dir, "alice", "hw1")

        with patch.object(sm, "_spawn_process") as mock_spawn:
            proc = _fake_popen()
            mock_spawn.return_value = (proc, 18000)
            asyncio.run(sm.get_or_spawn("alice", "hw1"))

        with patch("mograder.hub.spawner._kill_tree"):
            asyncio.run(sm.terminate("alice", "hw1"))

        assert ("alice", "hw1") not in sm.sessions


class TestCullIdle:
    def test_terminates_old_sessions(self, sm, notebooks_dir):
        """Session past TTL is terminated."""
        _create_notebook(notebooks_dir, "alice", "hw1")

        with patch.object(sm, "_spawn_process") as mock_spawn:
            proc = _fake_popen()
            mock_spawn.return_value = (proc, 18000)
            session = asyncio.run(sm.get_or_spawn("alice", "hw1"))

        # Backdate last_seen
        session.last_seen = time.time() - 120

        with patch("mograder.hub.spawner._kill_tree"):
            asyncio.run(sm.cull_idle())

        assert ("alice", "hw1") not in sm.sessions

    def test_keeps_active_sessions(self, sm, notebooks_dir):
        """Session within TTL is kept."""
        _create_notebook(notebooks_dir, "alice", "hw1")

        with patch.object(sm, "_spawn_process") as mock_spawn:
            proc = _fake_popen()
            mock_spawn.return_value = (proc, 18000)
            asyncio.run(sm.get_or_spawn("alice", "hw1"))

        with patch("mograder.hub.spawner._kill_tree"):
            asyncio.run(sm.cull_idle())

        assert ("alice", "hw1") in sm.sessions


class TestBwrap:
    def test_bwrap_edit_command(self, sm, notebooks_dir):
        """When use_bubblewrap=True, command includes bwrap."""
        sm.use_bubblewrap = True
        nb = _create_notebook(notebooks_dir, "alice", "hw1")

        with patch("shutil.which", return_value="/usr/bin/bwrap"):
            cmd = sm._build_command("alice", "hw1", nb, 18000)

        assert cmd[0] == "bwrap"
        assert "--unshare-net" in cmd
        assert "--die-with-parent" in cmd

    def test_bwrap_fallback(self, sm, notebooks_dir):
        """bwrap not on PATH → no bwrap in command."""
        sm.use_bubblewrap = True
        nb = _create_notebook(notebooks_dir, "alice", "hw1")

        with patch("shutil.which", return_value=None):
            cmd = sm._build_command("alice", "hw1", nb, 18000)

        assert cmd[0] != "bwrap"


class TestEnv:
    def test_uv_cache_not_overridden(self, sm, notebooks_dir):
        """Env has XDG_CONFIG_HOME and XDG_DATA_HOME but not HOME."""
        nb = _create_notebook(notebooks_dir, "alice", "hw1")
        env = sm._build_env("alice", nb)
        assert "XDG_CONFIG_HOME" in env
        assert "XDG_DATA_HOME" in env
        # HOME and XDG_CACHE_HOME should NOT be set
        assert "HOME" not in env
        assert "XDG_CACHE_HOME" not in env


class TestWarmCache:
    def test_parses_deps(self):
        """PEP 723 deps are extracted correctly."""
        source = """# /// script
# dependencies = [
#     "numpy",
#     "jax",
# ]
# ///

import numpy as np
"""
        from mograder.hub.spawner import parse_pep723_deps

        deps = parse_pep723_deps(source)
        assert deps == ["numpy", "jax"]

    def test_no_deps(self):
        """No PEP 723 block returns empty list."""
        from mograder.hub.spawner import parse_pep723_deps

        deps = parse_pep723_deps("import numpy as np\n")
        assert deps == []
