"""Notebook execution via ``marimo export html``."""

import csv
import io
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import zipfile
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

from mograder.models import CheckResult, NotebookResult
from mograder.parser import count_cell_errors, parse_check_results


def _make_apply_rlimits(
    cpu: int = 600, nproc: int = 512, nofile: int = 256, address_space: int = 1 << 30
):
    """Return a preexec_fn that sets resource limits on the subprocess.

    A value of 0 disables that limit.  Caps:
    - CPU time (*cpu* seconds)
    - Total user processes (*nproc* — note: per-user, not per-process)
    - Open file descriptors (*nofile*)
    - Virtual memory (*address_space* bytes, Linux only)
    """

    def _apply():
        import resource

        limits: list[tuple[int, int]] = []
        if cpu:
            limits.append((resource.RLIMIT_CPU, cpu))
        if nproc:
            limits.append((resource.RLIMIT_NPROC, nproc))
        if nofile:
            limits.append((resource.RLIMIT_NOFILE, nofile))
        # RLIMIT_AS is unreliable on macOS; only apply on Linux.
        if address_space and platform.system() != "Darwin":
            limits.append((resource.RLIMIT_AS, address_space))
        for limit_id, value in limits:
            try:
                resource.setrlimit(limit_id, (value, value))
            except (ValueError, OSError):
                pass

    return _apply


