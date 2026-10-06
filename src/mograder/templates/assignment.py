# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "marimo",
#     "mograder",
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
    # {assignment_name}

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
    ### BEGIN SOLUTION
    pass
    ### END SOLUTION
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
def written_analysis(mo):
    response_text = "*Write your analysis here...*"
    ### BEGIN SOLUTION
    response_text = r"""
    *Sample solution text.*
    """
    ### END SOLUTION
    mo.md(response_text)
    return


@app.cell(hide_code=True)
def _(mo):
    notebook_file = mo.watch.file(__file__)
    return (notebook_file,)


@app.cell(hide_code=True)
def _(notebook_file):
    from mograder.runtime import word_count as _word_count

    _word_count(notebook_file, target=(300, 500))
    return


if __name__ == "__main__":
    app.run()
