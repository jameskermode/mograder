"""HTML feedback export and grade aggregation."""

import csv
import hashlib
import html
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

from mograder.cells import (
    SCORES_MARKER,
    parse_auto_marks,
    parse_marker_feedback,
    parse_marks_metadata,
)


def _build_callout_html(content_html: str, kind: str) -> str:
    """Build a ``<marimo-callout-output>`` element string.

    Applies the layered escaping marimo expects:
    1. JSON-encode the inner HTML string
    2. HTML-entity-encode the JSON for use as an attribute value
    3. Wrap in the custom element
    """
    json_str = json.dumps(content_html)
    # Entity-encode for attribute value: &, <, >, ", backslash
    encoded = (
        json_str.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("\\", "&#92;")
    )
    kind_encoded = (
        json.dumps(kind)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("\\", "&#92;")
    )
    return f"<marimo-callout-output data-html='{encoded}' data-kind='{kind_encoded}'></marimo-callout-output>"


def _fmt_mark(v: int | float) -> str:
    """Format a mark value: show as int if whole, else as float."""
    return str(int(v)) if v == int(v) else str(v)


def _build_feedback_content(
    mark: int | float,
    feedback_text: str,
    auto_mark: int | float | None = None,
    total_available: int | float | None = None,
    penalty_pct: float | None = None,
    penalised_mark: int | float | None = None,
    penalty_reason: str | None = None,
) -> str:
    """Build the inner HTML content for a feedback callout.

    Returns HTML suitable for passing to ``_build_callout_html``.
    """
    parts = []
    _total_str = _fmt_mark(total_available) if total_available is not None else "100"

    if auto_mark is not None:
        manual = mark - auto_mark
        parts.append(
            f"<strong>Mark: {_fmt_mark(mark)}/{_total_str}</strong>"
            f" (auto: {_fmt_mark(auto_mark)}, manual: {_fmt_mark(manual)})"
        )
    else:
        parts.append(f"<strong>Mark: {_fmt_mark(mark)}/100</strong>")

    # Late penalty line
    if penalty_pct is not None and penalty_pct > 0 and penalised_mark is not None:
        reason = html.escape(penalty_reason or "")
        parts.append(
            f'<span style="color: #d32f2f"><strong>Late penalty: '
            f"-{_fmt_mark(penalty_pct)}%</strong>"
            f" ({reason})"
            f" &rArr; <strong>{_fmt_mark(penalised_mark)}/{_total_str}</strong></span>"
        )

    if feedback_text:
        paragraphs = feedback_text.split("\n\n")
        for para in paragraphs:
            escaped = html.escape(para.strip())
            if escaped:
                parts.append(f'<span class="paragraph">{escaped}</span>')

    inner = "\n".join(parts)
    return f'<span class="markdown prose dark:prose-invert contents">{inner}</span>'


def inject_feedback_html(
    html_source: str,
    dest: Path,
    mark: int | float,
    feedback_text: str,
    auto_mark: int | float | None = None,
    total_available: int | float | None = None,
    penalty_pct: float | None = None,
    penalised_mark: int | float | None = None,
    penalty_reason: str | None = None,
) -> None:
    """Inject a feedback callout cell into an existing marimo HTML export.

    Modifies the embedded ``__MARIMO_MOUNT_CONFIG__`` JSON to append a
    feedback cell to both ``notebook.cells`` and ``session.cells``.
    """
    prefix = "window.__MARIMO_MOUNT_CONFIG__ = "
    idx = html_source.index(prefix)
    json_start = idx + len(prefix)

    # Remove trailing commas before } or ] for valid JSON
    # Find the end of the JS object (ends with `};`)
    # Use brace counting to find the matching }
    depth = 0
    json_end = None
    for i in range(json_start, len(html_source)):
        ch = html_source[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                json_end = i + 1
                break
        elif ch == '"':
            # Skip string contents
            i2 = i + 1
            while i2 < len(html_source):
                c2 = html_source[i2]
                if c2 == "\\":
                    i2 += 2
                    continue
                if c2 == '"':
                    break
                i2 += 1

    if json_end is None:
        raise ValueError("Could not find end of __MARIMO_MOUNT_CONFIG__")

    raw_json = html_source[json_start:json_end]
    # Strip trailing commas (valid JS but not JSON)
    clean_json = re.sub(r",(\s*[}\]])", r"\1", raw_json)
    config = json.loads(clean_json)

    # Build feedback content
    content = _build_feedback_content(
        mark,
        feedback_text,
        auto_mark,
        total_available,
        penalty_pct=penalty_pct,
        penalised_mark=penalised_mark,
        penalty_reason=penalty_reason,
    )
    callout = _build_callout_html(content, "info")

    # Remove grader.scores() cell to avoid duplicate score display
    _scores_ids = {
        c["id"]
        for c in config["notebook"]["cells"]
        if SCORES_MARKER in c.get("code", "")
    }
    if _scores_ids:
        config["notebook"]["cells"] = [
            c for c in config["notebook"]["cells"] if c["id"] not in _scores_ids
        ]
        config["session"]["cells"] = [
            c for c in config["session"]["cells"] if c["id"] not in _scores_ids
        ]

    cell_id = "mgFB"
    cell_code = "# mograder feedback"
    code_hash = hashlib.md5(cell_code.encode()).hexdigest()

    # Insert at the top of notebook.cells
    config["notebook"]["cells"].insert(
        0,
        {
            "code": cell_code,
            "code_hash": code_hash,
            "config": {"column": None, "disabled": False, "hide_code": True},
            "id": cell_id,
            "name": "_",
        },
    )

    # Insert at the top of session.cells
    config["session"]["cells"].insert(
        0,
        {
            "code_hash": code_hash,
            "console": [],
            "id": cell_id,
            "outputs": [{"data": {"text/html": callout}, "type": "data"}],
        },
    )

    # Serialize back — escape < and > for script safety
    new_json = json.dumps(config)
    new_json = new_json.replace("<", "\\u003c").replace(">", "\\u003e")

    new_html = html_source[:json_start] + new_json + ";" + html_source[json_end + 1 :]
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(new_html)


def _export_via_marimo(
    notebook_path: Path,
    dest: Path,
    timeout: int = 300,
) -> Path:
    """Export a notebook to HTML by running ``marimo export html``."""
    dest.parent.mkdir(parents=True, exist_ok=True)

    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "marimo",
            "export",
            "html",
            str(notebook_path),
            "-o",
            str(dest),
        ],
        capture_output=True,
        text=True,
        timeout=timeout,
    )

    if proc.returncode != 0 and not dest.exists():
        raise RuntimeError(f"Failed to export {notebook_path}: {proc.stderr[:500]}")

    return dest