def _venv_python(venv_dir: Path) -> Path:
    """Return the path to the Python executable inside a venv (cross-platform)."""
    if os.name == "nt":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def create_shared_sandbox(notebook_path: Path) -> Path | None:
    """Create or reuse a shared venv from a notebook's PEP 723 inline script metadata.

    The venv is stored at ``<notebook_parent>/.venv`` so it persists across runs.
    On repeat invocations, ``uv pip install`` is a near-instant no-op when the
    uv cache already has the packages.

    Returns the venv directory, or None if the notebook has no inline deps.
    """
    # Ensure ~/.local/bin is on PATH so we can find uv (e.g. under systemd).
    env = os.environ.copy()
    local_bin = str(Path.home() / ".local" / "bin")
    if local_bin not in env.get("PATH", "").split(os.pathsep):
        env["PATH"] = local_bin + os.pathsep + env.get("PATH", "")

    # Extract requirements from PEP 723 metadata
    try:
        proc = subprocess.run(
            ["uv", "export", "--script", str(notebook_path), "--no-hashes"],
            capture_output=True,
            text=True,
            timeout=30,
            env=env,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None

    if proc.returncode != 0 or not proc.stdout.strip():
        return None

    venv_dir = notebook_path.parent / ".venv"
    reqs_file = venv_dir / "requirements.txt"

    try:
        # Create venv only if it doesn't already exist
        if not _venv_python(venv_dir).exists():
            subprocess.run(
                ["uv", "venv", "--seed", str(venv_dir)],
                capture_output=True,
                text=True,
                timeout=60,
                check=True,
                env=env,
            )

        # Always run install — uv is fast on cache hits
        reqs_file.write_text(proc.stdout)
        venv_python = _venv_python(venv_dir)
        subprocess.run(
            [
                "uv",
                "pip",
                "install",
                "--python",
                str(venv_python),
                "-r",
                str(reqs_file),
            ],
            capture_output=True,
            text=True,
            timeout=300,
            check=True,
            env=env,
        )
    except (
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
        FileNotFoundError,
    ):
        shutil.rmtree(venv_dir, ignore_errors=True)
        return None

    return venv_dir


def _read_sidecar(path: Path) -> list[CheckResult]:
    """Read check results from a sidecar JSONL file."""
    results = []
    try:
        text = path.read_text().strip()
    except OSError:
        return results
    if not text:
        return results
    for line in text.splitlines():
        try:
            record = json.loads(line)
            results.append(
                CheckResult(
                    label=record["label"],
                    status=record["status"],
                    details=record.get("details", []),
                )
            )
        except (json.JSONDecodeError, KeyError):
            continue
    return results


def _poll_sidecar(
    proc: subprocess.Popen,
    sidecar_path: Path,
    timeout: int,
    on_check: Callable[["CheckResult"], None],
    poll_interval: float = 0.5,
) -> None:
    """Poll the sidecar JSONL file while *proc* runs, invoking *on_check*
    for each new check result line that appears."""
    import time

    deadline = time.monotonic() + timeout
    lines_read = 0

    while proc.poll() is None:
        if time.monotonic() > deadline:
            _kill_tree(proc.pid)
            proc.wait()
            raise subprocess.TimeoutExpired(proc.args, timeout)

        # Read any new lines from the sidecar
        try:
            text = sidecar_path.read_text().strip()
        except OSError:
            text = ""
        if text:
            all_lines = text.splitlines()
            for line in all_lines[lines_read:]:
                try:
                    record = json.loads(line)
                    on_check(
                        CheckResult(
                            label=record["label"],
                            status=record["status"],
                            details=record.get("details", []),
                        )
                    )
                except (json.JSONDecodeError, KeyError):
                    pass
            lines_read = len(all_lines)

        time.sleep(poll_interval)

    # Final drain — process exited, read any remaining lines
    try:
        text = sidecar_path.read_text().strip()
    except OSError:
        text = ""
    if text:
        for line in text.splitlines()[lines_read:]:
            try:
                record = json.loads(line)
                on_check(
                    CheckResult(
                        label=record["label"],
                        status=record["status"],
                        details=record.get("details", []),
                    )
                )
            except (json.JSONDecodeError, KeyError):
                pass


def _maybe_bwrap_cmd(
    cmd: list[str],
    cwd: Path,
    use_bwrap: bool,
    ro_bind_extra: list[Path] | None = None,
) -> list[str]:
    """Optionally wrap *cmd* in bubblewrap for filesystem isolation.

    *ro_bind_extra* paths are mounted read-only inside the sandbox
    (e.g. the shared sandbox venv, ``~/.local/bin`` for uv).
    """
    if not use_bwrap:
        return cmd
    if shutil.which("bwrap") is None:
        import logging

        logging.getLogger("mograder").warning(
            "use_bubblewrap=true but bwrap not found on PATH; running without sandbox"
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
    for extra in ro_bind_extra or []:
        p = str(extra.resolve())
        args.extend(["--ro-bind", p, p])
    args.extend(["--unshare-net", "--die-with-parent", "--"])
    args.extend(cmd)
    return args


def _kill_tree(pid: int) -> None:
    """Kill a process and all its descendants via /proc walk.

    Sends SIGTERM to leaves first, then SIGKILL stragglers.
    Silently ignores processes that have already exited.
    """
    import signal
    import time as _time

    def _children(parent_pid: int) -> list[int]:
        kids: list[int] = []
        try:
            for entry in os.listdir("/proc"):
                if not entry.isdigit():
                    continue
                try:
                    with open(f"/proc/{entry}/stat") as f:
                        stat = f.read()
                    rparen = stat.rfind(")")
                    fields = stat[rparen + 2 :].split()
                    ppid = int(fields[1])
                    if ppid == parent_pid:
                        kids.append(int(entry))
                except (OSError, ValueError, IndexError):
                    continue
        except OSError:
            pass
        return kids

    def _descendants(root: int) -> list[int]:
        result: list[int] = []
        stack = [root]
        while stack:
            p = stack.pop()
            result.append(p)
            stack.extend(_children(p))
        result.reverse()
        return result

    pids = _descendants(pid)
    for p in pids:
        try:
            os.kill(p, signal.SIGTERM)
        except ProcessLookupError:
            pass
    _time.sleep(0.3)
    for p in pids:
        try:
            os.kill(p, signal.SIGKILL)
        except ProcessLookupError:
            pass


def run_notebook(
    notebook_path: Path,
    timeout: int = 300,
    html_dir: Path | None = None,
    sandbox_dir: Path | None = None,
    on_check: Callable[[CheckResult], None] | None = None,
    safety_check: bool = False,
    rlimit_cpu: int = 600,
    rlimit_nproc: int = 512,
    rlimit_nofile: int = 256,
    rlimit_as: int = 1 << 30,
    isolate_cwd: bool = False,
    use_bubblewrap: bool = False,
) -> NotebookResult:
    """Execute a notebook and return its check results.

    If *on_check* is provided, the sidecar file is polled while the
    notebook executes and the callback is invoked for each new check
    result as it appears (useful for live progress in the UI).

    If *safety_check* is True, the notebook source is scanned for
    dangerous patterns (denied imports, eval/exec, etc.) before execution.
    If unsafe patterns are found, execution is skipped.
    """
    result = NotebookResult(path=notebook_path)

    if safety_check:
        from mograder.safety import check_safety

        source = notebook_path.read_text()
        safety_result = check_safety(source)
        if not safety_result.safe:
            descs = "; ".join(f.description for f in safety_result.findings)
            result.export_ok = False
            result.export_error = f"safety check failed: {descs}"
            return result

    with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as tmp:
        tmp_path = Path(tmp.name)

    sidecar_fd, sidecar_name = tempfile.mkstemp(
        suffix=".jsonl", prefix="mograder_sidecar_"
    )
    os.close(sidecar_fd)
    sidecar_path = Path(sidecar_name)

    isolate_dir: Path | None = None
    try:
        # Resolve to absolute paths so they remain valid when cwd changes.
        notebook_abs = notebook_path.resolve()
        notebook_cwd = notebook_abs.parent

        # Temp dir isolation: copy notebook into a fresh directory so student
        # code cannot write files next to other submissions.
        if isolate_cwd:
            isolate_dir = Path(tempfile.mkdtemp(prefix="mograder_iso_"))
            shutil.copy2(notebook_abs, isolate_dir / notebook_abs.name)
            notebook_abs = (isolate_dir / notebook_abs.name).resolve()
            notebook_cwd = isolate_dir

        if sandbox_dir is not None:
            python_exe = str(_venv_python(sandbox_dir.resolve()))
        else:
            python_exe = sys.executable

        cmd = [
            python_exe,
            "-m",
            "marimo",
            "export",
            "html",
            str(notebook_abs),
            "-o",
            str(tmp_path),
        ]
        if sandbox_dir is not None:
            cmd.append("--no-sandbox")
        else:
            # Use --sandbox so marimo installs inline deps without prompting.
            # Without this, marimo may prompt interactively via click.confirm()
            # when stdin is a tty, causing the process to hang.
            cmd.append("--sandbox")

        env = {**os.environ, "MOGRADER_SIDECAR_PATH": str(sidecar_path)}
        # Ensure ~/.local/bin is on PATH so marimo can find uv for sandboxed
        # notebooks (e.g. when running under systemd with a minimal PATH).
        local_bin = str(Path.home() / ".local" / "bin")
        if local_bin not in env.get("PATH", "").split(os.pathsep):
            env["PATH"] = local_bin + os.pathsep + env.get("PATH", "")

        # When bubblewrap is active, skip RLIMIT_NPROC — it counts all user
        # processes and can block bwrap's clone() call.  Bwrap provides its own
        # process isolation via PID namespaces.
        _effective_nproc = 0 if use_bubblewrap else rlimit_nproc
        _preexec = (
            _make_apply_rlimits(rlimit_cpu, _effective_nproc, rlimit_nofile, rlimit_as)
            if os.name != "nt"
            else None
        )

        # Build list of extra paths the bwrap sandbox needs read-only
        # access to: the sandbox venv, ~/.local (for uv binary + uv-managed
        # Python installations which venv symlinks point to).
        _bwrap_ro: list[Path] = []
        if sandbox_dir is not None:
            _bwrap_ro.append(sandbox_dir.resolve())
        _dot_local = Path.home() / ".local"
        if _dot_local.is_dir():
            _bwrap_ro.append(_dot_local)
        cmd = _maybe_bwrap_cmd(cmd, notebook_cwd, use_bubblewrap, _bwrap_ro)

        if on_check is not None:
            # Stream mode: poll sidecar for live check results
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=env,
                stdin=subprocess.DEVNULL,
                preexec_fn=_preexec,
                cwd=notebook_cwd,
            )
            _poll_sidecar(proc, sidecar_path, timeout, on_check)
            stderr = proc.stderr.read() if proc.stderr else ""
        else:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=env,
                stdin=subprocess.DEVNULL,
                preexec_fn=_preexec,
                cwd=notebook_cwd,
            )
            stderr = proc.stderr

        if proc.returncode != 0 and (
            not tmp_path.exists() or tmp_path.stat().st_size == 0
        ):
            result.export_ok = False
            result.export_error = stderr[:500]
            return result

        html_content = tmp_path.read_text()
        result.cell_errors = count_cell_errors(html_content)

        # Prefer sidecar results; fall back to HTML parsing
        sidecar_results = _read_sidecar(sidecar_path)
        if sidecar_results:
            result.checks = sidecar_results
        else:
            result.checks = parse_check_results(html_content)

        if "some cells failed to execute" in stderr:
            result.export_error = "some cells failed to execute"

        if html_dir is not None and html_content:
            saved = html_dir / f"{notebook_path.stem}.html"
            shutil.copy2(tmp_path, saved)
            result.html_path = saved

    except subprocess.TimeoutExpired:
        result.export_ok = False
        result.export_error = f"timeout after {timeout}s"
    except Exception as e:
        result.export_ok = False
        result.export_error = str(e)
    finally:
        tmp_path.unlink(missing_ok=True)
        sidecar_path.unlink(missing_ok=True)
        if isolate_dir is not None:
            shutil.rmtree(isolate_dir, ignore_errors=True)

    return result


