# Formgrader Dashboard

Launch an interactive grading management dashboard:

```bash
mograder grader course/
```

This opens a marimo app with four tabs:

- **Assignments** — overview table with pipeline status and action buttons for generate, autograde, and export (feedback + Moodle merge). Source and release columns link to `marimo edit`.
- **Submissions** — per-student status for the selected assignment with marks breakdown, edit buttons, and auto/manual/total histograms.
- **Grading** — navigate between students with prev/next, set manual marks and feedback, auto-saved to the gradebook.
- **Students** — cross-assignment marks table with name lookup from the gradebook.

The grader reads `mograder.toml` from the course directory for directory names, Moodle settings, and gradebook path (see [Configuration](../configuration.md)). Options: `--port PORT` to set the server port, `--headless` to suppress the browser.

## ASGI deployment

For deployment as a persistent service behind a reverse proxy, use `grader-asgi`:

```bash
mograder grader-asgi course/ --host 0.0.0.0 --port 2718 --base-url /grading/
mograder grader-asgi course/ --instructors "alice,bob" --trusted-proxies "127.0.0.1"
```

This runs the grader under uvicorn with trusted-proxy authentication middleware. Use `--reload` for development.
