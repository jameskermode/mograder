"""Hub session spawner — manage per-student marimo edit sessions."""

from __future__ import annotations

import asyncio
import logging
import os
import re
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

from mograder.core.edit_sessions import _kill_tree
from mograder.hub.memory import MemoryLedger, children_map, tree_mb
from mograder.hub.models import MarimoSession

log = logging.getLogger("mograder.hub")


def _uv_env() -> dict[str, str]:
    """Return an env dict with ``~/.local/bin`` on PATH so ``uv`` is found."""
    env = os.environ.copy()
    local_bin = str(Path.home() / ".local" / "bin")
    if local_bin not in env.get("PATH", "").split(os.pathsep):
        env["PATH"] = local_bin + os.pathsep + env.get("PATH", "")
    return env


class HubBusy(RuntimeError):
    """Not enough free memory to start another session (admission control)."""


BUSY_MESSAGE = (
    "The hub is busy right now: there is not enough free memory for another "
    "notebook session. Please try again in a few minutes, or run the notebook "
    "on your own computer."
)

# Thread-pool sizes of the numerical libraries a kernel may load. Each defaults
# to one thread per core, so many kernels on a shared machine oversubscribe the
# CPU (e.g. 14 kernels x 4 threads on 4 vCPU) and lose throughput to switching.
THREAD_ENV_VARS = (
    "OMP_NUM_THREADS",  # OpenMP: PyTorch intra-op, OpenBLAS/MKL builds using OpenMP
    "MKL_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "VECLIB_MAXIMUM_THREADS",
    "NUMEXPR_NUM_THREADS",
)


def thread_env(threads: int) -> dict[str, str]:
    """Environment capping a kernel's numerical thread pools at ``threads``."""
    if threads <= 0:
        return {}
    env = {var: str(threads) for var in THREAD_ENV_VARS}
    # JAX (XLA CPU) ignores the variables above; its Eigen pool can only be
    # switched to single-threaded
    if threads == 1:
        flags = os.environ.get("XLA_FLAGS", "")
        extra = "--xla_cpu_multi_thread_eigen=false intra_op_parallelism_threads=1"
        env["XLA_FLAGS"] = f"{flags} {extra}".strip()
    return env


def mem_available_mb() -> int | None:
    """MemAvailable from /proc/meminfo in MB (None where unavailable, e.g. macOS)."""
    try:
        with open("/proc/meminfo", encoding="utf-8") as f:
            for line in f:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) // 1024
    except OSError:
        return None
    return None


def parse_pep723_deps(source: str) -> list[str]:
    """Extract dependencies from PEP 723 inline script metadata."""
    m = re.search(
        r"^# /// script\s*\n((?:#[^\n]*\n)*?)# ///",
        source,
        re.MULTILINE,
    )
    if not m:
        return []
    block = m.group(1)
    # Strip leading "# " from each line and parse as TOML
    lines = [line.removeprefix("# ").removeprefix("#") for line in block.splitlines()]
    text = "\n".join(lines)
    try:
        import tomllib

        data = tomllib.loads(text)
    except Exception:
        return []
    return list(data.get("dependencies", []))


def warm_notebook_cache(nb_path: Path, dry_run: bool = False) -> list[str]:
    """Parse PEP 723 deps from *nb_path* and warm the uv cache.

    Also creates a shared sandbox venv (via ``create_shared_sandbox``)
    so that edit sessions can start without ``uv run`` overhead.

    Returns the dependency list (empty if none found).
    """
    deps = parse_pep723_deps(nb_path.read_text(encoding="utf-8"))
    if not deps or dry_run:
        return deps
    dep_args = []
    for d in deps:
        dep_args.extend(["--with", d])
    subprocess.run(
        ["uv", "run", *dep_args, "python", "-c", "pass"],
        check=True,
        capture_output=True,
        timeout=120,
        env=_uv_env(),
    )

    # Create shared sandbox venv for fast edit-session startup
    from mograder.grading.runner import create_shared_sandbox

    sandbox = create_shared_sandbox(nb_path)
    if sandbox:
        log.info("Created shared sandbox for %s: %s", nb_path.stem, sandbox)

    return deps