def run_batch(
    notebooks: list[Path],
    jobs: int = 4,
    timeout: int = 300,
    html_dir: Path | None = None,
    on_progress: Callable[[int, int, Path], None] | None = None,
    sandbox_dir: Path | None = None,
    safety_check: bool = False,
    rlimit_cpu: int = 600,
    rlimit_nproc: int = 512,
    rlimit_nofile: int = 256,
    rlimit_as: int = 1 << 30,
    isolate_cwd: bool = False,
    use_bubblewrap: bool = False,
) -> list[NotebookResult]:
    """Run notebooks in parallel and return results sorted by filename."""
    results: list[NotebookResult] = []
    total = len(notebooks)
    completed = 0

    with ProcessPoolExecutor(max_workers=jobs) as executor:
        futures = {
            executor.submit(
                run_notebook,
                nb,
                timeout,
                html_dir,
                sandbox_dir,
                None,
                safety_check,
                rlimit_cpu,
                rlimit_nproc,
                rlimit_nofile,
                rlimit_as,
                isolate_cwd,
                use_bubblewrap,
            ): nb
            for nb in notebooks
        }
        for future in as_completed(futures):
            nb_path = futures[future]
            try:
                results.append(future.result())
            except Exception as e:
                results.append(
                    NotebookResult(path=nb_path, export_ok=False, export_error=str(e))
                )
            completed += 1
            if on_progress is not None:
                on_progress(completed, total, nb_path)

    results.sort(key=lambda r: r.path.stem)
    return results


