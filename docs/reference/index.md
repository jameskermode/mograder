# API & CLI Reference

This section provides auto-generated reference documentation for mograder's Python API and CLI.

## Runtime API

The [Runtime API](runtime.md) covers the public symbols used inside notebooks:

- `check()` — run boolean checks and display coloured feedback
- `Grader` — per-question marks with reactive score tracking
- `hint()` — progressive hints in collapsed accordions

## CLI Reference

The [CLI Reference](cli.md) documents all `mograder` commands and their options, auto-generated from the Click decorators.

## Python Modules

| Module | Description |
|--------|-------------|
| [Configuration](config.md) | `MograderConfig`, `load_config()` |
| [Models](models.md) | `CheckResult`, `NotebookResult`, data classes |
| [Transport](transport.md) | `Transport` protocol, `build_transport()` |
| [Gradebook](gradebook.md) | `Gradebook` class (SQLite) |
| [Cells](markers.md) | `process_file()`, `strip_solutions()`, `inject_grading_cells()` |
| [Moodle API](moodle-api.md) | `MoodleAPIClient` |
