# Hub — Multi-User Server

The **hub** provides a cloud-hosted alternative to the local `mograder student` workflow. Each student gets a persistent notebook directory and on-demand `marimo edit` sessions, all accessible through a web browser.

## Quick Start

```bash
# Set the secret (required, unless --dev)
export MOGRADER_HUB_SECRET=$(python -c "import secrets; print(secrets.token_hex(32))")

# Start the hub
mograder hub -C /path/to/course --port 8080 --headless

# Or in development mode (no auth required)
mograder hub -C /path/to/course --dev --headless
```

## Student Workflow

Students access the hub via a browser (no local install required):

### Assignments

1. Navigate to the hub URL provided by your instructor
2. Log in via university SSO (automatic via reverse proxy)
3. Click **Open**: the marimo editor opens in a new tab with your own copy (fetched from the release the first time, reopened afterwards)
4. Work on the assignment — changes are saved automatically
5. Click **Validate** to run checks and see results
6. Click **Export** to download the completed `.py` file
7. Upload the exported file to Moodle for submission
8. Click **Get latest** (after confirming) to replace your copy with the current release (your work is archived)

**Open**, **Run** and **Edit** are plain links to the deep links (`/edit/<name>`, `/run/<name>`), so the new tab opens straight from your click and is not stopped by pop-up blockers; its page starts the session. Reload the dashboard to update the status columns.

Open notebooks appear in an **Active sessions** panel (viewing or editing), with links to reopen and a **Stop** button; the dashboard checks for sessions every few seconds (**Auto-refresh**), so this panel and the status columns update without a reload.

!!! note
    The hub does not submit to Moodle directly. Students must export their
    notebook and upload to Moodle for grading.

### Lectures

If the instructor has published lectures to the hub, they appear in a **Lectures** table below the assignments:

1. Click **Run** to open the lecture in a new tab
2. The lecture runs in read-only mode with code visible (`marimo run --include-code`)
3. Each student gets their own isolated session (widget state is not shared)
4. Cross-notebook links within lectures navigate directly to other published lectures
5. Click **Edit** for your own editable copy of the lecture (deep link `/edit/<lecture>`), to change settings and explore; it is kept between visits
6. Once you have a copy, **Get latest** replaces it with the current version (after the instructor republishes a lecture, the table shows "update available"); your previous copy is kept as `<lecture>.bak.<timestamp>.py`

**Edit sessions run the notebook when they open** (as `marimo run` does), so a workshop notebook runs up to the first exercise not yet attempted. The hub sets `runtime.auto_instantiate = true` in the student's marimo user config for the notebook, unless the student has set it themselves; marimo ignores this setting in a notebook's own header.

**Your work is never overwritten.** Opening an assignment or lecture again reopens your existing copy; the release is copied only when you have none. **Get latest** (and Download, if you already have a copy) first saves your copy as `<name>.bak.<timestamp>.py` in the same folder, then fetches the release; for assignments it asks for confirmation first. The table marks copies taken before the item was last republished ("update available").

When a student's copy of an assignment or lecture is created, the release's supporting files (data, images, helper modules) are copied next to it, since edit sessions run in the student's directory. Existing files are never overwritten, and missing ones are filled in when an editor starts.

Lecture sessions are per-user and subject to the same idle timeout as assignment edit sessions.

### Deep Links

Both assignments and lectures support **shareable deep links** that can be embedded in lectures, Moodle pages, or shared directly:

| Type | Deep link URL | What it does |
|------|--------------|--------------|
| Assignment | `/edit/{assignment}` | Auto-downloads release (if needed), starts editor |
| Lecture | `/run/{lecture}` | Starts read-only run session |

Deep links show a spinner page while the session starts, then redirect to the per-user editor or viewer. If the student already has a copy of the assignment, their edits are preserved — the release is not re-downloaded.