def discover_labels(results: list[NotebookResult]) -> list[str]:
    """Extract ordered unique labels from results."""
    label_set: dict[str, str] = {}
    for r in results:
        for c in r.checks:
            key = c.label.split(":")[0].strip()
            if key not in label_set:
                label_set[key] = c.label
    return list(label_set.values())


def format_status(status: str) -> str:
    """Format status for terminal output with ANSI colors."""
    symbols = {
        "success": "\033[32mPASS\033[0m",
        "danger": "\033[31mFAIL\033[0m",
        "warn": "\033[33mWAIT\033[0m",
        "error": "\033[31mERR \033[0m",
        "missing": "\033[90m --- \033[0m",
    }
    return symbols.get(status, status)


def format_status_plain(status: str) -> str:
    """Format status without ANSI codes."""
    return {
        "success": "PASS",
        "danger": "FAIL",
        "warn": "WAIT",
        "error": "ERR",
        "missing": "---",
    }.get(status, status)


def print_summary(
    results: list[NotebookResult],
    all_labels: list[str],
    marks: dict[str, int | float] | None = None,
):
    """Print a formatted summary table to stdout."""
    has_tampering = any(r.tampered for r in results)

    stem_width = max(len(r.path.stem) for r in results) if results else 20
    stem_width = max(stem_width, 10)
    header = f"{'Notebook':<{stem_width}}  "
    header += "  ".join(f"{label[:6]:>6}" for label in all_labels)
    if marks is not None:
        header += "  Marks"
    header += "  Errors"
    if has_tampering:
        header += "  Tampered"
    print(header)
    print("-" * len(header))

    for result in results:
        if not result.export_ok:
            line = f"{result.path.stem:<{stem_width}}  "
            line += f"\033[31mEXPORT FAILED: {result.export_error}\033[0m"
            print(line)
            continue

        check_map = {c.label.split(":")[0].strip(): c.status for c in result.checks}
        line = f"{result.path.stem:<{stem_width}}  "
        for label in all_labels:
            q_key = label.split(":")[0].strip()
            status = check_map.get(q_key, "missing")
            line += f"{format_status(status):>17}  "
        if marks is not None:
            auto_mark = sum(
                marks[k] for k in marks if k in check_map and check_map[k] == "success"
            )
            total = sum(marks.values())
            line += f"  {auto_mark}/{total}"
        line += f"  {result.cell_errors}"
        if has_tampering:
            line += f"  {', '.join(result.tampered)}" if result.tampered else ""
        print(line)


