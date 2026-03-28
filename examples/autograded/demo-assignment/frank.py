# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "marimo",
#     "numpy",
#     "mograder",
# ]
# ///

import marimo

__generated_with = "0.20.0"
app = marimo.App()


@app.cell(hide_code=True)
def _():
    import marimo as mo
    from mograder.runtime import Grader

    # === MOGRADER: MARKS ===
    _marks = {"Q1": 10, "Q2": 15, "Q3": 15, "Analysis": 60}
    grader = Grader(_marks)
    check = grader.check
    return check, grader, mo


@app.cell(hide_code=True)
def _():
    import numpy as np

    return (np,)


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    # Demo Assignment — Numerical Methods

    **How this notebook works**

    - Code cells labelled **YOUR CODE HERE** are for you to complete
    - Coloured feedback boxes appear automatically beneath each task:
      - Red = some checks failed (read the messages for guidance)
      - Amber = waiting for your code
      - Green = all checks passed
    - All questions carry marks — your score updates automatically
    - The **Written Analysis** section is graded by a GTA
    """)
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Part 1 — Array Operations

    **Question 1.** Create a 1D numpy array `x` containing 50 equally spaced values
    from 0 to 2*pi (inclusive), and compute `y = sin(x)`.
    """)
    return


@app.cell
def _(np):
    x = list(range(50))
    y = x
    return x, y


@app.cell(hide_code=True)
def _(check, mo, np, x, y):
    mo.stop(x is None, check("Q1: Array creation", []))
    check(
        "Q1: Array creation",
        [
            (isinstance(x, np.ndarray), "x should be a numpy array"),
            (x.shape == (50,), f"x should have shape (50,), got {x.shape}"),
            (abs(x[0]) < 1e-10, "x should start at 0"),
            (abs(x[-1] - 2 * np.pi) < 1e-10, "x should end at 2*pi"),
            (isinstance(y, np.ndarray), "y should be a numpy array"),
            (y.shape == (50,), f"y should have shape (50,), got {y.shape}"),
            (abs(y[0]) < 1e-10, "y[0] should be sin(0) = 0"),
        ],
    )
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Part 2 — Numerical Differentiation

    **Question 2.** Implement a function `finite_diff(x, y)` that computes the
    numerical derivative dy/dx using central differences for interior points and
    forward/backward differences at the boundaries. Return the derivative as a
    numpy array of the same length as `x`.
    """)
    return


@app.cell
def _(np):
    def finite_diff(x, y):
        pass

    return (finite_diff,)


@app.cell(hide_code=True)
def _(check, finite_diff, mo, np, x, y):
    mo.stop(x is None, check("Q2: Finite differences", []))
    _dydx = finite_diff(x, y)
    _exact = np.cos(x)
    mo.stop(_dydx is None, check("Q2: Finite differences", []))
    check(
        "Q2: Finite differences",
        [
            (isinstance(_dydx, np.ndarray), "Result should be a numpy array"),
            (
                _dydx.shape == x.shape,
                f"Result shape {_dydx.shape} should match input shape {x.shape}",
            ),
            (
                np.max(np.abs(_dydx - _exact)) < 0.05,
                f"Max error {np.max(np.abs(_dydx - _exact)):.4f} should be < 0.05",
            ),
        ],
    )
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Part 3 — Numerical Integration

    **Question 3.** Implement the trapezoidal rule to compute the definite integral
    of `y` over `x`. Store the result in `integral`.

    Recall: $\int_a^b f(x)\,dx \approx \sum_{i=0}^{N-1} \frac{f(x_i) + f(x_{i+1})}{2} \Delta x_i$
    """)
    return


@app.cell
def _(np, x, y):
    integral = 42
    return (integral,)


@app.cell(hide_code=True)
def _(check, integral, mo):
    mo.stop(integral is None, check("Q3: Trapezoidal rule", []))
    check(
        "Q3: Trapezoidal rule",
        [
            (isinstance(integral, float), "integral should be a float"),
            (
                abs(integral) < 1e-6,
                f"Integral of sin over [0, 2*pi] should be ~0, got {integral:.6f}",
            ),
        ],
    )
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ---

    ## Written Analysis

    This section is graded by a GTA. Your response should address:

    - How does the accuracy of the finite difference method depend on the grid spacing?
    - Why are central differences more accurate than forward/backward differences?
    - What are the limitations of the trapezoidal rule, and when might it perform poorly?
    """)
    return


@app.cell
def _(mo):
    mo.md(r"""
    *Write your analysis here...*
    """)
    return


@app.cell(hide_code=True)
def _(grader):
    grader.scores()
    return



@app.cell(hide_code=True)
def _(mo):
    # === MOGRADER: VERIFICATION SUMMARY ===
    _mograder_checks = [
        ("Q3: Trapezoidal rule", "FAIL"),
    ]
    _mograder_marks = {'Q1': 10, 'Q2': 15, 'Q3': 15, 'Analysis': 60}
    _cell_errors = 0
    _auto_earned = 0
    _table = ""
    for _label, _s in _mograder_checks:
        _key = _label.split(":")[0].strip()
        _avail = _mograder_marks.get(_key, "")
        _earned = _avail if _s == "PASS" else 0
        if _s == "PASS" and isinstance(_avail, (int, float)):
            _auto_earned += _avail
        _marks_col = f"{_earned}/{_avail}" if _avail != "" else ""
        _table += f"| {_label} | {_s} | {_marks_col} |\n"
    _table += "| Q1 | — | ?/10 |\n"
    _table += "| Q2 | — | ?/15 |\n"
    _table += "| Analysis | — | ?/60 |\n"
    _total_avail = sum(_mograder_marks.values())
    _table += f"| **Total** | | **{_auto_earned}/{_total_avail}** |\n"
    mo.callout(mo.md(f"## Verification Summary\n\n"
        f"| Check | Result | Marks |\n|-------|--------|-------|\n{_table}\n"
        f"Cell errors: {_cell_errors}"),
        kind="success" if all(s == "PASS" for _, s in _mograder_checks) else "danger")
    return

@app.cell
def _(mo):
    # === MOGRADER: GTA FEEDBACK ===
    # Auto marks: 0/15
    # Set _mark for manual questions (out of 85), then save.
    _mark = None       # e.g. _mark = 85
    _feedback = ""     # e.g. _feedback = "Good analysis of the DP approach..."

    # --- display (do not edit below) ---
    if _mark is not None:
        _total = 0 + _mark
        mo.callout(mo.md(f"**Mark: {_total}/100** (auto: 0, manual: {_mark})\n\n{_feedback}"), kind="success")
    else:
        mo.callout(mo.md("**Awaiting GTA feedback** — edit `_mark` (out of 85) and `_feedback` above\n\n"
            f"Auto marks so far: 0/15"), kind="warn")
    return

if __name__ == "__main__":
    app.run()
