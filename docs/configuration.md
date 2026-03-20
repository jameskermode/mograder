# Configuration

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
release = "release"
submitted = "submitted"
autograded = "autograded"
feedback = "feedback"
import = "import"       # Moodle worksheets for export

[moodle]
url = "https://moodle.uni.ac.uk"  # Moodle site URL (for API commands)
course_id = 12345                  # Moodle course ID (for API commands)
csv = "moodle.csv"                 # default Moodle worksheet (for export)
match_column = "Username"
name_column = "Full name"

[https]
url = "http://localhost:8080"      # HTTPS transport server URL
token = ""                         # cached auth token

[defaults]
jobs = 4
timeout = 300
no_edit = false                    # disable "Edit" buttons in formgrader
no_actions = false                 # disable action buttons in formgrader
headless_edit = false              # open marimo edit in headless mode

[rlimits]                          # resource caps for notebook subprocesses
cpu = 600                          # CPU time limit in seconds
nproc = 64                         # max user processes
nofile = 256                       # max open file descriptors

[gradebook]
path = "gradebook.db"

[sync]
remote = "sciml"                                    # SSH host alias
remote_course_dir = "/home/svc_user/courses/es98e"  # course dir on remote
remote_venv_dir = "~/marimo-server"                 # uv venv dir on remote (optional)

[edit_links]                       # custom "Edit in ..." links for the student dashboard
molab = "https://molab.marimo.io/new/#code/{content_lz}"
```

## Section reference

### `transport`

Top-level string selecting the active transport: `"moodle"` or `"https"`. This determines which backend the student dashboard and formgrader use for fetching/submitting assignments.

### `[dirs]`

Override default directory names for the nbgrader-style layout. All paths are relative to the course directory.

### `[moodle]`

Moodle API connection settings. Required for `mograder moodle` subcommands.

### `[https]`

HTTPS transport settings. The `url` is the base URL of the assignment server.

### `[defaults]`

Default values for command-line flags: `jobs` (parallel workers), `timeout` (per-notebook), and formgrader UI options.

### `[rlimits]`

POSIX resource limits applied to notebook subprocesses during autograde. See [Security](security.md) for details.

### `[gradebook]`

Path to the SQLite gradebook file (default: `gradebook.db` in the course directory).

### `[sync]`

Settings for `mograder sync` — SSH remote host, course directory on the remote, and optional uv venv directory.

### `[edit_links]`

Custom "Edit in ..." link templates for the student dashboard. The `{content_lz}` placeholder is replaced with the lzstring-compressed notebook content.
