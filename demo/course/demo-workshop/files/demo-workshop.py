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
    from mograder.runtime import check, hint

    # === MOGRADER: ANSWERS ===
    _answers = {"Q1": [2.54, 0.07], "Q2": 42}
    return check, hint, mo


@app.cell(hide_code=True)
def _():
    import numpy as np

    return (np,)


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    # Demo Workshop — Numerical Methods

    Welcome to this interactive workshop on numerical methods with NumPy!

    - Complete the exercises below by replacing `# YOUR CODE HERE`
    - Coloured feedback boxes tell you if your checks pass or fail
    - Use the **hints** if you get stuck — they reveal progressively
    - After the workshop, the instructor may release model solutions
    """)
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Exercise 1 — Array Operations

    Create a 1D numpy array `x` containing 50 equally spaced values
    from 0 to 2π (inclusive), and compute `y = sin(x)`.
    """)
    return


@app.cell(hide_code=True)
def _(hint):
    hint(
        "Think about which NumPy function creates evenly spaced arrays",
        "Use `np.linspace(start, stop, num_points)`",
        "The stop value should be `2 * np.pi`",
    )
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
    ## Exercise 2 — Numerical Integration

    Implement the trapezoidal rule to compute the definite integral
    of `y` over `x`. Store the result in `integral`.

    Recall: $\int_a^b f(x)\,dx \approx \sum_{i=0}^{N-1} \frac{f(x_i) + f(x_{i+1})}{2} \Delta x_i$
    """)
    return


@app.cell(hide_code=True)
def _(hint):
    hint(
        "The trapezoidal rule averages adjacent y-values and multiplies by the spacing",
        "Use `np.diff(x)` to get the spacing between consecutive x values",
        "Try: `np.sum((y[:-1] + y[1:]) / 2 * np.diff(x))`",
    )
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
    mo.stop(integral is None, check("Q2: Trapezoidal rule", []))
    check(
        "Q2: Trapezoidal rule",
        [
            (isinstance(integral, float), "integral should be a float"),
            (
                abs(integral) < 1e-6,
                f"Integral of sin over [0, 2*pi] should be ~0, got {integral:.6f}",
            ),
        ],
    )
    return


if __name__ == "__main__":
    app.run()
