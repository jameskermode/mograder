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
generate → autograde → (marker grades in marimo) → feedback → (optional) moodle
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

### CLI argument resolution

`generate`, `autograde`, and `feedback` accept either assignment names or file paths:

```bash
# Name-based (resolved via directory convention)
mograder generate demo-assignment
mograder autograde demo-assignment
mograder feedback demo-assignment

# Path-based (backward compatible)
mograder generate source/demo-assignment/demo-assignment.py
```

An argument is treated as an assignment name if it contains no `/` and doesn't end with `.py`. Names are resolved to `*.py` files in the appropriate base directory (`source_dir`, `submitted_dir`, or `autograded_dir`).

### Package structure

```
src/mograder/
├── cli.py              ← Click CLI entry point
├── runtime.py          ← Public API: check(), Grader (imported by notebooks)
├── remote.py           ← Public API: stdlib-only fetch/submit (works in WASM)
├── core/               ← Foundation (shared across sub-packages)
│   ├── models.py       ← CheckResult, NotebookResult dataclasses
│   ├── config.py       ← TOML config (mograder.toml), MograderConfig
│   ├── auth.py         ← HMAC-SHA256 token auth for HTTPS transport
│   ├── edit_sessions.py← Headless marimo edit sessions, ASGI proxy
│   ├── _utils.py       ← Shared utilities (rel, TIMESTAMP_RE, CORS helpers)
│   └── _token_cache.py ← Unified file-based token caching
├── grading/            ← Pipeline: generate → autograde → feedback
│   ├── cells.py        ← Marker validation, solution stripping, grading cell injection/parsing
│   ├── runner.py       ← Notebook execution, batch processing, sandboxing
│   ├── parser.py       ← HTML callout parsing from marimo exports
│   ├── feedback.py     ← HTML feedback export, grade aggregation, CSV output
│   ├── integrity.py    ← Tampering detection via cell hash comparison
│   ├── safety.py       ← AST-based safety scanner for submitted code
│   ├── gradebook.py    ← SQLite-backed persistent grade storage (WAL mode)
│   ├── check_cache.py  ← File-based caching of notebook validation results
│   ├── penalties.py    ← Late submission penalty calculations
│   └── wasm_compat.py  ← WASM compatibility checking (Pyodide blocklist)
├── transport/          ← Remote communication (Moodle, HTTPS, workshop)
│   ├── transport.py    ← Transport Protocol + build_transport() factory
│   ├── https_transport.py, https_server.py
│   ├── moodle_transport.py, moodle_api.py, moodle.py
│   ├── commands.py     ← Shared do_fetch, do_submit, do_status logic
│   ├── edit_links.py   ← Moodle assignment description edit-link injection
│   └── workshop.py, workshop_server.py
├── student/            ← Student-facing apps
│   ├── app.py          ← Marimo student dashboard (mograder student)
│   ├── api.py          ← Read-only Starlette API for assignment browsing
│   ├── common.py       ← Shared student app helpers
│   └── wasm_app.py     ← WASM student app (browser-only)
├── grader/             ← Instructor grading dashboard
│   ├── app.py          ← Marimo grader app (mograder grader)
│   ├── scanner.py      ← Directory scanning, assignment discovery
│   └── asgi.py         ← ASGI grader with trusted-proxy auth middleware
└── hub/                ← Multi-user hub server
    ├── app.py, auth.py, models.py, proxy.py, spawner.py, storage.py
    └── student_app.py
```

### Module responsibilities

