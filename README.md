# mograder

Semi-automated grading for [Marimo](https://marimo.io) notebooks.

mograder is the Marimo equivalent of [nbgrader](https://nbgrader.readthedocs.io/). Coding exercises support optional per-question marks via `Grader` (auto-scored pass/fail), while written analysis sections are graded by a GTA. Without per-question marks, a single holistic mark (0-100) is assigned.

## Try it

[![Open in marimo](https://marimo.io/shield.svg)](https://molab.marimo.io/github/jameskermode/mograder/blob/main/examples/release/demo-assignment/demo-assignment.py)

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
6. **`mograder moodle`** — `gradebook.db` + `worksheet.csv` → `export/`
   - Merges grades into Moodle offline grading worksheets
   - Bundles HTML feedback into a Moodle-compatible ZIP
   - Auto-imports student names into gradebook

## Installation

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

### Upload to Moodle

Merge grades into a Moodle offline grading worksheet and bundle feedback:

```bash
mograder moodle worksheet.csv -o export/
mograder moodle worksheet.csv --feedback-dir feedback/ -o export/
mograder moodle worksheet.csv --grades-csv grades.csv -o export/   # manual CSV instead of gradebook
```

Grades are read from `gradebook.db` by default. The match column and name column can be configured in `mograder.toml` (see [Configuration](#configuration)). Student names are auto-imported into the gradebook when the moodle command runs.

## Configuration

Create `mograder.toml` in the course directory to customise settings:

```toml
[dirs]
source = "source"       # default directory names
import = "import"       # Moodle worksheets for export

[moodle]
csv = "moodle.csv"      # default Moodle worksheet
match_column = "Username"
name_column = "Full name"

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
