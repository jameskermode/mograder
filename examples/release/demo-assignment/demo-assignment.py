# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "marimo",
#     "numpy",
#     "mograder",
# ]
# mograder-assignment = "demo-assignment"
# mograder-cell-hashes = "375c0a19,6f11581d,83f06244,442241f7,c28e3951,06984910,eef64e3f,31db746f,92e2cea5,7294011f,f26057ad,b5f5459d"
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
    grader = Grader(mo, _marks)
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
    x = None
    y = None
    # YOUR CODE HERE
    pass
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
        dydx = ...
        # YOUR CODE HERE
        pass
        return dydx

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
                3,  # weight 3: accuracy matters more than type/shape
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
    integral = None
    # YOUR CODE HERE
    pass
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
    return (response_text,)


@app.cell(hide_code=True)
def _(grader):
    grader.scores()
    return


if __name__ == "__main__":
    app.run()
