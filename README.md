# mograder

Semi-automated grading for [Marimo](https://marimo.io) notebooks.

mograder asprises to become a Marimo equivalent of [nbgrader](https://nbgrader.readthedocs.io/). It doesn't yet have full feature parity but should already be useable. mograder has been developed based on my experiences teaching computational modelling and machine learning with Jupyter and nbgrader in [HetSys CDT](https://warwick.ac.uk/fac/sci/hetsys/) and the [Predictive Modelling and Scientific Computing MSc course](https://warwick.ac.uk/study/postgraduate/courses/pga-pgcert-pgdip-msc-predictive-modelling-scientific-computing/), both at the University of Warwick, so it is an personal and opinionated take on the ngrader workflow which may or may not suit other users!

Three modes of operation are supported:
- **Workshop mode** which is fully formative (i.e. no marks are assigned). Model solutions can be unlocked automatically by students when they pass automated tests. Solutions can also be released one by one by an instructor from a web dashboard, allowing 'un-sticking' of students during a live workshop.
- **Manual grading** of a single holistic mark. Instance formative feedbck is available to students on coding questions, while reflective interpretation is manually graded.
- **Hybrid grading** Automated per-question marks on coding exericies, plus a single mark for the reflective component.

Two transports are currently availble: Moodle integration, and HTTPS transport for standalone usage.

Thanks to Marimo's WASM support, notebooks with dependendencies which are [Pyodide comptabile](https://pyodide.com/what-python-packages-are-available-in-pyodide/) can be deployed as a standalone HTML file which runs entirely in students' browsers with no need for a server. It is also possible to run notebooks on [MoLab](https://molab.marimo.io/), which allows for full dependencies, to run your own [Marimo edit server]. Thanks to Marimo's [UV](https://docs.astral.sh/uv/) integration and support for [PEP 723](https://peps.python.org/pep-0723/) script dependencies (`--sandbox` mode) which automatically installs notebooks dependencies in an isolated environment, it is also [straightforward for students](docs/student-setup.md) to install and run themselves locally.

## Try it

A live demo is available with three components:

1. **[Student Dashboard](https://jameskermode.github.io/mograder/?server=https://mograder-demo.jrkermode.uk&wasm_base=notebooks)** — WASM app hosted on GitHub Pages. Lists assignments and links to self-hosted WASM notebooks for editing in the browser.
2. **[Formgrader + Assignment Server](https://mograder-demo.jrkermode.uk)** — Combined ASGI app. The formgrader UI shows the full grading workflow (assignments, submissions, grading, students tabs) with pre-populated demo data. The same service also handles the assignment API at `/assignments`. No login required (for a real server, token-based authentication should be used, described below).
3. **Notebook Editor** — Click "Edit in Browser" in the dashboard to open a notebook as a standalone WASM app with full edit mode or "Edit in Molab" to open a full editor. Each notebook has a submit cell to send your work back to the demonstration assignment server.

There is also a **[Demo Workshop](https://jameskermode.github.io/mograder/notebooks/demo-workshop.html)** which is a WASM notebook demonstrating hints and encrypted solutions for formative workshops. The **[Instructor Dashboard](https://mograder-demo.jrkermode.uk/dashboard.html#token=mograder-demo-secret)** controls which model solutions are visible to students.

A demonstration **[GitHub Codespaces](https://codespaces.new/jameskermode/mograder)** shows how to open this repo in a Codespace for a full development environment with uv, marimo, and the student dashboard pre-configured. Assignments are served from the demo server.

## For students

See the [Student Setup Guide](docs/student-setup.md) for full instructions.

**Quick start** (macOS/Linux — just 2 commands):
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
uvx mograder student <CONFIG_URL>
```

**Or open in [GitHub Codespaces](docs/student-setup.md#option-2-github-codespaces)** — one click, no install needed.

## Directory Convention

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
```

## Workflow

1. **`mograder generate`** — `source/*.py` → `release/*.py` (strip solutions)
2. **`mograder moodle upload`** — zip release files and open Moodle edit page for attachment
3. **Students** complete and submit `.py` files
4. **`mograder validate`** — run a notebook in a sandbox and report check results (student self-check)
5. **`mograder autograde`** — `submitted/*.py` → `autograded/*.py`
   - Integrity check against source notebook (detects tampered check/marks cells)
   - Runs each notebook via `marimo export html`
   - Parses check results from HTML
   - Injects verification summary + GTA feedback cells
   - Stores results in `gradebook.db`
6. **GTAs grade** — formgrader Grading tab or `marimo edit`
   - GTA sets manual mark and feedback per student
   - Grades saved to `gradebook.db`
7. **`mograder feedback`** — `autograded/*.py` → `feedback/*.html`
   - Injects mark + feedback callout into existing autograde HTML
   - Removes self-assessment scores cell
8. **`mograder moodle export`** — `gradebook.db` + `worksheet.csv` → `export/`
   - Merges grades into Moodle offline grading worksheets
   - Bundles HTML feedback into a Moodle-compatible ZIP
   - Auto-imports student names into gradebook
9. **`mograder moodle login`** — obtain and cache a Moodle API token (supports SSO)
10. **`mograder moodle fetch`** / **`mograder moodle submit`** — students fetch assignments and submit work via Moodle API
11. **`mograder moodle fetch-submissions`** / **`mograder moodle upload-feedback`** — instructors bulk-download submissions and push grades/feedback via Moodle API
12. **`mograder moodle sync`** — syncs assignment metadata from Moodle into `mograder.toml` (instructor runs this, students get the config via URL or file)
13. **`mograder student`** — launches an interactive student dashboard (Marimo app) for downloading, validating, editing, and submitting assignments
14. **`mograder serve`** / **`mograder https *`** — lightweight HTTPS server + transport for assignment distribution without Moodle (HMAC token auth, atomic timestamped submissions)

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
mograder generate hw1                             # by assignment name
mograder generate source/hw1/hw1.py -o release/   # by file path
mograder generate hw1 --dry-run                   # preview only
mograder generate hw1 --validate                  # check markers only
```

Arguments without `/` or `.py` suffix are treated as assignment names and resolved to files in the source directory.

Source notebooks use markers to delimit solutions:

```python
### BEGIN SOLUTION
x = 42
### END SOLUTION
```

Solution blocks are replaced with `# YOUR CODE HERE` / `pass` in the release version. Auxiliary files (data, helper modules) are automatically copied from the source directory. Notebooks import `check()` from `mograder.runtime` for formative feedback, or use `Grader` for per-question marks with reactive score tracking.

### Hints

Use `hint()` in notebooks to provide progressive hints as collapsed accordions:

```python
from mograder.runtime import hint

# Single hint — accordion label is "Hint"
hint("Think about what preserves insertion order")

# Multiple hints — numbered "Hint 1", "Hint 2", ...
hint(
    "Think about which data structure preserves insertion order",
    "Consider using `collections.OrderedDict`",
    "Use `OrderedDict.move_to_end()`"
)
```

### Workshop notebooks with encrypted solutions

For formative workshops (ungraded, deployed as WASM on GitHub Pages), mograder supports encrypted solutions with two reveal mechanisms:

- **Auto-reveal on check pass** — when a student's `check()` passes and they've entered the workshop key, the model solution appears automatically below the check result
- **Instructor release** — the instructor can release solutions progressively during a live workshop via `keys.json`; students click "Check for released solutions" to fetch them

The workshop key is a secret shared verbally by the instructor during the session. It is not stored in the generated notebook (only a SHA-256 hash is embedded), so students cannot extract solutions from the source code.

**1. Author a source notebook** with a `# === MOGRADER: EXERCISES ===` cell listing exercise keys, alongside regular `### BEGIN/END SOLUTION` markers, `check()` calls, and optionally `hint()` for progressive hints:

```python
# === MOGRADER: EXERCISES ===
_exercises = ["Q1", "Q2"]
```

**2. Generate the workshop notebook** — encrypts solutions, strips them, and injects solution-reveal cells. The command prints the workshop key for the instructor to share verbally:

```bash
mograder workshop encrypt source/workshop/workshop.py -o release/workshop/ --salt mykey
# Workshop key (share with students verbally): mykey
```

**3. Export for WASM deployment** — generates HTML + keys.json for GitHub Pages:

```bash
mograder workshop export source/workshop/workshop.py -o dist/workshop/ --salt mykey
```

**4. Release solutions during a live workshop** — incrementally reveal solutions by adding decryption keys to `keys.json`:

```bash
mograder workshop release-key dist/workshop/keys.json Q1 --salt mykey
```

Students click "Check for released solutions" in the notebook to fetch updated keys. Released solutions appear regardless of whether checks pass or the workshop key has been entered. To release all solutions at once, copy `keys_all.json` over `keys.json`.

### Validate a notebook

Run a notebook in a sandbox and report check results (useful for students to self-check before submitting):

```bash
mograder validate hw1.py
mograder validate hw1.py --timeout 600
```

Installs dependencies in a sandbox, executes the notebook, and prints PASS/FAIL for each check. Exits with code 1 if any check fails. An HTML report is saved alongside the notebook.

### Autograde submissions

Run student notebooks and prepare grading copies with injected feedback cells:

```bash
mograder autograde hw1                            # by assignment name
mograder autograde submitted/hw1/*.py -o autograded/hw1/
mograder autograde submitted/hw1/*.py --source source/hw1/hw1.py --csv results.csv
mograder autograde hw1 -j 8 --timeout 600
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
mograder feedback hw1                             # by assignment name
mograder feedback autograded/hw1/*.py -o feedback/hw1/
mograder feedback hw1 --grades-csv grades.csv
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

#### Upload release files (instructor)

Zip release files and open the Moodle assignment edit page for manual attachment:

```bash
mograder moodle upload "HW1"                    # auto-discovers from release/HW1/
mograder moodle upload "HW1" file1.py data.csv  # explicit files
mograder moodle upload "HW1" --dry-run          # preview without creating zip
mograder moodle upload "HW1" --no-open          # create zip without opening browser
```

Files are zipped into `<assignment>.zip` in the current directory. If no files are given, all files in `release/<assignment>/` are included. The Moodle assignment edit page is opened automatically so you can attach the zip as an introattachment.

#### Upload feedback (instructor)

Push grades and feedback to Moodle via the API:

```bash
mograder moodle upload-feedback "HW1"                          # from gradebook.db
mograder moodle upload-feedback "HW1" --dry-run                # preview without pushing
mograder moodle upload-feedback "HW1" --grades-csv grades.csv  # from CSV
mograder moodle upload-feedback "HW1" --feedback-dir feedback/HW1/  # with HTML feedback files
mograder moodle upload-feedback "HW1" --workflow-state released     # make grades visible immediately
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

#### Login (obtain API token)

Obtain and cache a Moodle API token for subsequent commands:

```bash
mograder moodle login                    # username/password prompt
mograder moodle login --sso              # browser-based SSO (CAS/SAML/Shibboleth)
mograder moodle login --url https://moodle.uni.ac.uk
```

The token is cached at `~/.config/mograder/token.json`. For SSO sites, `--sso` opens the Moodle Security Keys page in your browser where you can copy the token.

All Moodle API commands accept `--url` and `--token` flags, or read from `MOGRADER_MOODLE_URL` / `MOGRADER_MOODLE_TOKEN` environment variables, or from the `[moodle]` section in `mograder.toml`.

### HTTPS transport (Moodle-free alternative)

mograder includes a lightweight HTTP server and transport for distributing assignments without Moodle. This is useful for courses that don't use Moodle, for local testing, or as a simple course server on platforms like Molab.

#### Start an assignment server

```bash
mograder serve course/release/        # serve assignment files
mograder serve course/release/ -p 9000  # custom port
```

The server auto-discovers assignments from the directory structure. Each subdirectory with a `files/` subfolder becomes an assignment. You can also provide a manual `assignments.json` manifest.

#### Authentication

Authentication is enabled by default. The server generates a secret (`.mograder-secret`) on first start and uses HMAC-SHA256 tokens in the format `username:hmac_hex`.

**Student self-registration** (recommended): Set an enrollment code so students can register themselves via the student dashboard or API:

```bash
mograder serve course/release/ --enrollment-code "my-course-phrase"
# or via environment variable:
MOGRADER_ENROLLMENT_CODE="my-course-phrase" mograder serve course/release/
# or from a file:
mograder serve course/release/ --enrollment-code-file enrollment.txt
```

Students enter their username + enrollment code in the dashboard to receive a personal token. The enrollment code can be shared in class or via LMS — it is separate from the HMAC secret.

**Generate tokens manually** (alternative): Use `mograder token` to generate tokens directly:

```bash
mograder token alice bob carol                      # reads .mograder-secret from CWD
mograder token --secret-file path/to/.mograder-secret alice bob
ssh server "cat /path/.mograder-secret" | mograder token --secret-stdin alice bob
```

Or from the `serve` command with a file of usernames (one per line):

```bash
mograder serve course/release/ --generate-tokens students.txt
```

Disable auth for local testing with `--no-auth`.

**Token roles:**
- **Student tokens** — can list/download assignments, submit own work, check own status
- **Instructor token** — full access: list submissions, download any submission, upload grades

#### Student commands

Students register via the student dashboard (enter username + enrollment code), or cache a token manually:

```bash
mograder https login --token <YOUR_TOKEN> --url https://server.example.com
mograder https fetch --list                              # list assignments
mograder https fetch "hw1" -o hw1/                       # download files
mograder https submit "hw1" hw1.py                       # submit work
mograder https feedback "hw1"                            # check status/grade
```

The URL and token can also be passed explicitly with `--url` and `--token` flags.

#### Instructor commands

```bash
mograder https fetch-submissions "hw1" --url https://server.example.com --token <INSTRUCTOR_TOKEN> -o submitted/hw1/
mograder https upload-grades "hw1" --url https://server.example.com --token <INSTRUCTOR_TOKEN> --grades-csv grades.csv
```

The URL can also be set in `mograder.toml`:

```toml
transport = "https"

[https]
url = "https://server.example.com"
```

#### Server directory structure

```
server_root/
  .mograder-secret                    # HMAC secret (auto-generated)
  assignments.json                    # optional manifest
  hw1/
    files/
      homework.py                     # assignment files
    grades.json                       # uploaded grades

submitted/                            # submission storage (configurable)
  hw1/
    alice_20260310T200800.py          # timestamped submissions
    alice.py -> alice_20260310T200800.py  # symlink to latest
```

Submissions are written atomically with timestamped filenames, preserving history across resubmissions. A symlink `<user>.py` always points to the latest version.

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

- **Login** — for Moodle courses, paste your Moodle security token (from your Moodle Security Keys page). For HTTPS transport courses, register with your username and the enrollment code provided by your instructor (or paste a token directly). Tokens are cached at `~/.config/mograder/`.
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
