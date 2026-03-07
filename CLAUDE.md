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

Regenerating release examples (CI checks freshness — must be committed in sync):
```bash
uv run mograder generate examples/source/demo-assignment/demo-assignment.py examples/source/demo-holistic/demo-holistic.py -o examples/release
```

## Architecture

mograder is a pipeline for semi-automated grading of Marimo notebooks. The flow follows [nbgrader terminology](https://nbgrader.readthedocs.io/en/latest/user_guide/philosophy.html):

```
generate → autograde → (GTA grades in marimo) → feedback → (optional) moodle
source   → release   → submitted → autograded → feedback
```

### Directory convention

```
course/
  source/assignment-name/assignment-name.py    ← source notebooks (with solutions)
  release/assignment-name/assignment-name.py   ← generated release versions
  submitted/assignment-name/student.py         ← student submissions
  autograded/assignment-name/student.py        ← autograded with injected cells
  feedback/assignment-name/student.html        ← exported HTML feedback
```

### Module responsibilities

- **`runtime.py`** — Runtime helpers imported by notebooks. `check()` for holistic grading, `Grader` class for per-question marks with reactive score tracking via `mo.state`.
- **`markers.py`** — Solution stripping (`### BEGIN/END SOLUTION` → `# YOUR CODE HERE`), marker validation, and `convert_markdown_cells()` post-processing. Entry point: `process_file()`.
- **`parser.py`** — Regex-based HTML parsing of marimo's `<marimo-callout-output>` elements to extract check results and cell error counts.
- **`runner.py`** — Notebook execution via `subprocess` (`python -m marimo export html`), parallel batch processing with `ProcessPoolExecutor`, summary table printing, and CSV/ZIP output.
- **`cells.py`** — Generates and injects two grading cells (verification summary + GTA feedback) before `if __name__`. Parses `_mark`/`_feedback`/`_marks` back out of graded notebooks. `parse_marks_metadata()` reads `_marks` dict only. Idempotent.
- **`integrity.py`** — Integrity checking: compares check/marks cells between source and submitted notebooks via marimo's `MarimoConvert` parser. Detects tampering and reinjects source cells. Returns `IntegrityResult` with tampered info and fixed source.
- **`feedback.py`** — Exports graded notebooks to HTML, collects grades (auto + manual marks), writes grades CSV.
- **`moodle.py`** — Merges grades into Moodle offline grading worksheets (UTF-8-SIG CSV), builds feedback ZIP with Moodle path conventions.
- **`moodle_api.py`** — Moodle REST Web Services API client. `MoodleAPIClient` class for fetching assignments, downloading/uploading files, saving submissions, and pushing grades. Credential resolution (CLI flag > env var > config). Assignment name matching. Token authentication via `/login/token.php` with caching to `~/.config/mograder/token.json`.
- **`student_app.py`** — Marimo web app for students. Login to Moodle, browse assignments, fetch files, open notebooks for editing (launches `marimo edit`), and submit completed work. Launched via `mograder student`.
- **`cli.py`** — Click CLI wiring. Commands: `generate`, `autograde`, `feedback`, `moodle` (group), `student`, `formgrader`. The `moodle` group has subcommands: `export` (merge grades into Moodle CSV), `fetch` (student downloads assignment), `submit` (student uploads submission), `fetch-submissions` (instructor bulk download), `upload-feedback` (instructor bulk grade push). Smart output directory defaults infer from nbgrader convention. `--source` auto-discovery. Integrity checking integrated into autograde.

### Key data flow

`runner.run_notebook()` spawns marimo, `parser.py` extracts `CheckResult` list from HTML, `cells.inject_grading_cells()` embeds results + feedback placeholders into the `.py` source, then GTAs edit `_mark`/`_feedback` in marimo, and `cells.parse_gta_feedback()` reads them back.

When `--source` is provided to autograde, `integrity.check_integrity()` compares check/marks cells between source and submitted notebooks before execution. Tampered cells are reinjected from the source.

### Per-question marks (optional)

When a notebook has a `# === MOGRADER: MARKS ===` cell with `_marks = {"Q1": 10, ...}`:
- The `Grader` class handles reactive score tracking at runtime — no generate-time code transforms
- Questions matching a `check()` call are auto-scored (PASS = full marks, FAIL = 0)
- Questions without a matching check are manual (scored by GTA via `_mark`)
- Total = auto earned + manual `_mark`
- Without a marks cell, notebooks use standalone `check()` with holistic `_mark` 0–100

### Marker strings (grep-friendly)

```
### BEGIN SOLUTION / ### END SOLUTION     — solution blocks in source notebooks
# === MOGRADER: VERIFICATION SUMMARY === — injected verification cell
# === MOGRADER: GTA FEEDBACK ===         — injected feedback cell
# === MOGRADER: MARKS ===                — optional per-question marks cell
```

## Conventions

- Source layout: `src/mograder/`, tests in `tests/`, fixtures in `tests/fixtures/`.
- Examples: `examples/source/` (source notebooks in assignment subdirs), `examples/release/` (generated release versions in matching subdirs).
- Local pre-commit hook (`.git/hooks/pre-commit`, not tracked) does two things:
  1. Runs `uv run ruff format --check src/ tests/` on every commit.
  2. If any `examples/source/` file is staged, regenerates `examples/release/` and fails if the result differs — so you must stage the updated release files too.
- CI runs tests on Python 3.11–3.13 and verifies `examples/release/` matches regenerated output.
- Check status mapping: HTML `success`→PASS, `danger`→FAIL, `warn`→WAIT.
