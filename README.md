# mograder

Semi-automated grading for [Marimo](https://marimo.io) notebooks.

mograder is the Marimo equivalent of [nbgrader](https://nbgrader.readthedocs.io/). Coding exercises support optional per-question marks via `Grader` (auto-scored pass/fail), while written analysis sections are graded by a GTA. Without per-question marks, a single holistic mark (0-100) is assigned.

## Try it

[![Open in marimo](https://marimo.io/shield.svg)](https://molab.marimo.io/github/jameskermode/mograder/blob/main/examples/release/demo-assignment.py)

## Workflow

```
1. mograder generate   ──→  staff.py  →  student.py  (strip solutions)
2. Students complete and submit .py files
3. mograder autograde  ──→  submissions/*.py  →  grading/*.py
   - Runs each notebook via `marimo export html`
   - Parses check results from HTML
   - Injects verification summary + GTA feedback cells
4. GTAs grade          ──→  marimo edit grading/student.py
   - GTA sets _mark and writes _feedback, then saves
5. mograder feedback   ──→  grading/*.py  →  feedback/*.html
   - Exports graded notebooks to standalone HTML
   - Aggregates marks into CSV
```

## Installation

```bash
git clone https://github.com/jameskermode/mograder.git
cd mograder
uv venv && uv pip install -e ".[dev]"
```

## Usage

### Generate student notebooks

Strip solution blocks from staff notebooks:

```bash
mograder generate staff_notebook.py -o release/
mograder generate staff_notebook.py --dry-run    # preview only
mograder generate staff_notebook.py --validate   # check markers only
```

Staff notebooks use markers to delimit solutions:

```python
### BEGIN SOLUTION
x = 42
### END SOLUTION
```

Solution blocks are replaced with `# YOUR CODE HERE` / `pass` in the student version. Notebooks import `check()` from `mograder.runtime` for formative feedback, or use `Grader` for per-question marks with reactive score tracking.

### Autograde submissions

Run student notebooks and prepare grading copies with injected feedback cells:

```bash
mograder autograde submissions/*.py -o grading/
mograder autograde submissions/*.py --staff staff.py --csv results.csv
mograder autograde submissions/*.py -j 8 --timeout 600
```

### Export feedback

Export graded notebooks to HTML and aggregate marks:

```bash
mograder feedback grading/*.py -o feedback/
mograder feedback grading/*.py --grades-csv grades.csv
```

## Development

```bash
uv run pytest              # run tests
uv run ruff check src/     # lint
```

## License

MIT
