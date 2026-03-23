# Writing Source Notebooks

Source notebooks are standard [Marimo](https://marimo.io) notebooks (`.py` files) with a few conventions for marking solutions and autograding checks. Create them with `marimo edit` and place them in `source/<assignment>/<assignment>.py`.

## Solution markers

Wrap model solutions in `### BEGIN SOLUTION` / `### END SOLUTION` markers. When you run `mograder generate`, these blocks are replaced with `# YOUR CODE HERE` and `pass` in the release version:

```python
@app.cell
def _(np):
    def finite_diff(x, y):
        ### BEGIN SOLUTION
        dydx = np.zeros_like(y)
        dydx[0] = (y[1] - y[0]) / (x[1] - x[0])
        dydx[-1] = (y[-1] - y[-2]) / (x[-1] - x[-2])
        dydx[1:-1] = (y[2:] - y[:-2]) / (x[2:] - x[:-2])
        ### END SOLUTION
        return dydx

    return (finite_diff,)
```

For written-response cells, assign the model answer to `response_text` inside a solution block. The generated release version is automatically converted to an editable `mo.md()` block for the student:

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

## Autograding checks

Import `check` from `mograder.runtime` and call it with a label and a list of `(condition, failure_message)` tuples. Each tuple can optionally include a weight as a third element (default 1). The result is a coloured callout that gives students instant feedback:

```python
from mograder.runtime import check

check(
    "Q1: Palindrome checker",
    [
        (is_palindrome("racecar") is True, 'is_palindrome("racecar") should be True'),
        (is_palindrome("hello") is False, 'is_palindrome("hello") should be False'),
    ],
)
```

Use `mo.stop()` with an empty-checks call to show an amber "waiting" state before the student has written any code:

```python
@app.cell(hide_code=True)
def _(check, mo, x):
    mo.stop(x is None, check("Q1: Array creation", []))
    check("Q1: Array creation", [
        (x.shape == (50,), f"x should have shape (50,), got {x.shape}"),
    ])
    return
```

## Holistic vs per-question marks

**Holistic mode** (single mark 0-100, assigned by a marker): import the standalone `check` function. This is suited to notebooks where coding questions provide formative feedback only and a marker assigns one overall mark:

```python
from mograder.runtime import check
```

**Per-question marks** (automatic + manual): use the `Grader` class with a marks dictionary. Questions matching a `check()` label are auto-scored with **partial credit**: marks are proportional to the weight of passing checks. Questions without a matching check (e.g. written analysis) are scored manually by the marker:

```python
from mograder.runtime import Grader

# === MOGRADER: MARKS ===
_marks = {"Q1": 10, "Q2": 15, "Analysis": 60}
grader = Grader(_marks)
check = grader.check
```

Each check tuple can optionally include a weight as a third element (default weight is 1). Earned marks are `round(available * earned_weight / total_weight, 1)`:

```python
check("Q2: Finite differences", [
    (isinstance(dydx, np.ndarray), "result should be ndarray"),       # weight 1
    (dydx.shape == x.shape, "shape should match"),                    # weight 1
    (np.max(np.abs(dydx - np.cos(x))) < 0.05, "max error < 0.05", 3),  # weight 3
])
# If only the first two pass: earned = round(15 * 2/5, 1) = 6.0/15
```

The question key is the text before the first colon in the check label, so `check("Q1: Array creation", [...])` maps to the `"Q1"` entry. Call `grader.scores()` in a cell to display a reactive score table showing earned/available marks (including fractional values for partial credit).

## Hidden tests

You can include checks that are visible to instructors but hidden from students. Wrap them in `### BEGIN HIDDEN TESTS` / `### END HIDDEN TESTS` markers. During `mograder generate`, these blocks are replaced with a `# HIDDEN TESTS` placeholder comment. During `mograder autograde`, the hidden tests are reinjected from the source notebook and executed:

```python
@app.cell(hide_code=True)
def _(check, mo, np, x, y):
    mo.stop(x is None, check("Q1: Array creation", []))
    # Visible checks — students see these
    check("Q1: Array creation", [
        (isinstance(x, np.ndarray), "x should be a numpy array"),
        (x.shape == (50,), f"Expected shape (50,), got {x.shape}"),
    ])
    ### BEGIN HIDDEN TESTS
    check("Q1: Edge cases", [
        (abs(x[0]) < 1e-10, "x should start at 0"),
        (abs(x[-1] - 2 * np.pi) < 1e-10, "x should end at 2*pi"),
    ])
    ### END HIDDEN TESTS
    return
```

Hidden checks contribute to the mark total like visible checks. In the release notebook, `grader.scores()` shows a placeholder message instead of the score table when hidden tests exist, so students don't see misleading partial marks.

## PEP 723 script dependencies

Include a [PEP 723](https://peps.python.org/pep-0723/) metadata block at the top of the notebook so that `marimo edit --sandbox` and `mograder validate` can automatically install dependencies:

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

`mograder generate` automatically adds `mograder-assignment` and `mograder-cell-hashes` lines to this block in the release notebook, enabling integrity checking during `mograder validate`.