**Try it on the live demo:** [edit demo-assignment](https://mograder-demo.jrkermode.uk/edit/demo-assignment) | [run demo-lecture](https://mograder-demo.jrkermode.uk/run/demo-lecture)

These can be used in:

- **Lecture notebooks** — `mograder generate --lecture` automatically rewrites inter-notebook links to `/run/{lecture}/` format
- **Moodle** — paste the deep link as an activity URL or in assignment instructions
- **Direct sharing** — students can bookmark or share the link

If a session is already running for the current user, the deep link reconnects to it rather than starting a new one.

## Commands

### `mograder hub`

Start the hub server. Options:

| Option | Default | Description |
|--------|---------|-------------|
| `-C`, `--course-dir` | `.` | Course directory |
| `--port` | `8080` | Server port |
| `--host` | `0.0.0.0` | Bind address |
| `--notebooks-dir` | from config | Student notebooks directory |
| `--session-ttl` | `3600` | Session idle timeout (seconds) |
| `--session-threads` | `0` | Cap each session's numerical thread pools (OpenMP, BLAS, PyTorch; JAX only at 1) at N threads. `0` keeps library defaults (one thread per core), which oversubscribes the CPU when many students compute at once |
| `--min-free-mb` | `0` | Admission control: refuse *new* sessions (HTTP 503, "the hub is busy") while available memory is below this many MB; existing sessions are unaffected. `0` disables |
| `--instructors` | | Usernames (from the proxy's user header, e.g. SSO) with the instructor role: they see every item whatever its schedule, and can **view the hub as a student** (below) |
| `--session-mb` | `0` | Admission control: memory to assume per session for items not yet measured or calibrated (see below) |
| `--trusted-header` | `X-Remote-User` | Trusted proxy header name |
| `--dev` | off | Dev mode (no auth required) |
| `--headless` | off | Don't open browser on startup |

Each option can also be set in the service environment as `MOGRADER_HUB_SESSION_TTL`, `MOGRADER_HUB_SESSION_THREADS` and `MOGRADER_HUB_MIN_FREE_MB` (an option given on the command line wins).

#### Demos

A **demo** is a run-only notebook (code hidden), opened by deep link
(`run/<name>/`, e.g. from a course web page) and never listed on the
dashboard or affected by the release schedule. Each visitor gets their own
`marimo run` process, with the hub's thread caps and admission control.
Students cannot make a copy or download a demo's source (instructors can).
Publish with `mograder hub publish <dir> --demo`, or mark the notebook with
`mograder-type = "demo"` in its PEP 723 block.

#### View as student

Like Moodle's *Switch role to…*, an instructor can see the hub exactly as a
student does: the dashboard shows **View as student now**, and **View as
student then** with an *as of* date, which evaluates the release schedule at
09:00 (Europe/London) on that day, so the schedule can be checked before
term. Permissions really drop to a student's (hidden items are hidden, deep
links refuse them) until **Back to instructor view**. The switch is a cookie
(`mograder_view_as`, 8 hours) honoured only for real instructors, so it can
only ever reduce privileges. Endpoint: `view-as?role=student[&as_of=ISO]`,
`view-as?role=` to switch back.

#### Admission control and calibration

A session starts small and grows as its notebook runs, so a check of free
memory alone admits a burst of arrivals that later runs the machine out of
memory. With `--min-free-mb` set, the hub admits a new session only if

    available memory - growth still to come in existing sessions
                     - estimate for the new session  >=  --min-free-mb

where a session's growth to come is its item's estimate minus its latest
measured memory. Estimates per item come from:

1. **Measurement.** The hub samples each session's memory (marimo process and
   kernel, as PSS, so pages shared through the venv are split between
   sessions) every 10 s and keeps each item's peak in `session_memory.json`
   in the course directory.
2. **Calibration.** `session_mb.json` in the course directory,
   `{"<item>": MB, ..., "default": MB}`, read on every admission (no
   restart). Fill it from a pre-session run, e.g. a load test of each
   workshop, with some margin.
3. `--session-mb` for items with neither.

The estimate is the larger of the measured peak and the calibrated (or
default) value, so real use during term only ever raises it.

### `mograder hub check`

Preflight check to verify hub requirements:

```bash
mograder hub check /path/to/course
```

Checks:
- `MOGRADER_HUB_SECRET` is set
- `marimo` is available
- `bwrap` (bubblewrap) is available (optional)
- Hub port is free
- Directories are configured

### `mograder hub publish`

Publish a release assignment or lecture to the hub:

