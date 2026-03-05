# mograder

Semi-automated grading for [Marimo](https://marimo.io) notebooks.

mograder is the Marimo equivalent of [nbgrader](https://nbgrader.readthedocs.io/). Coding exercises support optional per-question marks via `Grader` (auto-scored pass/fail), while written analysis sections are graded by a GTA. Without per-question marks, a single holistic mark (0-100) is assigned.

## Try it

[![Open in marimo](https://marimo.io/shield.svg)](https://molab.marimo.io/github/jameskermode/mograder/blob/main/examples/release/demo-assignment/demo-assignment.py)

## Directory convention

mograder follows [nbgrader's terminology](https://nbgrader.readthedocs.io/en/latest/user_guide/philosophy.html): **source** → **release** → **submitted** → **autograded** → **feedback**.

```
course/
  source/
    assignment-name/
      assignment-name.py   ← source notebook (with solutions)
      data.csv             ← auxiliary files (copied to release)
  release/
    assignment-name/
      assignment-name.py   ← generated (solutions stripped)
      data.csv             ← copied from source
  submitted/
    assignment-name/
      student1.py          ← student submissions
  autograded/
    assignment-name/
      student1.py          ← output of mograder autograde
  feedback/
    assignment-name/
      student1.html        ← output of mograder feedback
```

## Workflow

```
1. mograder generate   ──→  source/*.py  →  release/*.py  (strip solutions)
2. Students complete and submit .py files
3. mograder autograde  ──→  submitted/*.py  →  autograded/*.py
   - Integrity check against source notebook (detects tampered check/marks cells)
   - Runs each notebook via `marimo export html`
   - Parses check results from HTML
   - Injects verification summary + GTA feedback cells
4. GTAs grade          ──→  marimo edit autograded/student.py
   - GTA sets _mark and writes _feedback, then saves
5. mograder feedback   ──→  autograded/*.py  →  feedback/*.html
   - Exports graded notebooks to standalone HTML
   - Aggregates marks into CSV
6. mograder moodle     ──→  grades.csv + worksheet.csv  →  export/
   - Merges grades into Moodle offline grading worksheets
   - Optionally bundles HTML feedback into a Moodle-compatible ZIP
```

## Installation

```bash
git clone https://github.com/jameskermode/mograder.git
cd mograder
uv venv && uv pip install -e ".[dev]"
```

## Usage

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

When `--source` is provided (or auto-discovered from a sibling `source/` directory), mograder performs an integrity check — tampered check cells or marks definitions are reinjected from the source before execution.

### Export feedback

Export graded notebooks to HTML and aggregate marks:

```bash
mograder feedback autograded/hw1/*.py -o feedback/hw1/
mograder feedback autograded/hw1/*.py --grades-csv grades.csv
```

### Upload to Moodle

Merge grades into a Moodle offline grading worksheet and bundle feedback:

```bash
mograder moodle worksheet.csv --grades-csv grades.csv -o export/
mograder moodle worksheet.csv --grades-csv grades.csv --feedback-dir feedback/ -o export/
```

## Development

```bash
uv run pytest              # run tests
uv run ruff check src/     # lint
```

## License

MIT
