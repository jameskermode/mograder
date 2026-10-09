# Grader Dashboard

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

### Roles: instructors and markers

Behind a reverse proxy, each user's role comes from the `X-Remote-User`
header the proxy sets:

| Role | Who | Can do |
|------|-----|--------|
| Instructor | `--instructors` (`MOGRADER_INSTRUCTORS`) | everything: generate, autograde, import/export, fetch submissions and upload feedback to Moodle, open assignments for marking |
| Marker | `--markers` (`MOGRADER_MARKERS`), e.g. GTAs | the **Submissions** and **Grading** tabs only, for assignments an instructor has opened for marking: open autograded submissions in the editor, mark, save. No Moodle actions, no Students tab |
| anyone else | | refused (403) when `--markers` is set; a marker otherwise |

With neither list set, every proxied user is an instructor (as before roles
existed). Local access without the header (`localhost`) is always the
instructor.

**Opening an assignment for marking.** The Assignments tab has a *Marking*
switch per assignment; markers see an assignment only while it is on (stored
in `marking.json` in the course directory). A typical cycle: fetch
submissions, autograde, check the results, switch *Marking* on, tell the
markers; switch it off when marking is done, then upload feedback.

The role checks are enforced in the app (actions and uploads), not only by
hiding controls, and the edit-session API is instructor-only.

**SSH tunnel.** When the proxy reaches the grader through an SSH tunnel, all
requests arrive from `localhost`; use `--trust-local-proxy`
(`MOGRADER_TRUST_LOCAL_PROXY=1`) so the header is read there too, and bind
the grader to `127.0.0.1` so only the tunnel and local users reach it.