```bash
# Publish assignment (verifies files match Moodle first)
mograder hub publish A1 --url $HUB_URL --token $TOKEN

# Skip Moodle verification
mograder hub publish A1 --url $HUB_URL --token $TOKEN --force

# Preview what will be published
mograder hub publish A1 --force --dry-run

# Explicit Moodle assignment name (if different from directory name)
mograder hub publish A1 --moodle-assignment "A1. Introduction" --url $HUB_URL --token $TOKEN

# Publish a lecture (auto-detected from mograder-type metadata, or use --lecture)
mograder hub publish L01-Intro --url $HUB_URL --token $TOKEN
mograder hub publish L01-Intro --lecture --url $HUB_URL --token $TOKEN
```

The `ASSIGNMENT` argument is a name (e.g. `A1-Intro-to-SciML` or prefix `A1`) resolved from the `release/` directory, or an explicit directory path.

For **assignments**, files are verified against Moodle before publishing by default — Moodle is the authoritative source for assignment content.

For **lectures**, Moodle verification is skipped automatically (lectures aren't posted to Moodle). The lecture type is auto-detected from `mograder-type = "lecture"` in the notebook's PEP 723 block (injected by `mograder generate --lecture`), or can be forced with `--lecture`.

Publishing a lecture:
1. Uploads the notebook and auxiliary files to the hub
2. Stores `"type": "lecture"` in the `files.json` manifest
3. Warms the uv cache / creates a shared `.venv` from PEP 723 dependencies

| Option | Env var | Description |
|--------|---------|-------------|
| `--url` | `MOGRADER_HUB_URL` | Hub base URL |
| `--token` | `MOGRADER_HUB_INSTRUCTOR_TOKEN` | Instructor token |
| `--moodle-assignment` | | Moodle assignment name (default: same as ASSIGNMENT) |
| `--force` | | Skip Moodle verification |
| `--lecture` | | Publish as lecture (implies `--force`) |
| `--dry-run` | | Preview only, don't publish |

### `mograder hub visibility` and `mograder hub schedule`

Control when published items become visible to students. Instructors always
see everything. For students, a hidden or not-yet-open item is left out of the
hub listing, and its deep links (`/run/<lecture>`, `/edit/<assignment>`) and
release downloads answer "Not available until …". A student who already has a
copy of an assignment keeps access to it if the item is hidden again.
Items with no setting are visible, and republishing an item keeps its setting,
so you can update a notebook without changing when it opens.

```bash
# List published items and their visibility
mograder hub visibility --ssh hub-host

# Set individual items (exact names or unique prefixes)
mograder hub visibility A3 L03 --from 2027-01-25T09:00 --ssh hub-host   # local time
mograder hub visibility A3 --hide --ssh hub-host
mograder hub visibility A3 --show --ssh hub-host

# Apply a weekly schedule (replaces all visibility settings)
mograder hub schedule schedule.toml --dry-run --ssh hub-host
mograder hub schedule schedule.toml --ssh hub-host
```

Schedule file:

```toml
start = 2027-01-11          # Monday of week 1
time = "09:00"              # opening time (default 09:00)
timezone = "Europe/London"  # default; summer time is handled
hide_unlisted = true        # hide published items that are not in the schedule

[weeks]                     # week N opens on start + 7*(N-1) days
0 = ["L00a-Probability"]
1 = ["L01-Intro", "A1-Setup"]

[items]                     # explicit dates override the weeks
"A0-Workshop" = 2027-01-08T14:00:00
```

Settings are stored in `.visibility.json` in the hub's release directory
(API: `GET`/`POST /visibility`, instructor only).

### `mograder hub warm-cache`

Pre-populate the uv cache with notebook dependencies:

```bash
# Warm cache for specific notebooks
mograder hub warm-cache release/hw1/hw1.py release/hw2/hw2.py

# Warm cache for all release notebooks
mograder hub warm-cache --all

# Dry run (show deps without installing)
mograder hub warm-cache --dry-run release/hw1/hw1.py

# Remote mode: warm cache on the hub server
mograder hub warm-cache --url $HUB_URL --token $TOKEN
```

This parses PEP 723 inline script metadata (`# /// script` blocks) to find
dependencies and runs `uv run --with <deps> python -c pass` to populate the cache.

With `--url`, sends a POST to the hub's `/warm-cache` endpoint instead of running locally.

### `mograder hub generate-token`

Generate HMAC authentication tokens:

```bash
# Generate a student token
mograder hub generate-token alice

# Generate an instructor token
mograder hub generate-token --role instructor admin
```

Requires `MOGRADER_HUB_SECRET` to be set.

## Configuration

Add a `[hub]` section to `mograder.toml`:

```toml
[hub]
port = 8080
notebooks_dir = "hub-notebooks"
release_dir = "hub-release"
session_ttl = 3600
trusted_header = "X-Remote-User"
uv_cache_dir = ""  # empty = default ~/.cache/uv
```

## Instructor Workflow

### Assignments

1. Generate release notebooks: `mograder generate A1`
2. Upload to Moodle: `mograder moodle upload A1`
3. Publish to hub: `mograder hub publish A1 --url $HUB_URL --token $TOKEN`

### Lectures

1. Generate lecture release: `mograder generate --lecture source/L01-Intro/L01-Intro.py`
2. Publish to hub: `mograder hub publish L01-Intro --url $HUB_URL --token $TOKEN`

The lecture type is auto-detected from PEP 723 metadata — no `--lecture` flag needed on publish if `generate --lecture` was used. Cache warming happens automatically during publish.

## Environment Variables

| Variable | Description |
|----------|-------------|
| `MOGRADER_HUB_SECRET` | HMAC secret for session/token signing (required unless `--dev`) |
| `MOGRADER_HUB_URL` | Hub base URL (for `publish` and `warm-cache` commands) |
| `MOGRADER_HUB_INSTRUCTOR_TOKEN` | Instructor token (for `publish`, `warm-cache`, `visibility` and `schedule`) |
| `MOGRADER_HUB_SSH` | SSH host for the `--ssh` tunnel |
| `MOGRADER_HUB_SSH_OPTIONS` | Extra `ssh` options for the tunnel, e.g. `-o ProxyJump=none` to bypass a jump host |

## API Endpoints

### Deep Links (shareable)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/edit/{assignment}` | Spinner → auto-download + start edit session |
| GET | `/run/{lecture}` | Spinner → start run session |

### Assignments (per-user)

| Method | Path | Description |
|--------|------|-------------|
| POST | `/start-edit-deep/{assignment}` | Auto-download release + start edit (used by spinner) |
| POST | `/start-edit/{user}/{assignment}` | Start edit session (notebook must exist) |
| POST | `/stop-edit/{user}/{assignment}` | Stop edit session |
| POST | `/upload/{user}/{assignment}` | Upload a notebook |
| GET | `/export/{user}/{assignment}` | Download a notebook |
| POST | `/validate/{user}/{assignment}` | Run validation checks |
| POST | `/reset/{user}/{assignment}` | Reset to release version |
| GET | `/status/{user}/{assignment}` | Get assignment status |
| POST | `/mark-exported/{user}/{assignment}` | Mark as exported |
| `*` | `/edit/user/{user}/{assignment}/...` | Proxy to marimo editor |

### Lectures (per-user)

| Method | Path | Description |
|--------|------|-------------|
| POST | `/start-run/{lecture}` | Start per-user marimo run session |
| `*` | `/run/user/{user}/{lecture}/...` | Proxy to marimo run session |

### Shared

| Method | Path | Description |
|--------|------|-------------|
| GET | `/assignments` | List assignments and lectures (with `type` field) |
| GET | `/sessions` | List active sessions (with `type` field) |
| GET | `/release/{name}/{filename}` | Download release file |
| POST | `/publish/{name}` | Publish release (instructor); `?type=lecture` for lectures |
| POST | `/warm-cache` | Warm uv cache (instructor) |
| GET | `/visibility` | Visibility settings (instructor) |
| POST | `/visibility` | Set visibility: `{"items": {name: {"visible_from": iso} \| {"hidden": true} \| {}}, "replace": false}` (instructor) |

## Authentication

The hub supports multiple authentication methods (checked in order):

1. **Session cookies** — Set after first successful authentication
2. **Trusted proxy header** — `X-Remote-User` from trusted proxy IPs (e.g., university SSO)
3. **Bearer tokens** — HMAC-SHA256 tokens for API access
4. **Dev mode** — No authentication (for local development)

## Security

- **Path traversal hardening** — All file paths are validated against base directories
- **AST safety scanner** — Uploaded code is checked for dangerous patterns (denied imports, builtins)
- **Bubblewrap** (optional) — Filesystem isolation for marimo edit sessions
- **Session isolation** — Each student can only access their own sessions
- **Instructor bypass** — Instructors can access any student's resources
