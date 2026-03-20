# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "marimo",
#     "mograder>=0.0.7",
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
    # Demo Assignment — String Processing

    **How this notebook works**

    - Code cells labelled **YOUR CODE HERE** are for you to complete
    - Coloured feedback boxes appear automatically beneath each task
    - A marker will assign a single holistic mark (0-100) after reviewing your work
    """)
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Part 1 — Palindrome Checker

    **Question 1.** Write a function `is_palindrome(s)` that returns `True` if the
    string `s` reads the same forwards and backwards (case-insensitive, ignoring
    spaces), and `False` otherwise.
    """)
    return


@app.cell
def _():
    def is_palindrome(s):
        # YOUR CODE HERE
        pass

    return (is_palindrome,)


@app.cell(hide_code=True)
def _(check, is_palindrome):
    check(
        "Q1: Palindrome checker",
        [
            (
                is_palindrome("racecar") is True,
                'is_palindrome("racecar") should be True',
            ),
            (is_palindrome("hello") is False, 'is_palindrome("hello") should be False'),
            (
                is_palindrome("A man a plan a canal Panama") is True,
                "Should be case-insensitive and ignore spaces",
            ),
            (is_palindrome("") is True, "Empty string is a palindrome"),
        ],
    )
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Part 2 — Word Counter

    **Question 2.** Write a function `word_count(text)` that returns a dictionary
    mapping each lowercase word to the number of times it appears in `text`.
    Words are separated by whitespace.
    """)
    return


@app.cell
def _():
    def word_count(text):
        # YOUR CODE HERE
        pass

    return (word_count,)


@app.cell(hide_code=True)
def _(check, word_count):
    check(
        "Q2: Word counter",
        [
            (
                word_count("the cat sat on the mat")
                == {"the": 2, "cat": 1, "sat": 1, "on": 1, "mat": 1},
                "Basic word counting",
            ),
            (word_count("") == {}, "Empty string should return empty dict"),
            (
                word_count("Hello hello HELLO") == {"hello": 3},
                "Should be case-insensitive",
            ),
        ],
    )
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ---

    ## Written Analysis

    Discuss the time and space complexity of your implementations above.
    Consider edge cases and explain any design decisions you made.
    """)
    return


@app.cell
def _(mo):
    mo.md(r"""
    *Write your analysis here...*
    """)
    return


@app.cell(hide_code=True)
def _(mo):
    # === MOGRADER: SUBMIT ===
    submit_username = mo.ui.text(label="Username", placeholder="Enter your username")
    submit_btn = mo.ui.run_button(label="Submit")
    mo.hstack([submit_username, submit_btn])
    return (submit_btn, submit_username)


@app.cell(hide_code=True)
def _(submit_btn, submit_username, mo):
    mo.stop(not submit_btn.value or not submit_username.value)
    from mograder.remote import submit as submit_fn

    submit_result = submit_fn(
        "https://mograder-demo.jrkermode.uk",
        "demo-holistic",
        __file__,
        submit_username.value,
    )
    mo.callout(mo.md(f"**Submitted!** Status: {submit_result}"), kind="success")
    return


if __name__ == "__main__":
    app.run()
