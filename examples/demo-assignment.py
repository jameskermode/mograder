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
    def check(label, checks, marks=None):
        """Run a list of (condition, message) checks and display coloured feedback.

        Args:
            label: Name of the test (e.g. "Q2: Model evaluation")
            checks: List of (bool_expr, fail_message) tuples
            marks: Optional marks available for this question
        """
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
    ### BEGIN SOLUTION
    x = np.linspace(0, 2 * np.pi, 50)
    y = np.sin(x)
    ### END SOLUTION
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
        ### BEGIN SOLUTION
        dydx = np.zeros_like(y)
        dydx[0] = (y[1] - y[0]) / (x[1] - x[0])
        dydx[-1] = (y[-1] - y[-2]) / (x[-1] - x[-2])
        dydx[1:-1] = (y[2:] - y[:-2]) / (x[2:] - x[:-2])
        return dydx
        ### END SOLUTION

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
    ### BEGIN SOLUTION
    integral = np.sum((y[:-1] + y[1:]) / 2 * np.diff(x))
    ### END SOLUTION
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
    ### BEGIN SOLUTION
    _response = r"""
    The finite difference method approximates derivatives using nearby function
    values. Central differences achieve second-order accuracy O(h^2) because the
    leading error terms cancel by symmetry, while forward and backward differences
    are only first-order O(h). With 50 grid points spanning [0, 2*pi], the spacing
    h ~ 0.128 gives a max error of about 0.005 for interior points using central
    differences.

    The trapezoidal rule approximates the area under a curve by summing trapezoids.
    For smooth periodic functions like sin(x) integrated over a full period, it
    performs exceptionally well because the errors at each interval partially cancel.
    It struggles with discontinuous functions or sharp features where the linear
    interpolation between points is a poor approximation.
    """
    ### END SOLUTION
    mo.md(_response)
    return


@app.cell(hide_code=True)
def _(mo):
    # === MOGRADER: MARKS ===
    # Auto-checked question marks are defined at each check() call site.
    # Only manual questions (graded by GTA) need to be listed here.
    _marks = {
        "Analysis": 60,
    }
    # --- display (do not edit below) ---
    _total = sum(_marks.values())
    mo.callout(mo.md(f"**Total marks available: {_total}**"), kind="neutral")
    return (_marks,)


if __name__ == "__main__":
    app.run()
