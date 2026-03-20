# Student Dashboard

Launch an interactive course browser as a local Marimo web app:

```bash
mograder student <CONFIG_URL>       # first-time setup from URL
mograder student                    # current directory (returning sessions)
mograder student ~/coursework/      # specific course directory
mograder student --port 8080        # custom port
mograder student --headless         # no browser auto-open
```

!!! tip
    The [desktop app](https://github.com/jameskermode/mograder-tauri/releases/latest) launches the student dashboard automatically with no CLI needed — just paste your course URL on first launch.

The dashboard provides:

- **Login** — for Moodle courses, paste your Moodle security token (from your Moodle Security Keys page). For HTTPS transport courses, register with your username and the enrollment code provided by your instructor (or paste a token directly). Tokens are cached at `~/.config/mograder/`.
- **Assignment table** — lists all course assignments with due dates, status, check validation results, and action buttons.
- **Download** — downloads assignment `.py` files into per-assignment subdirectories.
- **Edit** — opens the notebook in a new `marimo edit --sandbox` session.
- **Validate** — runs the notebook and shows a summary of check results (e.g. "3/5 PASS") with an inline HTML report preview. Warns if non-solution cells have been accidentally modified. Results are cached and marked stale when the notebook changes.
- **Submit** — uploads the `.py` file to Moodle and finalizes the submission.
- **Status tracking** — shows Downloaded, Submitted, or Modified for each assignment.
- **Activity log** — shows status messages for recent actions with dismiss button.
