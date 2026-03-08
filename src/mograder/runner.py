"""Notebook execution via ``marimo export html``."""

import csv
import io
import json
import os
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
    # Extract requirements from PEP 723 metadata
    try:
        proc = subprocess.run(
            ["uv", "export", "--script", str(notebook_path), "--no-hashes"],
            capture_output=True,
            text=True,
            timeout=30,
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


def run_notebook(
    notebook_path: Path,
    timeout: int = 300,
    html_dir: Path | None = None,
    sandbox_dir: Path | None = None,
) -> NotebookResult:
    """Execute a notebook and return its check results."""
    result = NotebookResult(path=notebook_path)

    with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as tmp:
        tmp_path = Path(tmp.name)

    sidecar_fd, sidecar_name = tempfile.mkstemp(
        suffix=".jsonl", prefix="mograder_sidecar_"
    )
    os.close(sidecar_fd)
    sidecar_path = Path(sidecar_name)

    try:
        if sandbox_dir is not None:
            python_exe = str(_venv_python(sandbox_dir))
        else:
            python_exe = sys.executable

        cmd = [
            python_exe,
            "-m",
            "marimo",
            "export",
            "html",
            str(notebook_path),
            "-o",
            str(tmp_path),
        ]
        if sandbox_dir is not None:
            cmd.append("--no-sandbox")

        env = {**os.environ, "MOGRADER_SIDECAR_PATH": str(sidecar_path)}
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )

        if proc.returncode != 0 and not tmp_path.exists():
            result.export_ok = False
            result.export_error = proc.stderr[:500]
            return result

        html_content = tmp_path.read_text()
        result.cell_errors = count_cell_errors(html_content)

        # Prefer sidecar results; fall back to HTML parsing
        sidecar_results = _read_sidecar(sidecar_path)
        if sidecar_results:
            result.checks = sidecar_results
        else:
            result.checks = parse_check_results(html_content)

        if "some cells failed to execute" in proc.stderr:
            result.export_error = "some cells failed to execute"

        if html_dir is not None:
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

    return result


def run_batch(
    notebooks: list[Path],
    jobs: int = 4,
    timeout: int = 300,
    html_dir: Path | None = None,
    on_progress: Callable[[int, int, Path], None] | None = None,
    sandbox_dir: Path | None = None,
) -> list[NotebookResult]:
    """Run notebooks in parallel and return results sorted by filename."""
    results: list[NotebookResult] = []
    total = len(notebooks)
    completed = 0

    with ProcessPoolExecutor(max_workers=jobs) as executor:
        futures = {
            executor.submit(run_notebook, nb, timeout, html_dir, sandbox_dir): nb
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
