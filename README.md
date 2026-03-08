# mograder

Semi-automated grading for [Marimo](https://marimo.io) notebooks.

mograder is the Marimo equivalent of [nbgrader](https://nbgrader.readthedocs.io/). Coding exercises support optional per-question marks via `Grader` (auto-scored pass/fail), while written analysis sections are hand-graded. Alternatively, without per-question marks, a single holistic mark (0-100) is assigned.

## Try it

A live demo is available with three components:

1. **[Student Dashboard](https://jameskermode.github.io/mograder/?server=https://mograder-demo.onrender.com&editor=https://mograder-editor.onrender.com)** — WASM app hosted on GitHub Pages. Lists assignments, shows submission status, and links to the editor for editing.
2. **[Formgrader + Assignment Server](https://mograder-demo.onrender.com)** — Render free-tier instance running a combined ASGI app. The formgrader UI shows the full grading workflow (assignments, submissions, grading, students tabs) with pre-populated demo data. The same service also handles the assignment API at `/assignments`.
3. **[Notebook Editor](https://mograder-editor.onrender.com)** — Render free-tier instance running `marimo edit --sandbox`. Click "Edit" in the dashboard to open a notebook in full edit mode with PEP 723 dependency isolation. Each notebook has a submit cell to send your work back to the assignment server.

Both Render services run on the free tier, so the first request after idle may take ~30s (cold start). As an alternative to the hosted editor, the dashboard also supports [Molab](https://molab.marimo.io) links — pass `repo`, `path`, and `branch` query params instead of `editor` to use GitHub-backed editing.

## For students

See the [Student Setup Guide](docs/student-setup.md) for full instructions.

**Quick start** (macOS/Linux — just 2 commands):
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
uvx mograder student <CONFIG_URL>
```

## Directory convention

mograder follows [nbgrader's terminology](https://nbgrader.readthedocs.io/en/latest/user_guide/philosophy.html): **source** → **release** → **submitted** → **autograded** → **feedback**.

```
course/
  mograder.toml              ← optional config (dirs, moodle settings, etc.)
  gradebook.db               ← SQLite gradebook (created by autograde)
  source/
    assignment-name/
      assignment-name.py     ← source notebook (with solutions)
      data.csv               ← auxiliary files (copied to release)
  release/
    assignment-name/
      assignment-name.py     ← generated (solutions stripped)
      data.csv               ← copied from source
  submitted/
    assignment-name/
      student1.py            ← student submissions
  autograded/
    assignment-name/
      student1.py            ← output of mograder autograde
  feedback/
    assignment-name/
      student1.html          ← output of mograder feedback
  import/
    assignment-name.csv      ← Moodle offline grading worksheet (optional)
```

## Workflow

1. **`mograder generate`** — `source/*.py` → `release/*.py` (strip solutions)
2. **Students** complete and submit `.py` files
3. **`mograder autograde`** — `submitted/*.py` → `autograded/*.py`
   - Integrity check against source notebook (detects tampered check/marks cells)
   - Runs each notebook via `marimo export html`
   - Parses check results from HTML
   - Injects verification summary + GTA feedback cells
   - Stores results in `gradebook.db`
4. **GTAs grade** — formgrader Grading tab or `marimo edit`
   - GTA sets manual mark and feedback per student
   - Grades saved to `gradebook.db`
5. **`mograder feedback`** — `autograded/*.py` → `feedback/*.html`
   - Injects mark + feedback callout into existing autograde HTML
   - Removes self-assessment scores cell
6. **`mograder moodle export`** — `gradebook.db` + `worksheet.csv` → `export/`
   - Merges grades into Moodle offline grading worksheets
   - Bundles HTML feedback into a Moodle-compatible ZIP
   - Auto-imports student names into gradebook
7. **`mograder moodle fetch`** / **`mograder moodle submit`** — students fetch assignments and submit work via Moodle API
8. **`mograder moodle fetch-submissions`** / **`mograder moodle upload-feedback`** — instructors bulk-download submissions and push grades/feedback via Moodle API
9. **`mograder moodle sync`** — syncs assignment metadata from Moodle into `mograder.toml` (instructor runs this, students get the config via URL or file)
10. **`mograder student`** — launches an interactive student dashboard (Marimo app) for downloading, validating, editing, and submitting assignments
11. **`mograder serve`** / **`mograder https *`** — lightweight HTTPS server + transport for assignment distribution without Moodle

## Installation

Stable release:

```
pip install mograder # or: uv add mograder
```

Development version:

```bash
git clone https://github.com/jameskermode/mograder.git
cd mograder
uv venv && uv pip install -e ".[dev]"
```

## Usage

### Formgrader dashboard

Launch an interactive grading management dashboard:

```bash
mograder formgrader course/
```

This opens a marimo app with four tabs:

- **Assignments** — overview table with pipeline status and action buttons for generate, autograde, and export (feedback + Moodle merge). Source and release columns link to `marimo edit`.
- **Submissions** — per-student status for the selected assignment with marks breakdown, edit buttons, and auto/manual/total histograms.
- **Grading** — navigate between students with prev/next, set manual marks and feedback, auto-saved to the gradebook.
- **Students** — cross-assignment marks table with name lookup from the gradebook.

The formgrader reads `mograder.toml` from the course directory for directory names, Moodle settings, and gradebook path (see [Configuration](#configuration)). Options: `--port PORT` to set the server port, `--headless` to suppress the browser.

### Generate release notebooks

Strip solution blocks from source notebooks:

```bash
mograder generate source/hw1/hw1.py -o release/
mograder generate source/hw1/hw1.py --dry-run    # preview only
mograder generate source/hw1/hw1.py --validate   # check markers only
```

Source notebooks use markers to delimit solutions:

```python
### BEGIN SOLUTION
x = 42
### END SOLUTION
```

Solution blocks are replaced with `# YOUR CODE HERE` / `pass` in the release version. Auxiliary files (data, helper modules) are automatically copied from the source directory. Notebooks import `check()` from `mograder.runtime` for formative feedback, or use `Grader` for per-question marks with reactive score tracking.

### Autograde submissions

Run student notebooks and prepare grading copies with injected feedback cells:

```bash
mograder autograde submitted/hw1/*.py -o autograded/hw1/
mograder autograde submitted/hw1/*.py --source source/hw1/hw1.py --csv results.csv
mograder autograde submitted/hw1/*.py -j 8 --timeout 600
```

When `--source` is provided (or auto-discovered from a sibling `source/` directory), mograder performs an integrity check — tampered check cells or marks definitions are reinjected from the source before execution. Default values for `-j` and `--timeout` can be set in `mograder.toml` (see [Configuration](#configuration)).

#### Autograde directly from Moodle downloads

Instead of manually extracting submissions, you can pass the Moodle offline grading CSV and submission ZIP directly:

```bash
mograder autograde --moodle-csv grades.csv --moodle-zip submissions.zip --source source/hw1/hw1.py
```

This extracts submissions from the ZIP (mapping participant IDs to usernames via the CSV), then runs the normal autograde flow. The output directory and assignment name are inferred from the source notebook path.

### Export feedback

Export graded notebooks to HTML and aggregate marks:

```bash
mograder feedback autograded/hw1/*.py -o feedback/hw1/
mograder feedback autograded/hw1/*.py --grades-csv grades.csv
```

### Import student names

Import student names from a Moodle CSV into the gradebook (used for name display in the formgrader):

```bash
mograder import-students worksheet.csv
```

### Sync to remote server

Sync autograded results to a remote server (e.g. a shared formgrader instance) via rsync + SSH:

```bash
mograder sync autograded/hw1/ --remote sciml --course-dir /home/svc_user/courses/es98e
```

This rsyncs `.py` and `.html` files to the remote `autograded/` directory, then runs `Gradebook.import_from_py()` on the server via SSH to update the remote gradebook. If the remote uses a uv-managed venv, pass `--venv-dir`:

```bash
mograder sync autograded/hw1/ --remote sciml --course-dir /home/svc_user/courses/es98e --venv-dir '~/marimo-server'
```

All three flags can be set in `mograder.toml` (see [Configuration](#configuration)) so you can just run `mograder sync autograded/hw1/`.

Autograded results can also be uploaded via the formgrader UI using the upload button in the Graded column of the Assignments table.

### Moodle integration

The `mograder moodle` command group provides both offline CSV-based workflows and live Moodle API access.

#### Export grades (offline)

Merge grades into a Moodle offline grading worksheet and bundle feedback:

```bash
mograder moodle export "HW1" -o export/
mograder moodle export "HW1" --feedback-dir feedback/ -o export/
mograder moodle export "HW1" --worksheet custom.csv -o export/
```

The worksheet is auto-discovered at `import/<assignment>.csv` (matching formgrader convention). Grades are read from `gradebook.db` by default. The match column and name column can be configured in `mograder.toml` (see [Configuration](#configuration)). Student names are auto-imported into the gradebook when the moodle command runs.

#### Fetch assignment (student)

Download assignment files from Moodle:

```bash
mograder moodle fetch "HW1"                     # download by name
mograder moodle fetch "HW1" -o ~/coursework/     # custom output directory
mograder moodle fetch --list                     # list available assignments
```

Downloads all attached files (`.py` notebooks and `.zip` archives with input data). ZIP files are automatically extracted. Assignment matching is flexible: exact name, numeric ID, or case-insensitive substring.

#### Submit assignment (student)

Upload a completed notebook to Moodle:

```bash
mograder moodle submit "HW1" hw1.py              # upload and finalize
mograder moodle submit "HW1" hw1.py --dry-run    # check without uploading
mograder moodle submit "HW1" hw1.py --no-finalize  # upload draft only
```

Only `.py` files are accepted. By default, submissions are finalized (visible to graders). Use `--no-finalize` to save as draft.

#### Fetch submissions (instructor)

Bulk-download all student submissions for an assignment:

```bash
mograder moodle fetch-submissions "HW1" -o submitted/hw1/
```

Downloads each student's latest `.py` submission, named by username.

#### Upload feedback (instructor)

Push grades and feedback to Moodle via the API:

```bash
mograder moodle upload-feedback "HW1"                # from gradebook.db
mograder moodle upload-feedback "HW1" --dry-run      # preview without pushing
mograder moodle upload-feedback "HW1" --grades-csv grades.csv  # from CSV
```

#### Sync assignment metadata (instructor)

Fetch assignment metadata from Moodle and write it to `mograder.toml`:

```bash
mograder moodle sync                          # sync all visible assignments
mograder moodle sync --include '^A[1-8]'      # only assignments matching regex
```

Only assignments visible to students are included (hidden assignments are excluded). Students receive this metadata via the config URL or file. Re-run after publishing or hiding assignments.

#### View feedback (student)

Check your submission status and view grade/feedback:

```bash
mograder moodle feedback "HW1"
```

Shows submission status, grade (if graded), and instructor feedback text.

All Moodle API commands accept `--url` and `--token` flags, or read from `MOGRADER_MOODLE_URL` / `MOGRADER_MOODLE_TOKEN` environment variables, or from the `[moodle]` section in `mograder.toml`.

### HTTPS transport (Moodle-free alternative)

mograder includes a lightweight HTTP server and transport for distributing assignments without Moodle. This is useful for courses that don't use Moodle, for local testing, or as a simple course server on platforms like Molab.

#### Start an assignment server

```bash
mograder serve course/release/        # serve assignment files
mograder serve course/release/ -p 9000  # custom port
```

The server auto-discovers assignments from the directory structure. Each subdirectory with a `files/` subfolder becomes an assignment. You can also provide a manual `assignments.json` manifest.

#### Student commands

```bash
mograder https fetch --list --url http://localhost:8080        # list assignments
mograder https fetch "hw1" --url http://localhost:8080 -o hw1/ # download files
mograder https submit hw1.py -a "hw1" --url http://localhost:8080 --user alice
mograder https feedback "hw1" --url http://localhost:8080 --user alice
```

#### Instructor commands

```bash
mograder https fetch-submissions "hw1" --url http://localhost:8080 -o submitted/hw1/
mograder https upload-grades "hw1" --url http://localhost:8080 --grades-csv grades.csv
```

The URL can also be set in `mograder.toml`:

```toml
transport = "https"

[https]
url = "http://localhost:8080"
```

#### Server directory structure

```
server_root/
  assignments.json                    # optional manifest
  hw1/
    files/
      homework.py                     # assignment files
    submissions/
      alice.py                        # student submissions
    grades.json                       # uploaded grades
```

### Student dashboard

Launch an interactive course browser as a local Marimo web app:

```bash
mograder student <CONFIG_URL>       # first-time setup from URL
mograder student                    # current directory (returning sessions)
mograder student ~/coursework/      # specific course directory
mograder student --port 8080        # custom port
mograder student --headless         # no browser auto-open
```

The dashboard provides:

- **Moodle login** — paste your Moodle security token (from your Moodle Security Keys page). Tokens are cached at `~/.config/mograder/token.json`.
- **Assignment table** — lists all course assignments with due dates, status, check validation results, and action buttons.
- **Download** — downloads assignment `.py` files into per-assignment subdirectories.
- **Edit** — opens the notebook in a new `marimo edit --sandbox` session.
- **Validate** — runs the notebook and shows a summary of check results (e.g. "3/5 PASS") with an inline HTML report preview. Results are cached and marked stale when the notebook changes.
- **Submit** — uploads the `.py` file to Moodle and finalizes the submission.
- **Status tracking** — shows Downloaded, Submitted, or Modified for each assignment.
- **Activity log** — shows status messages for recent actions with dismiss button.

## Configuration

Create `mograder.toml` in the course directory to customise settings:

```toml
config_url = "https://raw.githubusercontent.com/user/course/main/mograder.toml"
transport = "moodle"   # or "https" — selects the active transport for student/formgrader

# Transport-agnostic assignment list (written by `moodle sync` or `https sync`)
[[assignments]]
name = "HW1"
id = "10"
cmid = "42"
duedate = 1700000000
  [[assignments.files]]
  name = "hw1.py"
  url = "https://..."

[dirs]
source = "source"       # default directory names
import = "import"       # Moodle worksheets for export

[moodle]
url = "https://moodle.uni.ac.uk"  # Moodle site URL (for API commands)
course_id = 12345                  # Moodle course ID (for API commands)
csv = "moodle.csv"                 # default Moodle worksheet (for export)
match_column = "Username"
name_column = "Full name"

[https]
url = "http://localhost:8080"      # HTTPS transport server URL

[defaults]
jobs = 4
timeout = 300

[gradebook]
path = "gradebook.db"

[sync]
remote = "sciml"                                    # SSH host alias
remote_course_dir = "/home/svc_user/courses/es98e"  # course dir on remote
remote_venv_dir = "~/marimo-server"                 # uv venv dir on remote (optional)
```

## Development

```bash
uv run pytest              # run tests
uv run ruff check src/     # lint
```

## License

MIT
