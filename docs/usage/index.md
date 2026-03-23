# Usage

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

1. **[`mograder generate`](generate.md)** — `source/*.py` → `release/*.py` (strip solutions, embed cell hashes)
2. **[`mograder moodle upload`](moodle.md)** — zip release files and open Moodle edit page for attachment
3. **Students** complete and submit `.py` files
4. **[`mograder validate`](validate.md)** — run a notebook in a sandbox and report check results (student self-check); warns if non-solution cells have been modified
5. **[`mograder autograde`](autograde.md)** — `submitted/*.py` → `autograded/*.py`
    - Integrity check against source notebook (detects tampered check/marks cells)
    - Runs each notebook via `marimo export html`
    - Parses check results from HTML
    - Injects verification summary + marker feedback cells
    - Stores results in `gradebook.db`
6. **Markers grade** — [formgrader](formgrader.md) Grading tab or `marimo edit`
    - Marker sets manual mark and feedback per student
    - Grades saved to `gradebook.db`
7. **[`mograder feedback`](feedback.md)** — `autograded/*.py` → `feedback/*.html`
    - Injects mark + feedback callout into existing autograde HTML
    - Removes self-assessment scores cell
8. **[`mograder moodle export`](moodle.md)** — `gradebook.db` + `worksheet.csv` → `export/`
    - Merges grades into Moodle offline grading worksheets
    - Bundles HTML feedback into a Moodle-compatible ZIP
    - Auto-imports student names into gradebook
9. **[`mograder moodle login`](moodle.md#login-obtain-api-token)** — obtain and cache a Moodle API token (supports SSO)
10. **[`mograder moodle fetch`](moodle.md#fetch-assignment-student)** / **[`mograder moodle submit`](moodle.md#submit-assignment-student)** — students fetch assignments and submit work via Moodle API
11. **[`mograder moodle fetch-submissions`](moodle.md#fetch-submissions-instructor)** / **[`mograder moodle upload-feedback`](moodle.md#upload-feedback-instructor)** — instructors bulk-download submissions and push grades/feedback via Moodle API
12. **[`mograder moodle sync`](moodle.md#sync-assignment-metadata-instructor)** — syncs assignment metadata from Moodle into `mograder.toml`
13. **[`mograder student`](student-dashboard.md)** — launches an interactive student dashboard
14. **[`mograder serve`](https-transport.md)** / **[`mograder https *`](https-transport.md)** — lightweight HTTPS server + transport for assignment distribution without Moodle
15. **[`mograder hub`](hub.md)** — multi-user hub server for browser-based assignment delivery (publish, edit, validate)
