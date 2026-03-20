"""Integration tests for bubblewrap (bwrap) sandboxing.

These tests execute real bwrap processes to verify the sandbox properties
that mograder relies on: filesystem isolation, network blocking, /dev access,
and read-only bind mounts.

Requires bubblewrap to be installed and unprivileged user namespaces to be
enabled (the default on most Linux distributions).  Skipped automatically
when bwrap is unavailable or non-functional.

Run with:  uv run pytest tests/test_bwrap_integration.py -v
"""

import os
import subprocess
import textwrap
from pathlib import Path

import pytest

from mograder.runner import _maybe_bwrap_cmd


def _bwrap_works() -> bool:
    """Return True if bwrap can create a sandbox on this system."""
    try:
        r = subprocess.run(
            ["bwrap", "--ro-bind", "/", "/", "--dev", "/dev", "--", "true"],
            capture_output=True,
            timeout=10,
        )
        return r.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


# Single check at import time so we don't repeat it per test.
_BWRAP_OK = _bwrap_works()

requires_bwrap = pytest.mark.skipif(
    not _BWRAP_OK,
    reason="bubblewrap not installed or user namespaces unavailable",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _python_bind_paths() -> list[Path]:
    """Return the bind-mount paths needed to make ``sys.executable`` work
    inside bwrap's ``--tmpfs /home`` sandbox.

    This mirrors what ``run_notebook()`` does: bind ``~/.local`` (for
    uv-managed Python that venv symlinks resolve to) and the venv root
    (for the interpreter + stdlib).
    """
    import sys

    paths: list[Path] = []
    dot_local = Path.home() / ".local"
    if dot_local.is_dir():
        paths.append(dot_local)

    # The venv root (e.g. …/mograder/.venv) contains bin/python3 which is
    # a symlink into ~/.local/share/uv/python/… — we need both the venv
    # (for the symlink) and ~/.local (for the target).
    # Use the un-resolved path to find pyvenv.cfg, since resolve() follows
    # the symlink out of the venv.
    exe = Path(sys.executable)
    for parent in [exe.parent, *exe.parents]:
        if (parent / "pyvenv.cfg").exists():
            paths.append(parent)
            break
    return paths


def _run_in_bwrap(
    script: str,
    cwd: Path,
    ro_bind_extra: list[Path] | None = None,
    timeout: int = 10,
) -> subprocess.CompletedProcess[str]:
    """Run a short Python script inside bwrap via ``_maybe_bwrap_cmd``.

    Automatically adds the bind-mount paths needed for the interpreter
    to work under ``--tmpfs /home``.
    """
    import sys

    extras = _python_bind_paths() + (ro_bind_extra or [])
    cmd = _maybe_bwrap_cmd(
        [sys.executable, "-c", script],
        cwd,
        use_bwrap=True,
        ro_bind_extra=extras,
    )
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=cwd,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@requires_bwrap
class TestBwrapFilesystem:
    """Verify filesystem isolation guarantees."""

    def test_home_dir_hidden(self, tmp_path):
        """--tmpfs /home hides the user's actual home directory contents.

        The bind-mounts for the Python interpreter (venv, ~/.local) may
        create stub directories under /home, but the user's real files
        (Desktop, Documents, .bashrc, etc.) should be invisible.
        """
        script = textwrap.dedent("""\
            import os, pathlib
            home = pathlib.Path.home()
            # The home dir itself may exist as a stub from bind mounts,
            # but should NOT contain the user's real files.
            if home.is_dir():
                contents = set(os.listdir(home))
                # These are common dotfiles/dirs that would exist in a
                # real home directory but not in the bwrap sandbox.
                real_home_markers = {'.bashrc', '.profile', '.bash_history',
                                     'Desktop', 'Documents', 'Downloads'}
                leaked = contents & real_home_markers
                if leaked:
                    print(f'LEAKED:{leaked}')
                else:
                    print('HIDDEN')
            else:
                print('HIDDEN')
        """)
        r = _run_in_bwrap(script, tmp_path)
        assert r.returncode == 0, r.stderr
        assert r.stdout.strip() == "HIDDEN"

    def test_root_is_read_only(self, tmp_path):
        """--ro-bind / / prevents writing outside the working directory."""
        script = textwrap.dedent("""\
            import sys
            try:
                with open('/tmp/mograder_bwrap_test_probe', 'w') as f:
                    f.write('should not work')
                print('WRITTEN')
            except (OSError, PermissionError) as e:
                print(f'BLOCKED:{type(e).__name__}')
        """)
        r = _run_in_bwrap(script, tmp_path)
        assert r.returncode == 0, r.stderr
        # /tmp is a tmpfs inside bwrap, so writing there is actually allowed
        # (it's isolated per-sandbox).  Test writing to a truly read-only location.
        script_ro = textwrap.dedent("""\
            import sys
            try:
                with open('/usr/mograder_probe', 'w') as f:
                    f.write('should not work')
                print('WRITTEN')
            except (OSError, PermissionError) as e:
                print(f'BLOCKED:{type(e).__name__}')
        """)
        r2 = _run_in_bwrap(script_ro, tmp_path)
        assert r2.returncode == 0, r2.stderr
        assert r2.stdout.strip().startswith("BLOCKED:")

    def test_cwd_is_writable(self, tmp_path):
        """--bind cwd cwd makes the working directory writable."""
        probe = tmp_path / "probe.txt"
        script = f"""\
import pathlib
pathlib.Path({str(probe)!r}).write_text('hello from bwrap')
print('OK')
"""
        r = _run_in_bwrap(script, tmp_path)
        assert r.returncode == 0, r.stderr
        assert r.stdout.strip() == "OK"
        assert probe.read_text() == "hello from bwrap"

    def test_cannot_write_outside_cwd(self, tmp_path):
        """Files outside cwd (but on the same filesystem) are read-only."""
        # Create a sibling directory that should NOT be writable.
        sibling = tmp_path.parent / "bwrap_sibling_probe"
        sibling.mkdir(exist_ok=True)
        probe = sibling / "probe.txt"
        try:
            script = textwrap.dedent(f"""\
                try:
                    with open({str(probe)!r}, 'w') as f:
                        f.write('escaped')
                    print('WRITTEN')
                except (OSError, PermissionError) as e:
                    print(f'BLOCKED:{{type(e).__name__}}')
            """)
            r = _run_in_bwrap(script, tmp_path)
            assert r.returncode == 0, r.stderr
            assert r.stdout.strip().startswith("BLOCKED:")
        finally:
            if probe.exists():
                probe.unlink()
            sibling.rmdir()

    def test_tmp_is_isolated(self, tmp_path):
        """Files written to /tmp inside bwrap are invisible on the host."""
        host_probe = Path("/tmp/mograder_bwrap_isolation_check")
        host_probe.unlink(missing_ok=True)
        try:
            script = textwrap.dedent("""\
                from pathlib import Path
                Path('/tmp/mograder_bwrap_isolation_check').write_text('inside')
                print('OK')
            """)
            r = _run_in_bwrap(script, tmp_path)
            assert r.returncode == 0, r.stderr
            assert r.stdout.strip() == "OK"
            # The file should NOT appear on the host because /tmp is a
            # per-sandbox tmpfs.
            assert not host_probe.exists(), "/tmp write leaked to the host"
        finally:
            host_probe.unlink(missing_ok=True)


@requires_bwrap
class TestBwrapNetwork:
    """Verify --unshare-net blocks network access."""

    def test_loopback_only(self, tmp_path):
        """Network connections (except lo) should fail."""
        script = textwrap.dedent("""\
            import socket, sys
            try:
                s = socket.create_connection(('1.1.1.1', 53), timeout=3)
                s.close()
                print('CONNECTED')
            except OSError as e:
                print(f'BLOCKED:{type(e).__name__}')
        """)
        r = _run_in_bwrap(script, tmp_path, timeout=15)
        assert r.returncode == 0, r.stderr
        assert r.stdout.strip().startswith("BLOCKED:")


@requires_bwrap
class TestBwrapDev:
    """Verify --dev /dev provides necessary device nodes."""

    def test_dev_urandom_readable(self, tmp_path):
        """/dev/urandom must be readable (required by Python/uv)."""
        script = textwrap.dedent("""\
            with open('/dev/urandom', 'rb') as f:
                data = f.read(16)
            print(len(data))
        """)
        r = _run_in_bwrap(script, tmp_path)
        assert r.returncode == 0, r.stderr
        assert r.stdout.strip() == "16"

    def test_dev_null_works(self, tmp_path):
        """/dev/null should be available."""
        script = textwrap.dedent("""\
            with open('/dev/null', 'w') as f:
                f.write('gone')
            print('OK')
        """)
        r = _run_in_bwrap(script, tmp_path)
        assert r.returncode == 0, r.stderr
        assert r.stdout.strip() == "OK"


@requires_bwrap
class TestBwrapRoBindExtra:
    """Verify extra read-only bind mounts work correctly."""

    def test_extra_path_readable(self, tmp_path):
        """Paths in ro_bind_extra are accessible inside the sandbox."""
        # Create a directory with a file that should be readable.
        extra_dir = tmp_path / "extra_data"
        extra_dir.mkdir()
        (extra_dir / "secret.txt").write_text("shared-data")

        # The cwd is a different directory.
        work = tmp_path / "work"
        work.mkdir()

        script = f"""\
print(open({str(extra_dir / "secret.txt")!r}).read())
"""
        r = _run_in_bwrap(script, work, ro_bind_extra=[extra_dir])
        assert r.returncode == 0, r.stderr
        assert r.stdout.strip() == "shared-data"

    def test_extra_path_read_only(self, tmp_path):
        """Paths in ro_bind_extra are NOT writable."""
        extra_dir = tmp_path / "extra_ro"
        extra_dir.mkdir()

        work = tmp_path / "work"
        work.mkdir()

        probe = extra_dir / "probe.txt"
        script = textwrap.dedent(f"""\
            try:
                with open({str(probe)!r}, 'w') as f:
                    f.write('should fail')
                print('WRITTEN')
            except (OSError, PermissionError) as e:
                print(f'BLOCKED:{{type(e).__name__}}')
        """)
        r = _run_in_bwrap(script, work, ro_bind_extra=[extra_dir])
        assert r.returncode == 0, r.stderr
        assert r.stdout.strip().startswith("BLOCKED:")


@requires_bwrap
class TestBwrapCommandConstruction:
    """Verify _maybe_bwrap_cmd produces a working command."""

    def test_echo_through_bwrap(self, tmp_path):
        """Simplest possible test: bwrap echo."""
        cmd = _maybe_bwrap_cmd(
            ["echo", "hello-from-sandbox"],
            tmp_path,
            use_bwrap=True,
        )
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        assert r.returncode == 0, r.stderr
        assert r.stdout.strip() == "hello-from-sandbox"

    def test_exit_code_propagated(self, tmp_path):
        """Non-zero exit codes from the inner process propagate through bwrap."""
        r = _run_in_bwrap("raise SystemExit(42)", tmp_path)
        assert r.returncode == 42

    def test_env_vars_propagated(self, tmp_path):
        """Environment variables pass through to the sandboxed process."""
        import sys

        extras = _python_bind_paths()
        cmd = _maybe_bwrap_cmd(
            [sys.executable, "-c", "import os; print(os.environ['BWRAP_TEST_VAR'])"],
            tmp_path,
            use_bwrap=True,
            ro_bind_extra=extras,
        )
        env = {**os.environ, "BWRAP_TEST_VAR": "works"}
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=10, env=env)
        assert r.returncode == 0, r.stderr
        assert r.stdout.strip() == "works"