def write_csv(
    results: list[NotebookResult],
    all_labels: list[str],
    path: Path,
    marks: dict[str, int | float] | None = None,
):
    """Write results to a CSV file."""
    has_tampering = any(r.tampered for r in results)

    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        q_headers = [label.split(":")[0].strip() for label in all_labels]
        header = ["notebook"] + q_headers + ["cell_errors", "export_error"]
        if marks is not None:
            header.append("auto_mark")
        if has_tampering:
            header.append("tampered")
        writer.writerow(header)

        for result in results:
            if not result.export_ok:
                row = [result.path.stem] + ["EXPORT_FAILED"] * len(all_labels)
                row += [0, result.export_error]
                if marks is not None:
                    row.append("")
                if has_tampering:
                    row.append("; ".join(result.tampered))
            else:
                check_map = {
                    c.label.split(":")[0].strip(): format_status_plain(c.status)
                    for c in result.checks
                }
                row = [result.path.stem]
                row += [check_map.get(q, "---") for q in q_headers]
                row += [result.cell_errors, result.export_error]
                if marks is not None:
                    auto_mark = sum(
                        marks[k]
                        for k in marks
                        if k in check_map and check_map[k] == "PASS"
                    )
                    row.append(auto_mark)
                if has_tampering:
                    row.append("; ".join(result.tampered))
            writer.writerow(row)

    print(f"\nCSV written to {path}")


def serialize_results(
    results: list[NotebookResult],
    all_labels: list[str],
    marks: dict[str, int | float] | None = None,
) -> list[dict]:
    """Convert results to a list of dicts for JSON serialization."""
    q_headers = [label.split(":")[0].strip() for label in all_labels]
    rows = []
    for result in results:
        if not result.export_ok:
            row = {
                "notebook": result.path.stem,
                "checks": {q: "EXPORT_FAILED" for q in q_headers},
                "cell_errors": 0,
                "export_error": result.export_error,
                "tampered": result.tampered,
            }
            if marks is not None:
                row["auto_mark"] = None
                row["total_mark"] = sum(marks.values())
        else:
            check_map = {
                c.label.split(":")[0].strip(): format_status_plain(c.status)
                for c in result.checks
            }
            row = {
                "notebook": result.path.stem,
                "checks": {q: check_map.get(q, "---") for q in q_headers},
                "cell_errors": result.cell_errors,
                "export_error": result.export_error,
                "tampered": result.tampered,
            }
            if marks is not None:
                auto_mark = sum(
                    marks[k] for k in marks if k in check_map and check_map[k] == "PASS"
                )
                row["auto_mark"] = auto_mark
                row["total_mark"] = sum(marks.values())
        rows.append(row)
    return rows


def build_zip(
    results: list[NotebookResult],
    all_labels: list[str],
    zip_path: Path,
):
    """Bundle .py sources, .html exports, and results.csv into a zip."""
    csv_buf = io.StringIO()
    writer = csv.writer(csv_buf)
    q_headers = [label.split(":")[0].strip() for label in all_labels]
    writer.writerow(["notebook"] + q_headers + ["cell_errors", "export_error"])
    for result in results:
        if not result.export_ok:
            row = [result.path.stem] + ["EXPORT_FAILED"] * len(all_labels)
            row += [0, result.export_error]
        else:
            check_map = {
                c.label.split(":")[0].strip(): format_status_plain(c.status)
                for c in result.checks
            }
            row = [result.path.stem]
            row += [check_map.get(q, "---") for q in q_headers]
            row += [result.cell_errors, result.export_error]
        writer.writerow(row)

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("results.csv", csv_buf.getvalue())
        for result in results:
            zf.write(result.path, f"sources/{result.path.name}")
            if result.html_path and result.html_path.exists():
                zf.write(result.html_path, f"html/{result.html_path.name}")

    print(f"\nGrading bundle written to {zip_path}")
