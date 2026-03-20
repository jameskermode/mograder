# HTTPS Transport (Moodle-free Alternative)

mograder includes a lightweight HTTP server and transport for distributing assignments without Moodle. This is useful for courses that don't use Moodle, for local testing, or as a simple course server on platforms like Molab.

## Start an assignment server

```bash
mograder serve course/release/        # serve assignment files
mograder serve course/release/ -p 9000  # custom port
```

The server auto-discovers assignments from the directory structure. Each subdirectory with a `files/` subfolder becomes an assignment. You can also provide a manual `assignments.json` manifest. Use `--release-dir` to serve files from a flat `release/<assignment>/<file>` layout instead of requiring a `files/` subdirectory.

## Authentication

Authentication is enabled by default. The server generates a secret (`.mograder-secret`) on first start and uses HMAC-SHA256 tokens in the format `username:hmac_hex`.

### Student self-registration (recommended)

Set an enrollment code so students can register themselves via the student dashboard or API:

```bash
mograder serve course/release/ --enrollment-code "my-course-phrase"
# or via environment variable:
MOGRADER_ENROLLMENT_CODE="my-course-phrase" mograder serve course/release/
# or from a file:
mograder serve course/release/ --enrollment-code-file enrollment.txt
```

Students enter their username + enrollment code in the dashboard to receive a personal token. The enrollment code can be shared in class or via LMS — it is separate from the HMAC secret.

### Generate tokens manually (alternative)

Use `mograder token` to generate tokens directly:

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

### Token roles

- **Student tokens** — can list/download assignments, submit own work, check own status
- **Instructor token** — full access: list submissions, download any submission, upload grades

## Student commands

Students register via the student dashboard (enter username + enrollment code), or cache a token manually:

```bash
mograder https login --token <YOUR_TOKEN> --url https://server.example.com
mograder https fetch --list                              # list assignments
mograder https fetch "hw1" -o hw1/                       # download files
mograder https submit "hw1" hw1.py                       # submit work
mograder https feedback "hw1"                            # check status/grade
```

The URL and token can also be passed explicitly with `--url` and `--token` flags.

## Instructor commands

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

## Server directory structure

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
