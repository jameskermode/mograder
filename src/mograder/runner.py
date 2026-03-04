"""Notebook execution via ``marimo export html``."""

import csv
import io
import shutil
import subprocess
import sys
import tempfile
import zipfile
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

from mograder.models import NotebookResult
from mograder.parser import count_cell_errors, parse_check_results


def run_notebook(
    notebook_path: Path,
    timeout: int = 300,
    html_dir: Path | None = None,
) -> NotebookResult:
    """Execute a notebook and return its check results."""
    result = NotebookResult(path=notebook_path)

    with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as tmp:
        tmp_path = Path(tmp.name)

    try:
        proc = subprocess.run(
            [
                sys.executable, "-m", "marimo",
                "export", "html",
                str(notebook_path),
                "-o", str(tmp_path),
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
        )

        if proc.returncode != 0 and not tmp_path.exists():
            result.export_ok = False
            result.export_error = proc.stderr[:500]
            return result

        html_content = tmp_path.read_text()
        result.checks = parse_check_results(html_content)
        result.cell_errors = count_cell_errors(html_content)

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

    return result


def run_batch(
    notebooks: list[Path],
    jobs: int = 4,
    timeout: int = 300,
    html_dir: Path | None = None,
) -> list[NotebookResult]:
    """Run notebooks in parallel and return results sorted by filename."""
    results: list[NotebookResult] = []

    with ProcessPoolExecutor(max_workers=jobs) as executor:
        futures = {
            executor.submit(run_notebook, nb, timeout, html_dir): nb
            for nb in notebooks
        }
        for future in as_completed(futures):
            nb_path = futures[future]
            try:
                results.append(future.result())
            except Exception as e:
                results.append(NotebookResult(
                    path=nb_path, export_ok=False, export_error=str(e)
                ))

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
    return {"success": "PASS", "danger": "FAIL", "warn": "WAIT",
            "error": "ERR", "missing": "---"}.get(status, status)


def print_summary(results: list[NotebookResult], all_labels: list[str]):
    """Print a formatted summary table to stdout."""
    stem_width = max(len(r.path.stem) for r in results) if results else 20
    stem_width = max(stem_width, 10)
    header = f"{'Notebook':<{stem_width}}  "
    header += "  ".join(f"{label[:6]:>6}" for label in all_labels)
    header += "  Errors"
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
        line += f"  {result.cell_errors}"
        print(line)


def write_csv(results: list[NotebookResult], all_labels: list[str], path: Path):
    """Write results to a CSV file."""
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
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

    print(f"\nCSV written to {path}")


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
