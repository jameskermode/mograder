# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
uv sync --extra dev                    # Install with dev dependencies
uv run pytest                          # Run all tests
uv run pytest tests/test_cells.py -v   # Run one test file
uv run pytest -k test_parse_marks      # Run tests matching pattern
uv run ruff check src/                 # Lint
uv run ruff format src/ tests/         # Auto-format (pre-commit hook enforces this)
```

Regenerating student examples (CI checks freshness — must be committed in sync):
```bash
uv run mograder generate examples/demo-assignment.py examples/demo-holistic.py -o examples/release
```

## Architecture

mograder is a pipeline for semi-automated grading of Marimo notebooks. The flow:

```
generate → autograde → (GTA grades in marimo) → feedback → (optional) moodle
```

### Module responsibilities

- **`runtime.py`** — Runtime helpers imported by notebooks. `check()` for holistic grading, `Grader` class for per-question marks with reactive score tracking via `mo.state`.
- **`markers.py`** — Solution stripping (`### BEGIN/END SOLUTION` → `# YOUR CODE HERE`), marker validation, and `convert_markdown_cells()` post-processing. Entry point: `process_file()`.
- **`parser.py`** — Regex-based HTML parsing of marimo's `<marimo-callout-output>` elements to extract check results and cell error counts.
- **`runner.py`** — Notebook execution via `subprocess` (`python -m marimo export html`), parallel batch processing with `ProcessPoolExecutor`, summary table printing, and CSV/ZIP output.
- **`cells.py`** — Generates and injects two grading cells (verification summary + GTA feedback) before `if __name__`. Parses `_mark`/`_feedback`/`_marks` back out of graded notebooks. `parse_marks_metadata()` reads `_marks` dict only. Idempotent.
- **`feedback.py`** — Exports graded notebooks to HTML, collects grades (auto + manual marks), writes grades CSV.
- **`moodle.py`** — Merges grades into Moodle offline grading worksheets (UTF-8-SIG CSV), builds feedback ZIP with Moodle path conventions.
- **`cli.py`** — Click CLI wiring. Four commands: `generate`, `autograde`, `feedback`, `moodle`.

### Key data flow

`runner.run_notebook()` spawns marimo, `parser.py` extracts `CheckResult` list from HTML, `cells.inject_grading_cells()` embeds results + feedback placeholders into the `.py` source, then GTAs edit `_mark`/`_feedback` in marimo, and `cells.parse_gta_feedback()` reads them back.

### Per-question marks (optional)

When a notebook has a `# === MOGRADER: MARKS ===` cell with `_marks = {"Q1": 10, ...}`:
- The `Grader` class handles reactive score tracking at runtime — no generate-time code transforms
- Questions matching a `check()` call are auto-scored (PASS = full marks, FAIL = 0)
- Questions without a matching check are manual (scored by GTA via `_mark`)
- Total = auto earned + manual `_mark`
- Without a marks cell, notebooks use standalone `check()` with holistic `_mark` 0–100

### Marker strings (grep-friendly)

```
### BEGIN SOLUTION / ### END SOLUTION     — solution blocks in staff notebooks
# === MOGRADER: VERIFICATION SUMMARY === — injected verification cell
# === MOGRADER: GTA FEEDBACK ===         — injected feedback cell
# === MOGRADER: MARKS ===                — optional per-question marks cell
```

## Conventions

- Source layout: `src/mograder/`, tests in `tests/`, fixtures in `tests/fixtures/`.
- Local pre-commit hook (`.git/hooks/pre-commit`, not tracked) does two things:
  1. Runs `uv run ruff format --check src/ tests/` on every commit.
  2. If any `examples/demo-*` file is staged, regenerates `examples/release/` and fails if the result differs — so you must stage the updated release files too.
- CI runs tests on Python 3.11–3.13 and verifies `examples/release/` matches regenerated output.
- Check status mapping: HTML `success`→PASS, `danger`→FAIL, `warn`→WAIT.