class SessionManager:
    """Manage headless marimo edit sessions keyed by (username, assignment)."""

    def __init__(
        self,
        notebooks_dir: Path,
        session_ttl: int = 3600,
        base_port: int = 18000,
        use_bubblewrap: bool = False,
        uv_cache_dir: str = "",
        spawn_timeout: int = 120,
        release_dir: Path | None = None,
        session_threads: int = 0,
        min_free_mb: int = 0,
        session_mb: int = 0,
        course_dir: Path | None = None,
    ):
        self.session_threads = session_threads
        self.min_free_mb = min_free_mb
        # per-item memory estimates (measured peaks, calibration, session_mb)
        self.memory = MemoryLedger(course_dir, session_mb)
        # items of spawns admitted but not yet registered as sessions
        self._starting: list[str] = []
        self.notebooks_dir = Path(notebooks_dir).resolve()
        self.session_ttl = session_ttl
        self.base_port = base_port
        self.use_bubblewrap = use_bubblewrap
        self.uv_cache_dir = uv_cache_dir
        self.spawn_timeout = spawn_timeout
        self.release_dir = Path(release_dir).resolve() if release_dir else None
        self.sessions: dict[tuple[str, str], MarimoSession] = {}
        # Lecture "run" sessions are kept apart from edit sessions: a student
        # can have both for the same lecture (read-only view and own copy),
        # served under different base URLs (/run/user/... vs /edit/user/...)
        self.run_sessions: dict[tuple[str, str], MarimoSession] = {}
        self._locks: dict[tuple[str, str], asyncio.Lock] = {}
        # Ports handed out to spawns still starting up (not yet in a session
        # map): without this, concurrent spawns for different students can
        # get the same port, and the loser's readiness check then connects to
        # the winner's marimo server
        self._reserved_ports: set[int] = set()
        self._sandbox_dirs: dict[str, Path | None] = {}
        self._culler_task: asyncio.Task | None = None

    def _get_lock(self, key: tuple) -> asyncio.Lock:
        if key not in self._locks:
            self._locks[key] = asyncio.Lock()
        return self._locks[key]

    def _notebook_path(self, username: str, assignment: str) -> Path:
        return self.notebooks_dir / username / assignment / f"{assignment}.py"

    def _check_capacity(self, item: str) -> None:
        """Refuse a new session for ``item`` unless memory allows it.

        A session starts small and grows as its notebook runs, so free memory
        alone admits a burst of arrivals that later exhausts it. Admission
        therefore projects: available memory, minus the growth still to come
        in existing sessions (estimate minus latest sample) and in spawns
        under way, minus the new session's estimate, must stay at or above
        ``min_free_mb``. With no estimates this is a plain free-memory check.

        Only new sessions are refused: students already working keep their
        sessions, which a new one could otherwise push into the OOM killer.
        """
        if self.min_free_mb <= 0:
            return
        avail = mem_available_mb()
        if avail is None:
            return
        est = self.memory.estimate
        live = [*self.sessions.values(), *self.run_sessions.values()]
        growth = sum(max(0, est(s.assignment) - s.mem_mb) for s in live)
        growth += sum(est(i) for i in self._starting)
        need = est(item)
        if avail - growth - need < self.min_free_mb:
            log.warning(
                "refusing new session for %s: %d MB available - %d MB growth "
                "to come - %d MB for it < %d MB",
                item,
                avail,
                growth,
                need,
                self.min_free_mb,
            )
            raise HubBusy(BUSY_MESSAGE)

    def _allocate_port(self) -> int:
        """Find a free port starting from base_port and reserve it.

        The caller releases the reservation (``_reserved_ports.discard``)
        once the session is registered or the spawn has failed.
        """
        used = (
            {s.port for s in self.sessions.values()}
            | {s.port for s in self.run_sessions.values()}
            | self._reserved_ports
        )
        port = self.base_port
        while port < self.base_port + 1000:
            if port in used:
                port += 1
                continue
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                try:
                    s.bind(("127.0.0.1", port))
                    self._reserved_ports.add(port)
                    return port
                except OSError:
                    port += 1
        raise RuntimeError("No free ports available")

    def _get_sandbox_dir(self, assignment: str) -> Path | None:
        """Look up a pre-built shared sandbox venv for an assignment.

        The venv is created at publish/warm-cache time (not on first spawn)
        by ``warm_notebook_cache()`` calling ``create_shared_sandbox()``.
        This method only checks if it exists — it never creates one.
        """
        if assignment in self._sandbox_dirs:
            return self._sandbox_dirs[assignment]

        if not self.release_dir:
            self._sandbox_dirs[assignment] = None
            return None

        from mograder.grading.runner import _venv_python

        venv_dir = self.release_dir / assignment / ".venv"
        if _venv_python(venv_dir).exists():
            log.info("Using shared sandbox for %s: %s", assignment, venv_dir)
            self._sandbox_dirs[assignment] = venv_dir
            return venv_dir

        self._sandbox_dirs[assignment] = None
        return None

    @staticmethod
    def _ensure_autorun_config(config_home: Path) -> None:
        """Make marimo run the notebook when an edit session opens.

        marimo's default (``runtime.auto_instantiate = false``) opens edit
        sessions without running anything; workshops are written to run up
        to the first exercise not yet attempted, so the hub turns autorun on
        in the student's marimo user config. A value the student has set
        (e.g. turned off in marimo's settings) is left alone. marimo ignores
        this setting in a notebook's own header, so it is set here.
        """
        import re
        import tomllib

        cfg = config_home / "marimo" / "marimo.toml"
        text = cfg.read_text(encoding="utf-8") if cfg.is_file() else ""
        try:
            data = tomllib.loads(text)
        except tomllib.TOMLDecodeError:
            return  # leave a file we cannot parse alone
        runtime = data.get("runtime", {})
        if "auto_instantiate" in runtime:
            return
        if "runtime" in data:
            text = re.sub(
                r"^\[runtime\][ \t]*$",
                "[runtime]\nauto_instantiate = true",
                text,
                count=1,
                flags=re.M,
            )
        else:
            text = text.rstrip() + ("\n\n" if text.strip() else "")
            text += "[runtime]\nauto_instantiate = true\n"
        cfg.parent.mkdir(parents=True, exist_ok=True)
        cfg.write_text(text, encoding="utf-8")

    def _build_env(self, username: str, notebook_path: Path) -> dict[str, str]:
        """Build environment for student marimo process."""
        student_dir = notebook_path.parent
        env = {}
        env["XDG_CONFIG_HOME"] = str(student_dir / ".config")
        self._ensure_autorun_config(student_dir / ".config")
        env["XDG_DATA_HOME"] = str(student_dir / ".local" / "share")
        env["MOGRADER_DASHBOARD"] = "1"
        env.update(thread_env(self.session_threads))
        # Ensure uv is on PATH for marimo --sandbox mode
        uv_bin = Path.home() / ".local" / "bin"
        if uv_bin.is_dir():
            env["PATH"] = f"{uv_bin}:{os.environ.get('PATH', '/usr/bin:/bin')}"
        return env

    def _build_command(
        self,
        username: str,
        assignment: str,
        notebook_path: Path,
        port: int,
    ) -> list[str]:
        """Build the marimo edit command, optionally wrapped in bwrap."""
        from mograder.grading.runner import _venv_python

        base_url = f"/edit/user/{username}/{assignment}"
        sandbox_dir = self._get_sandbox_dir(assignment)

        if sandbox_dir is not None:
            python_exe = str(_venv_python(sandbox_dir))
        else:
            python_exe = sys.executable

        cmd = [
            python_exe,
            "-m",
            "marimo",
            "edit",
            "--no-sandbox" if sandbox_dir else "--sandbox",
            "--headless",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--base-url",
            base_url,
            "--no-token",
            str(notebook_path),
        ]

        if self.use_bubblewrap:
            return self._wrap_with_bwrap(
                cmd, notebook_path.parent, sandbox_dir=sandbox_dir
            )

        return cmd

    def _wrap_with_bwrap(
        self, cmd: list[str], cwd: Path, sandbox_dir: Path | None = None
    ) -> list[str]:
        """Wrap command in bubblewrap for isolation."""
        if shutil.which("bwrap") is None:
            log.warning(
                "use_bubblewrap=True but bwrap not found on PATH; "
                "running without sandbox"
            )
            return cmd

        args = [
            "bwrap",
            "--ro-bind",
            "/",
            "/",
            "--dev",
            "/dev",
            "--tmpfs",
            "/tmp",
            "--tmpfs",
            "/home",
            "--bind",
            str(cwd),
            str(cwd),
        ]
        if self.uv_cache_dir:
            cache = str(Path(self.uv_cache_dir).resolve())
            args.extend(["--ro-bind", cache, cache])
        if sandbox_dir:
            # Mount the shared venv read-only so students can't tamper
            venv = str(sandbox_dir.resolve())
            args.extend(["--ro-bind", venv, venv])
            # Also mount ~/.local for uv-managed Python symlinks
            dot_local = str(Path.home() / ".local")
            if Path(dot_local).is_dir():
                args.extend(["--ro-bind", dot_local, dot_local])
        args.extend(["--unshare-net", "--die-with-parent", "--"])
        args.extend(cmd)
        return args

    def _build_run_command(
        self,
        username: str,
        lecture: str,
        notebook_path: Path,
        port: int,
        include_code: bool = True,
    ) -> list[str]:
        """Build a ``marimo run`` command for a lecture (``--include-code``)
        or a demo (code hidden)."""
        sandbox_dir = self._get_sandbox_dir(lecture)

        if sandbox_dir is not None:
            from mograder.grading.runner import _venv_python

            python_exe = str(_venv_python(sandbox_dir))
        else:
            python_exe = sys.executable

        base_url = f"/run/user/{username}/{lecture}"
        cmd = [
            python_exe,
            "-m",
            "marimo",
            "run",
            "--no-sandbox" if sandbox_dir else "--sandbox",
            *(["--include-code"] if include_code else []),
            "--headless",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--base-url",
            base_url,
            "--no-token",
            str(notebook_path),
        ]
        return cmd

    async def _spawn_process(
        self, username: str, assignment: str, notebook_path: Path, port: int
    ) -> tuple:
        """Spawn the marimo process. Returns (process, port).

        This is the method mocked in tests.
        """
        cmd = self._build_command(username, assignment, notebook_path, port)
        extra_env = self._build_env(username, notebook_path)
        env = {**os.environ, **extra_env}

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env=env,
            cwd=str(notebook_path.parent),
        )
        # Wait for port to become ready
        polls = self.spawn_timeout * 2  # poll every 0.5s
        for _ in range(polls):
            await asyncio.sleep(0.5)
            # an exited process is not the one listening on the port
            if proc.returncode is not None:
                raise RuntimeError(f"marimo process exited with code {proc.returncode}")
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                try:
                    s.connect(("127.0.0.1", port))
                    return (proc, port)
                except OSError:
                    if proc.returncode is not None:
                        raise RuntimeError(
                            f"marimo process exited with code {proc.returncode}"
                        )

        proc.kill()
        raise TimeoutError(
            f"marimo did not start on port {port} within {self.spawn_timeout}s"
        )

    async def get_or_spawn(self, username: str, assignment: str) -> MarimoSession:
        """Get existing session or spawn a new one."""
        key = (username, assignment)

        # Fast path: existing live session
        existing = self.sessions.get(key)
        if existing and existing.process and existing.process.returncode is None:
            existing.last_seen = time.time()
            return existing

        # Serialize spawns for the same key
        lock = self._get_lock(key)
        async with lock:
            # Re-check after acquiring lock
            existing = self.sessions.get(key)
            if existing and existing.process and existing.process.returncode is None:
                existing.last_seen = time.time()
                return existing

            # Verify notebook exists
            nb = self._notebook_path(username, assignment)
            if not nb.is_file():
                raise FileNotFoundError(f"Notebook not found: {nb}")

            self._check_capacity(assignment)
            self._starting.append(assignment)
            port = self._allocate_port()
            try:
                proc, actual_port = await self._spawn_process(
                    username, assignment, nb, port
                )

                session = MarimoSession(
                    username=username,
                    assignment=assignment,
                    port=actual_port,
                    process=proc,
                    notebook_path=str(nb),
                    last_seen=time.time(),
                )
                self.sessions[key] = session
                return session
            finally:
                self._reserved_ports.discard(port)
                self._starting.remove(assignment)

    async def get_or_spawn_run(
        self, username: str, lecture: str, include_code: bool = True
    ) -> MarimoSession:
        """Get or spawn a per-user ``marimo run`` session for a lecture.

        Like ``get_or_spawn`` but reads the notebook from ``release_dir``
        (not the student's workspace) and uses ``marimo run --include-code``
        instead of ``marimo edit``.  Each user gets their own process so
        runtime state (widgets, cell execution) is isolated.
        """
        key = (username, lecture)

        existing = self.run_sessions.get(key)
        if existing and existing.process and existing.process.returncode is None:
            existing.last_seen = time.time()
            return existing

        lock = self._get_lock(("run", username, lecture))
        async with lock:
            existing = self.run_sessions.get(key)
            if existing and existing.process and existing.process.returncode is None:
                existing.last_seen = time.time()
                return existing

            if not self.release_dir:
                raise FileNotFoundError("No release directory configured")
            nb = self.release_dir / lecture / f"{lecture}.py"
            if not nb.is_file():
                raise FileNotFoundError(f"Lecture notebook not found: {nb}")

            self._check_capacity(lecture)
            self._starting.append(lecture)
            port = self._allocate_port()
            try:
                cmd = self._build_run_command(
                    username, lecture, nb, port, include_code=include_code
                )
                env = {**os.environ, **thread_env(self.session_threads)}
                uv_bin = Path.home() / ".local" / "bin"
                if uv_bin.is_dir():
                    env["PATH"] = f"{uv_bin}:{os.environ.get('PATH', '/usr/bin:/bin')}"

                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT,
                    env=env,
                    cwd=str(nb.parent),
                )
                polls = self.spawn_timeout * 2
                for _ in range(polls):
                    await asyncio.sleep(0.5)
                    if proc.returncode is not None:
                        raise RuntimeError(
                            f"marimo run exited with code {proc.returncode}"
                        )
                    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                        try:
                            s.connect(("127.0.0.1", port))
                            break
                        except OSError:
                            if proc.returncode is not None:
                                raise RuntimeError(
                                    f"marimo run exited with code {proc.returncode}"
                                )
                else:
                    proc.kill()
                    raise TimeoutError(
                        f"marimo run did not start on port {port} within {self.spawn_timeout}s"
                    )

                session = MarimoSession(
                    username=username,
                    assignment=lecture,
                    port=port,
                    process=proc,
                    notebook_path=str(nb),
                    last_seen=time.time(),
                )
                self.run_sessions[key] = session
                return session
            finally:
                self._reserved_ports.discard(port)
                self._starting.remove(lecture)

    async def terminate(
        self, username: str, assignment: str, mode: str = "edit"
    ) -> bool:
        """Kill a session (``mode`` "edit" or "run") and remove it from its map."""
        key = (username, assignment)
        sessions = self.run_sessions if mode == "run" else self.sessions
        session = sessions.pop(key, None)
        if session is None:
            return False
        if session.process and session.process.pid:
            try:
                _kill_tree(session.process.pid)
            except Exception:
                pass
        return True

    async def cull_idle(self) -> None:
        """Terminate sessions that have been idle past TTL."""
        now = time.time()
        for mode, sessions in (("edit", self.sessions), ("run", self.run_sessions)):
            to_cull = [
                (u, a)
                for (u, a), s in list(sessions.items())
                if (now - s.last_seen) > self.session_ttl
                or (s.process and s.process.returncode is not None)
            ]
            for u, a in to_cull:
                await self.terminate(u, a, mode)

    async def start_culler(self, interval: float = 60) -> None:
        """Background task to cull idle sessions periodically."""
        while True:
            await asyncio.sleep(interval)
            try:
                await self.cull_idle()
            except Exception:
                log.exception("Error during session culling")

    def sample_memory(self) -> None:
        """Measure every session's process tree; record peaks per item."""
        live = [*self.sessions.values(), *self.run_sessions.values()]
        if not live:
            return
        children = children_map()
        for s in live:
            pid = getattr(s.process, "pid", None)
            if pid is None:
                continue
            s.mem_mb = tree_mb(pid, children)
            self.memory.record(s.assignment, s.mem_mb)
        self.memory.save()

    async def start_sampler(self, interval: float = 10) -> None:
        """Background task sampling session memory (for admission control)."""
        while True:
            await asyncio.sleep(interval)
            try:
                await asyncio.to_thread(self.sample_memory)
            except Exception:
                log.exception("Error sampling session memory")

    async def shutdown_all(self) -> None:
        """Terminate all sessions."""
        for u, a in list(self.sessions.keys()):
            await self.terminate(u, a)
        for u, a in list(self.run_sessions.keys()):
            await self.terminate(u, a, "run")
