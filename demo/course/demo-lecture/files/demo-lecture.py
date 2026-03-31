# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "marimo",
#     "numpy",
#     "matplotlib",
# ]
# ///

import marimo

__generated_with = "0.21.0"
app = marimo.App()


@app.cell(hide_code=True)
def _():
    import marimo as mo
    import numpy as np
    import matplotlib.pyplot as plt

    return mo, np, plt


@app.cell(hide_code=True)
def _(mo):
    mo.md(
        r"""
    # Introduction to Curve Fitting

    This lecture introduces the idea of fitting a model to data.
    We start with the simplest case: fitting a polynomial to noisy
    observations of an unknown function.
    """
    )
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(
        r"""
    ## The Problem

    Given $n$ data points $(x_i, y_i)$ where $y_i = f(x_i) + \varepsilon_i$
    and $\varepsilon_i \sim \mathcal{N}(0, \sigma^2)$, we want to find a
    polynomial $p(x) = \sum_{k=0}^{d} a_k x^k$ of degree $d$ that
    approximates $f$.

    The **least-squares** solution minimises the residual sum of squares:

    $$\hat{\mathbf{a}} = \arg\min_{\mathbf{a}} \sum_{i=1}^{n} \bigl(y_i - p(x_i)\bigr)^2 = \arg\min_{\mathbf{a}} \|\mathbf{y} - \mathbf{V}\mathbf{a}\|^2$$

    where $\mathbf{V}$ is the **Vandermonde matrix** with entries $V_{ik} = x_i^k$.
    """
    )
    return


@app.cell(hide_code=True)
def _(mo, np, plt):
    # Generate synthetic data
    rng = np.random.default_rng(42)
    x_data = np.sort(rng.uniform(-1, 1, 15))
    y_true = np.sin(np.pi * x_data)
    y_data = y_true + rng.normal(0, 0.2, len(x_data))

    x_fine = np.linspace(-1, 1, 200)
    y_fine = np.sin(np.pi * x_fine)

    _fig, _ax = plt.subplots(figsize=(8, 4))
    _ax.plot(x_fine, y_fine, "k--", alpha=0.4, label=r"$f(x) = \sin(\pi x)$")
    _ax.scatter(x_data, y_data, c="C0", zorder=5, label="Noisy data")
    _ax.set_xlabel("$x$")
    _ax.set_ylabel("$y$")
    _ax.legend()
    _ax.set_title("Observed data")
    plt.tight_layout()

    mo.md(
        f"""
    ## Example Data

    We sample 15 points from $f(x) = \\sin(\\pi x)$ with Gaussian noise
    ($\\sigma = 0.2$):

    {mo.as_html(_fig)}
    """
    )
    return x_data, x_fine, y_data, y_fine


@app.cell(hide_code=True)
def _(mo):
    degree_slider = mo.ui.slider(1, 12, value=3, label="Polynomial degree $d$")
    return (degree_slider,)


@app.cell(hide_code=True)
def _(degree_slider, mo, np, plt, x_data, x_fine, y_data, y_fine):
    d = degree_slider.value
    coeffs = np.polyfit(x_data, y_data, d)
    y_fit = np.polyval(coeffs, x_fine)
    residual = np.sum((y_data - np.polyval(coeffs, x_data)) ** 2)

    _fig, _ax = plt.subplots(figsize=(8, 4))
    _ax.plot(x_fine, y_fine, "k--", alpha=0.4, label=r"$f(x)$")
    _ax.scatter(x_data, y_data, c="C0", zorder=5, label="Data")
    _ax.plot(x_fine, y_fit, "C1", linewidth=2, label=f"Degree {d} fit")
    _ax.set_xlabel("$x$")
    _ax.set_ylabel("$y$")
    _ax.legend()
    _ax.set_title(f"Polynomial fit (degree {d})")
    _ax.set_ylim(-2, 2)
    plt.tight_layout()

    mo.md(
        f"""
    ## Interactive Fit

    Use the slider to change the polynomial degree and observe how the
    fit changes. Low degrees **underfit** (miss the trend), while high
    degrees **overfit** (fit the noise).

    {degree_slider}

    {mo.as_html(_fig)}

    Residual sum of squares: **{residual:.4f}**

    > **Exercise:** Try the [demo assignment](/run/demo-assignment/) to
    > practise these ideas with numpy.
    """
    )
    return


if __name__ == "__main__":
    app.run()
