# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "marimo",
#     "mograder @ git+https://github.com/jameskermode/mograder.git",
# ]
# ///

import marimo

__generated_with = "0.20.0"
app = marimo.App()


@app.cell(hide_code=True)
def _():
    import marimo as mo
    from mograder.runtime import check

    return check, mo


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    # test

    - Code cells labelled **YOUR CODE HERE** are for you to complete
    - Coloured feedback boxes appear automatically beneath each task
    """)
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Question 1

    *Describe the task here.*
    """)
    return


@app.cell
def _():
    # YOUR CODE HERE
    pass
    return


@app.cell(hide_code=True)
def _(check):
    check(
        "Q1",
        [
            (True, "Replace with your test condition"),
        ],
    )
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ---

    ## Written Analysis

    *Describe what students should discuss here.*
    """)
    return


@app.cell
def _(mo):
    mo.md(r"""
    *Write your analysis here...*
    """)
    return


if __name__ == "__main__":
    app.run()
