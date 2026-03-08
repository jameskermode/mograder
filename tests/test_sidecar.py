"""Tests for sidecar JSONL check result extraction."""

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

from mograder.models import CheckResult
from mograder.runner import _read_sidecar, run_notebook


def test_write_sidecar_writes_jsonl(tmp_path):
    """_write_sidecar appends a JSONL record when env var is set."""
    sidecar = tmp_path / "results.jsonl"
    env = {"MOGRADER_SIDECAR_PATH": str(sidecar)}

    with patch.dict(os.environ, env, clear=False):
        from mograder.runtime import _write_sidecar

        _write_sidecar("Q1: Foo", "success", [])
        _write_sidecar("Q2: Bar", "danger", ["x must be > 0", "y is missing"])

    lines = sidecar.read_text().strip().splitlines()
    assert len(lines) == 2

    r1 = json.loads(lines[0])
    assert r1 == {"label": "Q1: Foo", "status": "success", "details": []}

    r2 = json.loads(lines[1])
    assert r2["label"] == "Q2: Bar"
    assert r2["status"] == "danger"
    assert r2["details"] == ["x must be > 0", "y is missing"]


def test_write_sidecar_noop_without_env(tmp_path):
    """_write_sidecar does nothing when MOGRADER_SIDECAR_PATH is unset."""
    env = {k: v for k, v in os.environ.items() if k != "MOGRADER_SIDECAR_PATH"}
    with patch.dict(os.environ, env, clear=True):
        from mograder.runtime import _write_sidecar

        _write_sidecar("Q1: Foo", "success", [])
    # No file created — just verifying no exception


def test_read_sidecar_parses_jsonl(tmp_path):
    """_read_sidecar reads JSONL into CheckResult list."""
    sidecar = tmp_path / "results.jsonl"
    records = [
        {"label": "Q1: Foo", "status": "success", "details": []},
        {"label": "Ex1: Bar", "status": "danger", "details": ["fail msg"]},
    ]
    sidecar.write_text("\n".join(json.dumps(r) for r in records) + "\n")

    results = _read_sidecar(sidecar)
    assert len(results) == 2
    assert results[0] == CheckResult(label="Q1: Foo", status="success", details=[])
    assert results[1].label == "Ex1: Bar"
    assert results[1].status == "danger"
    assert results[1].details == ["fail msg"]


def test_read_sidecar_empty_file(tmp_path):
    """_read_sidecar returns empty list for empty file."""
    sidecar = tmp_path / "results.jsonl"
    sidecar.write_text("")
    assert _read_sidecar(sidecar) == []


def test_read_sidecar_missing_file(tmp_path):
    """_read_sidecar returns empty list for non-existent file."""
    assert _read_sidecar(tmp_path / "no_such_file.jsonl") == []


def test_read_sidecar_skips_bad_lines(tmp_path):
    """_read_sidecar skips malformed JSONL lines."""
    sidecar = tmp_path / "results.jsonl"
    sidecar.write_text(
        '{"label": "Q1: Foo", "status": "success", "details": []}\n'
        "not valid json\n"
        '{"label": "Q2: Bar", "status": "warn", "details": []}\n'
    )
    results = _read_sidecar(sidecar)
    assert len(results) == 2


def test_run_notebook_prefers_sidecar(tmp_path):
    """run_notebook uses sidecar results when available."""
    nb = tmp_path / "test.py"
    nb.write_text("# notebook")

    sidecar_records = [
        {"label": "Jensen: Inequality", "status": "success", "details": []},
    ]

    def mock_run(cmd, **kwargs):
        # Write sidecar file
        sidecar_path = kwargs.get("env", {}).get("MOGRADER_SIDECAR_PATH")
        if sidecar_path:
            with open(sidecar_path, "w") as f:
                for rec in sidecar_records:
                    f.write(json.dumps(rec) + "\n")

        # Write HTML output
        out_idx = cmd.index("-o")
        html_path = Path(cmd[out_idx + 1])
        html_path.write_text("<html>no callouts</html>")

        result = MagicMock()
        result.returncode = 0
        result.stderr = ""
        return result

    with patch("mograder.runner.subprocess.run", side_effect=mock_run):
        result = run_notebook(nb)

    assert len(result.checks) == 1
    assert result.checks[0].label == "Jensen: Inequality"
    assert result.checks[0].status == "success"


def test_run_notebook_falls_back_to_html(tmp_path):
    """run_notebook falls back to HTML parsing when sidecar is empty."""
    nb = tmp_path / "test.py"
    nb.write_text("# notebook")

    html_content = (
        "<html>"
        "Q1: Data check\\u0026lt;/strong\\u0026gt; \\u2014 all checks passed"
        "</html>"
    )

    def mock_run(cmd, **kwargs):
        out_idx = cmd.index("-o")
        html_path = Path(cmd[out_idx + 1])
        html_path.write_text(html_content)

        result = MagicMock()
        result.returncode = 0
        result.stderr = ""
        return result

    with patch("mograder.runner.subprocess.run", side_effect=mock_run):
        result = run_notebook(nb)

    assert len(result.checks) == 1
    assert result.checks[0].label == "Q1: Data check"
