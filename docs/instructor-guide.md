# Instructor Quickstart

A step-by-step guide to setting up and grading your first assignment with mograder.

## 1. Install mograder

```bash
pip install mograder
# or run without installing:
uvx mograder --help
```

## 2. Set up the course directory

Create the standard directory structure:

```
my-course/
  mograder.toml              # configuration (optional)
  source/
    hw1/
      hw1.py                 # source notebook (with solutions)
  release/                   # generated (solutions stripped)
  submitted/                 # student submissions
  autograded/                # autograde output
  feedback/                  # HTML feedback
```

A minimal `mograder.toml`:

```toml
[defaults]
jobs = 4
timeout = 300
```

See [Configuration](configuration.md) for all options.

## 3. Write a source notebook

Create a notebook with `marimo edit source/hw1/hw1.py`. Source notebooks are standard marimo notebooks with three conventions:

### PEP 723 dependencies

Add a metadata block at the top so dependencies install automatically:

```python
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "marimo",
#     "numpy",
#     "mograder",
# ]
# ///
```

### Solution markers

Wrap model solutions in `### BEGIN SOLUTION` / `### END SOLUTION`. When you run `mograder generate`, these are replaced with `# YOUR CODE HERE` and `pass`:

```python
@app.cell
def _(np):
    x = None
    y = None
    ### BEGIN SOLUTION
    x = np.linspace(0, 2 * np.pi, 50)
    y = np.sin(x)
    ### END SOLUTION
    return x, y
```

For written-response cells, assign to `response_text` inside a solution block. The release version is automatically converted to an editable `mo.md()` block:

```python
@app.cell
def _(mo):
    response_text = "*Write your analysis here...*"
    ### BEGIN SOLUTION
    response_text = r"""
    The finite difference method approximates derivatives using nearby
    function values. Central differences achieve second-order accuracy...
    """
    ### END SOLUTION
    mo.md(response_text)
    return (response_text,)
```

### Autograding checks

Import `check` from `mograder.runtime` and call it with a label and a list of `(condition, failure_message)` tuples:

```python
from mograder.runtime import check

check(
    "Q1: Array creation",
    [
        (x.shape == (50,), f"x should have shape (50,), got {x.shape}"),
        (abs(x[0]) < 1e-10, "x should start at 0"),
    ],
)
```

Use `mo.stop()` with an empty-checks call for a "waiting" state before the student has written code:

```python
@app.cell(hide_code=True)
def _(check, mo, x):
    mo.stop(x is None, check("Q1: Array creation", []))
    check("Q1: Array creation", [
        (x.shape == (50,), f"x should have shape (50,), got {x.shape}"),
    ])
    return
```

### Choosing a grading mode

**Holistic mode** (single 0-100 mark assigned by a GTA):

```python
from mograder.runtime import check
```

**Per-question marks** (auto + manual):

```python
from mograder.runtime import Grader

# === MOGRADER: MARKS ===
_marks = {"Q1": 10, "Q2": 15, "Analysis": 60}
grader = Grader(mo, _marks)
check = grader.check
```

Questions matching a `check()` label are auto-scored with **partial credit**: marks are proportional to the weight of passing checks. Each check tuple can optionally include a weight as a third element (default 1):

```python
check("Q2: Finite differences", [
    (isinstance(dydx, np.ndarray), "result should be ndarray"),       # weight 1
    (dydx.shape == x.shape, "shape should match"),                    # weight 1
    (np.max(np.abs(dydx - np.cos(x))) < 0.05, "max error < 0.05", 3),  # weight 3
])
# If only the first two pass: earned = round(15 * 2/5, 1) = 6.0/15
```

The question key is the text before the first colon in the label, so `check("Q1: Array creation", [...])` maps to `"Q1"`. Questions without a matching check (e.g. `"Analysis"`) are scored manually by the GTA.

Call `grader.scores()` in a cell to display a reactive score table (including fractional marks for partial credit).

## 4. Generate the release notebook

Strip solutions and embed integrity hashes:

```bash
mograder generate hw1
```

This creates `release/hw1/hw1.py` with solutions removed and cell hashes embedded. Use `--dry-run` to preview, `--validate` to check markers only.

## 5. Distribute to students

=== "Moodle"

    ```bash
    mograder moodle upload "HW1"
    ```

=== "HTTPS server"

    ```bash
    mograder serve release/ --enrollment-code "my-secret-phrase"
    ```

=== "Manual"

    Share the `release/hw1/` directory.

## 6. Collect submissions

=== "From Moodle"

    ```bash
    mograder moodle fetch-submissions "HW1" -o submitted/hw1/
    ```

=== "From HTTPS server"

    Submissions are stored automatically in `submitted/`.

=== "Manual"

    Place student `.py` files in `submitted/hw1/` named by username (e.g. `alice.py`).

## 7. Autograde

```bash
mograder autograde hw1
```

This:

1. Auto-discovers the source notebook in `source/hw1/`
2. Checks submission integrity against the source (detects tampered cells)
3. Executes each notebook via `marimo export html`
4. Parses check results from the output
5. Injects grading cells (verification summary + GTA feedback placeholders)
6. Writes results to `gradebook.db`
7. Saves grading copies to `autograded/hw1/`

Options:

- `-j 8` — parallel workers (default: 4)
- `--timeout 600` — per-notebook timeout (default: 300s)
- `--safety-check` — scan for dangerous code before execution
- `--max-memory 2048` — memory limit in MB
- `--force` — re-grade all even if output is up to date

## 8. Manual grading with the formgrader

```bash
mograder formgrader my-course/
```

This opens a marimo web app with four tabs:

- **Assignments** — overview with pipeline status and action buttons
- **Submissions** — per-student status with marks breakdown
- **Grading** — navigate between students, set marks and feedback
- **Students** — cross-assignment marks table

For a persistent server deployment:

```bash
mograder formgrader-asgi my-course/ --host 0.0.0.0 --port 2718
```

## 9. Export feedback

```bash
mograder feedback hw1
```

This exports graded notebooks to HTML in `feedback/hw1/`, injecting the GTA's mark and feedback as a callout.

## 10. Upload grades

=== "Moodle"

    ```bash
    mograder moodle export "HW1" -o export/
    mograder moodle upload-feedback "HW1"
    ```

=== "HTTPS server"

    Grades are stored in the server automatically.

## Worked example

The `examples/` directory in the mograder repository contains two complete example assignments:

- `examples/source/demo-assignment/` — per-question marks (numerical methods)
- `examples/source/demo-holistic/` — holistic grading (string processing)

Try the full workflow:

```bash
cd examples
mograder generate demo-assignment demo-holistic
mograder autograde demo-assignment
mograder feedback demo-assignment
```

## Next steps

- [Grader API Reference](reference/runtime.md) — detailed documentation of `check()`, `Grader`, and `hint()`
- [Security](security.md) — threat model and hardening options for autograde
- [Student Setup Guide](student-guide.md) — share this with your students
- [Configuration](configuration.md) — full `mograder.toml` reference