def export_feedback_html(
    notebook_path: Path,
    output_dir: Path,
    timeout: int = 300,
    mark: int | float | None = None,
    feedback_text: str | None = None,
    auto_mark: int | float | None = None,
    total_available: int | float | None = None,
    penalty_pct: float | None = None,
    penalised_mark: int | float | None = None,
    penalty_reason: str | None = None,
) -> Path:
    """Export a graded notebook to standalone HTML feedback.

    If an autograde HTML file exists alongside the notebook, injects the
    marker feedback directly into it (fast, no subprocess). Otherwise falls
    back to running ``marimo export html``.

    When *mark* is provided, uses those values directly instead of parsing
    the ``.py`` file for grade data.

    Returns the path to the exported HTML file.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    dest = output_dir / f"{notebook_path.stem}.html"

    autograde_html = notebook_path.with_suffix(".html")

    if autograde_html.exists():
        # Use pre-loaded values if provided, else read from .py
        if mark is not None and feedback_text is not None:
            _mark = mark
            _feedback = feedback_text
            _auto_mark = auto_mark
            _total_avail = total_available
        else:
            lines = notebook_path.read_text().splitlines(keepends=True)
            manual_mark, _feedback = parse_marker_feedback(lines)
            _auto_mark = parse_auto_marks(lines)
            marks_meta = parse_marks_metadata(lines)

            if manual_mark is not None:
                if _auto_mark is not None:
                    _mark = _auto_mark + manual_mark
                else:
                    _mark = manual_mark
                _total_avail = sum(marks_meta.values()) if marks_meta else None
            else:
                _mark = None
                _total_avail = None

        if _mark is not None:
            inject_feedback_html(
                autograde_html.read_text(),
                dest,
                mark=_mark,
                feedback_text=_feedback or "",
                auto_mark=_auto_mark,
                total_available=_total_avail,
                penalty_pct=penalty_pct,
                penalised_mark=penalised_mark,
                penalty_reason=penalty_reason,
            )
        else:
            # Not yet graded — just copy the HTML as-is
            shutil.copy2(autograde_html, dest)

        return dest

    # Fallback: run marimo export
    return _export_via_marimo(notebook_path, dest, timeout)


def collect_grades(graded_notebooks: list[Path]) -> list[dict]:
    """Parse marks and feedback from graded notebooks.

    Returns a list of dicts with keys: student, mark, feedback, auto_mark.

    When per-question marks are present (``_mograder_marks`` in verification cell),
    ``auto_mark`` contains the auto-scored portion and ``mark`` is the total
    (auto + manual). When no marks metadata exists, ``auto_mark`` is None and
    ``mark`` is the raw ``_mark`` value (backward compatible).
    """
    grades = []
    for nb in graded_notebooks:
        lines = nb.read_text().splitlines(keepends=True)
        manual_mark, feedback = parse_marker_feedback(lines)
        auto_mark = parse_auto_marks(lines)

        if auto_mark is not None and manual_mark is not None:
            total_mark = auto_mark + manual_mark
        elif auto_mark is not None:
            # Auto marks present but marker hasn't graded yet
            total_mark = None
        else:
            # No per-question marks — backward compatible
            total_mark = manual_mark

        grades.append(
            {
                "student": nb.stem,
                "mark": total_mark,
                "auto_mark": auto_mark,
                "feedback": feedback,
            }
        )
    return grades


def write_grades_csv(grades: list[dict], path: Path):
    """Write aggregated grades to CSV."""
    path.parent.mkdir(parents=True, exist_ok=True)
    has_auto = any(g.get("auto_mark") is not None for g in grades)
    has_penalty = any(g.get("penalty_pct") is not None for g in grades)
    fieldnames = ["student", "mark", "feedback"]
    if has_auto:
        fieldnames = ["student", "mark", "auto_mark", "feedback"]
    if has_penalty:
        fieldnames.extend(["penalty_pct", "penalised_mark"])
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(grades)
    print(f"Grades written to {path}")
