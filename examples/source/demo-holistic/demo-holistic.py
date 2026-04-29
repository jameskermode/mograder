# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "marimo",
#     "mograder",
# ]
# ///

import marimo

__generated_with = "0.23.4"
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


@app.function
def is_palindrome(s):
    ### BEGIN SOLUTION
    cleaned = s.lower().replace(" ", "")
    return cleaned == cleaned[::-1]
    ### END SOLUTION


@app.cell(hide_code=True)
def _(check):
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


@app.function
def word_count(text):
    ### BEGIN SOLUTION
    counts = {}
    for word in text.lower().split():
        counts[word] = counts.get(word, 0) + 1
    return counts
    ### END SOLUTION


@app.cell(hide_code=True)
def _(check):
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
    response_text = "*Write your analysis here...*"
    ### BEGIN SOLUTION
    response_text = r"""
    The `is_palindrome` function runs in O(n) time and O(n) space where n is
    the length of the input string, due to creating the cleaned and reversed
    copies. An in-place two-pointer approach could reduce space to O(1).

    The `word_count` function runs in O(n) time where n is the total number of
    characters, since `split()` and the loop each traverse the string once.
    Space is O(k) where k is the number of unique words.
    """
    ### END SOLUTION
    mo.md(response_text)
    return


if __name__ == "__main__":
    app.run()
