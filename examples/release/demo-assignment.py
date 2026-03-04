# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "marimo",
#     "numpy",
# ]
# ///

import marimo

__generated_with = "0.20.0"
app = marimo.App()


@app.cell
def _():
    import marimo as mo

    return (mo,)



@app.cell(hide_code=True)
def _(mo):
    mograder_check_state, mograder_set_check = mo.state({})
    return mograder_check_state, mograder_set_check


@app.cell(hide_code=True)
def _(mo, mograder_set_check):
    def check(label, checks, marks=None):
        """Run a list of (condition, message) checks and display coloured feedback.

        Args:
            label: Name of the test (e.g. "Q2: Model evaluation")
            checks: List of (bool_expr, fail_message) tuples
            marks: Optional marks available for this question
        """
        _key = label.split(":")[0].strip()
        _passed = bool(checks) and all(ok for ok, _ in checks)
        mograder_set_check(lambda prev: {**prev, _key: _passed})
        failures = [msg for ok, msg in checks if not ok]
        if marks is not None:
            earned = marks if checks and not failures else 0
            badge = f'<span style="float:right"><code>[{earned}/{marks} marks]</code></span>'
        else:
            badge = ""
        if not checks:
            return mo.callout(
                mo.md(f"{badge}**{label}** — waiting for your code"), kind="warn"
            )
        if failures:
            items = "\n".join(f"- {f}" for f in failures)
            return mo.callout(
                mo.md(f"{badge}**{label}** — some checks failed:\n\n{items}"),
                kind="danger",
            )
        return mo.callout(
            mo.md(f"{badge}**{label}** — all checks passed"), kind="success"
        )

    return (check,)


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
    - The **Written Analysis** section at the bottom is the only summatively assessed part
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
    x = None
    y = None
    # YOUR CODE HERE
    pass
    return x, y


@app.cell(hide_code=True)
def _(check, mo, np, x, y):
    _q1_marks = 10
    mo.stop(x is None, check("Q1: Array creation", [], marks=_q1_marks))
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
        marks=_q1_marks,
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
        # YOUR CODE HERE
        pass

    return (finite_diff,)


@app.cell(hide_code=True)
def _(check, finite_diff, mo, np, x, y):
    _q2_marks = 15
    mo.stop(x is None, check("Q2: Finite differences", [], marks=_q2_marks))
    _dydx = finite_diff(x, y)
    _exact = np.cos(x)
    mo.stop(_dydx is None, check("Q2: Finite differences", [], marks=_q2_marks))
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
        marks=_q2_marks,
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
    integral = None
    # YOUR CODE HERE
    pass
    return (integral,)


@app.cell(hide_code=True)
def _(check, integral, mo):
    _q3_marks = 15
    mo.stop(integral is None, check("Q3: Trapezoidal rule", [], marks=_q3_marks))
    check(
        "Q3: Trapezoidal rule",
        [
            (isinstance(integral, float), "integral should be a float"),
            (
                abs(integral) < 1e-6,
                f"Integral of sin over [0, 2*pi] should be ~0, got {integral:.6f}",
            ),
        ],
        marks=_q3_marks,
    )
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ---

    ## Written Analysis (Summative)

    This is the only part of the assignment that is formally assessed. A GTA will
    read your response and assign a single holistic mark.

    Discuss your results from the exercises above. Your response should address:

    - How does the accuracy of the finite difference method depend on the grid spacing?
    - Why are central differences more accurate than forward/backward differences?
    - What are the limitations of the trapezoidal rule, and when might it perform poorly?
    """)
    return


@app.cell
def _(mo):
    _response = "*Write your analysis here...*"
    # YOUR CODE HERE
    pass
    mo.md(_response)
    return


@app.cell(hide_code=True)
def _(mo, mograder_check_state):
    # === MOGRADER: MARKS ===
    # Auto-checked question marks are defined at each check() call site.
    # Only manual questions (graded by GTA) need to be listed here.
    _marks = {
        "Analysis": 60,
    }
    # --- display (do not edit below) ---
    _results = mograder_check_state()
    _auto = sum(v for k, v in _marks.items() if _results.get(k))
    _total = sum(_marks.values())
    _rows = ""
    for _q, _pts in _marks.items():
        _got = _pts if _results.get(_q) else 0
        _icon = "PASS" if _results.get(_q) else ("FAIL" if _q in _results else "—")
        _rows += f"| {_q} | {_icon} | {_got}/{_pts} |\n"
    _rows += f"| **Total** | | **{_auto}/{_total}** |\n"
    mo.callout(mo.md(
        f"## Your Score\n\n"
        f"| Question | Status | Marks |\n|----------|--------|-------|\n{_rows}"),
        kind="success" if _auto == _total else "neutral")
    return (_marks,)


if __name__ == "__main__":
    app.run()