- **`runtime.py`** — Public notebook API: `check()` for holistic grading, `Grader` class for per-question marks with reactive score tracking via `mo.state`.
- **Written analysis cells**: Use `response_text` (not `_response`) as the variable name for the student's written response, and `return (response_text,)` so the word count cell can reactively consume it.
- **`remote.py`** — Stdlib-only helpers for fetching, submitting, and checking assignment status via `urllib` (no `requests` dependency, works in Pyodide/WASM).
- **`grading/cells.py`** — Solution stripping (`### BEGIN/END SOLUTION` → `# YOUR CODE HERE`), marker validation, `convert_markdown_cells()`, grading cell injection/parsing, `process_file()` entry point. Merged from old `markers.py` + `cells.py`.
- **`grading/runner.py`** — Notebook execution via `subprocess` (`python -m marimo export html`), parallel batch processing with `ProcessPoolExecutor`, summary table printing, and CSV/ZIP output.
- **`grading/integrity.py`** — Integrity checking: compares check/marks cells between source and submitted notebooks via marimo's `MarimoConvert` parser. Detects tampering and reinjects source cells.
- **`grading/feedback.py`** — Exports graded notebooks to HTML, collects grades (auto + manual marks), writes grades CSV.
- **`transport/moodle_api.py`** — Moodle REST Web Services API client. Token authentication via `/login/token.php` with caching to `~/.config/mograder/token.json`.
- **`transport/transport.py`** — `Transport` Protocol with methods: `list_assignments`, `download_file`, `submit_file`, `get_submissions`, `upload_grades`, `get_status`. `build_transport(config)` factory reads `config.transport` to select implementation.
- **`core/edit_sessions.py`** — Shared headless edit session utilities and ASGI reverse proxy: spawn `marimo edit` processes, manage session lifecycle, and proxy HTTP/WebSocket traffic.
- **`grader/scanner.py`** — Directory scanning for grader dashboard with assignment discovery, automatic marks parsing, and marker feedback extraction.
- **`grader/asgi.py`** — ASGI grader app with trusted-proxy authentication middleware (localhost=instructor, trusted proxies read `X-Remote-User` header).
- **`cli.py`** — Click CLI wiring. Commands: `generate`, `validate`, `autograde`, `feedback`, `moodle` (group), `https` (group), `token`, `serve`, `student`, `grader`. The `moodle` group has subcommands: `export`, `fetch`, `submit`, `fetch-submissions`, `upload-feedback`, `upload`, `feedback`, `sync`, `sync-users`, `login`. The `https` group has subcommands: `login`, `fetch`, `submit`, `fetch-submissions`, `upload-grades`, `feedback`. `token` generates HMAC-SHA256 auth tokens for given usernames. `serve` starts the assignment server. Smart output directory defaults infer from nbgrader convention. `--source` auto-discovery. Integrity checking integrated into autograde.

### Key data flow

`grading.runner.run_notebook()` spawns marimo, `grading.parser` extracts `CheckResult` list from HTML, `grading.cells.inject_grading_cells()` embeds results + feedback placeholders into the `.py` source, then markers edit `_mark`/`_feedback` in marimo, and `grading.cells.parse_marker_feedback()` reads them back.

When `--source` is provided to autograde, `grading.integrity.check_integrity()` compares check/marks cells between source and submitted notebooks before execution. Tampered cells are reinjected from the source.

### Per-question marks (optional)

When a notebook has a `# === MOGRADER: MARKS ===` cell with `_marks = {"Q1": 10, ...}`:
- The `Grader` class handles reactive score tracking at runtime — no generate-time code transforms
- Questions matching a `check()` call are auto-scored with **partial credit**: marks are proportional to the weight of passing checks (`earned = round(avail × earned_weight / total_weight, 1)`)
- Check tuples support optional weights: `(bool, str)` (weight=1) or `(bool, str, weight)` (custom weight)
- Questions without a matching check are manual (scored by marker via `_mark`)
- Total = auto earned + manual `_mark`
- Without a marks cell, notebooks use standalone `check()` with holistic `_mark` 0–100

### Marker strings (grep-friendly)

```
### BEGIN SOLUTION / ### END SOLUTION     — solution blocks in source notebooks
# === MOGRADER: VERIFICATION SUMMARY === — injected verification cell
# === MOGRADER: MARKER FEEDBACK ===      — injected feedback cell
# === MOGRADER: MARKS ===                — optional per-question marks cell
```

## Conventions

- **Marimo `_` prefix rule**: In marimo notebooks (`student/app.py`, `grader/app.py`), names prefixed with `_` are **private to the cell** and cannot be referenced from callbacks or other cells. Never use `_`-prefixed names for UI elements, variables referenced in `on_change` handlers, or anything that needs to be visible outside the immediate cell scope. Use unprefixed names instead.
- Source layout: `src/mograder/`, tests in `tests/`, fixtures in `tests/fixtures/`.
- Examples: `examples/source/` (source notebooks in assignment subdirs), `examples/release/` (generated release versions in matching subdirs).
- Local pre-commit hook (`.git/hooks/pre-commit`, not tracked) does two things:
  1. Runs `uv run ruff format --check src/ tests/` on every commit.
  2. If any `examples/source/` file is staged, regenerates `examples/release/` and fails if the result differs — so you must stage the updated release files too.
- CI runs tests on Python 3.11–3.13 and verifies `examples/release/` matches regenerated output.
- Check status mapping: HTML `success`→PASS, `partial`→PARTIAL (blue, fractional marks), `danger`→FAIL, `warn`→WAIT.
