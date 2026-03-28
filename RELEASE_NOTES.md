# mograder 0.3.0

## Breaking changes

This release reorganizes the codebase into sub-packages. **Public APIs are unchanged** — `mograder.runtime` and `mograder.remote` (imported by student notebooks) remain at their existing paths. Internal module paths have changed:

### Module moves

| Old path | New path |
|----------|----------|
| `mograder.models` | `mograder.core.models` |
| `mograder.config` | `mograder.core.config` |
| `mograder.auth` | `mograder.core.auth` |
| `mograder.edit_sessions` | `mograder.core.edit_sessions` |
| `mograder.cells` | `mograder.grading.cells` |
| `mograder.markers` | `mograder.grading.cells` *(merged)* |
| `mograder.runner` | `mograder.grading.runner` |
| `mograder.parser` | `mograder.grading.parser` |
| `mograder.feedback` | `mograder.grading.feedback` |
| `mograder.integrity` | `mograder.grading.integrity` |
| `mograder.safety` | `mograder.grading.safety` |
| `mograder.gradebook` | `mograder.grading.gradebook` |
| `mograder.check_cache` | `mograder.grading.check_cache` |
| `mograder.penalties` | `mograder.grading.penalties` |
| `mograder.wasm_compat` | `mograder.grading.wasm_compat` |
| `mograder.transport` | `mograder.transport.transport` |
| `mograder.https_transport` | `mograder.transport.https_transport` |
| `mograder.https_server` | `mograder.transport.https_server` |
| `mograder.moodle_transport` | `mograder.transport.moodle_transport` |
| `mograder.moodle_api` | `mograder.transport.moodle_api` |
| `mograder.moodle` | `mograder.transport.moodle` |
| `mograder.transport_commands` | `mograder.transport.commands` |
| `mograder.workshop` | `mograder.transport.workshop` |
| `mograder.workshop_server` | `mograder.transport.workshop_server` |
| `mograder.edit_links` | `mograder.transport.edit_links` |
| `mograder.student_app` | `mograder.student.app` |
| `mograder.student_api` | `mograder.student.api` |
| `mograder.student_common` | `mograder.student.common` |
| `mograder.student_wasm_app` | `mograder.student.wasm_app` |
| `mograder.formgrader` | `mograder.grader.scanner` |
| `mograder.formgrader_app` | `mograder.grader.app` |
| `mograder.formgrader_asgi` | `mograder.grader.asgi` |
| `mograder.hub_student_app` | `mograder.hub.student_app` |

### CLI command renames

| Old command | New command |
|-------------|-------------|
| `mograder formgrader` | `mograder grader` |
| `mograder formgrader-asgi` | `mograder grader-asgi` |

### Merged modules

`markers.py` and `cells.py` have been merged into `grading/cells.py`. All public symbols from both modules are available at the new path.

### Deployment

Systemd service files referencing `mograder.formgrader_asgi:app` must be updated to `mograder.grader.asgi:app`.

## New features

- **Sub-package organization**: Modules grouped into `core/`, `grading/`, `transport/`, `student/`, `grader/`, and `hub/` for clearer boundaries.
- **Shared utilities** (`core/_utils.py`): Deduplicated path helpers, timestamp regex, CORS headers, and directory matching across the codebase.
- **Unified token caching** (`core/_token_cache.py`): Single `TokenCache` class replacing duplicated implementations in auth and Moodle API modules.
- **Version display**: Shows git SHA for development/git-based installs, with update notifications for PyPI installs.
- **Hub improvements**: Split student app into hub-specific and local variants, read-only shared venvs, confirmation dialog for Reset.
- **Removed anywidget/traitlets dependencies**.

## What's unchanged

- **`mograder.runtime`** — `check()`, `Grader` class (student notebook API)
- **`mograder.remote`** — `fetch()`, `submit()` (WASM/Pyodide API)
- **CLI entry point** — `mograder.cli:cli`
- **All CLI commands** (except the formgrader → grader rename)
- **Notebook format** — source, release, and autograded notebooks are fully compatible
