# /// script
# requires-python = ">=3.11"
# dependencies = ["marimo"]
# ///

import marimo

__generated_with = "0.20.0"
app = marimo.App()


@app.cell
def _():
    import marimo as mo

    return (mo,)


@app.cell
def _(mo):
    def check(label, checks):
        failures = [msg for ok, msg in checks if not ok]
        if not checks:
            return mo.callout(mo.md(f"**{label}** — waiting"), kind="warn")
        if failures:
            return mo.callout(mo.md(f"**{label}** — failed"), kind="danger")
        return mo.callout(mo.md(f"**{label}** — all checks passed"), kind="success")

    return (check,)


@app.cell
def _():
    ### BEGIN SOLUTION
    x = 42
    y = x**2
    ### END SOLUTION
    return (x, y)


@app.cell
def _(check, x, y):
    check(
        "Q1: Computation",
        [
            (x == 42, "x should be 42"),
            (y == 1764, "y should be x^2"),
        ],
    )
    return


@app.cell
def _():
    ### BEGIN SOLUTION
    def greet(name):
        return f"Hello, {name}!"

    ### END SOLUTION
    return (greet,)


@app.cell
def _(check, greet):
    check(
        "Q2: Greeting",
        [
            (greet("World") == "Hello, World!", "greet should return greeting"),
        ],
    )
    return


if __name__ == "__main__":
    app.run()
