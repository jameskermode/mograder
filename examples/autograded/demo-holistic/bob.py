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
    # Demo Assignment — String Processing

    **How this notebook works**

    - Code cells labelled **YOUR CODE HERE** are for you to complete
    - Coloured feedback boxes appear automatically beneath each task
    - A GTA will assign a single holistic mark (0-100) after reviewing your work
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
        cleaned = s.lower().replace(" ", "")
        return cleaned == cleaned[::-1]

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
        counts = {}
        for word in text.split():
            counts[word] = counts.get(word, 0) + 1
        return counts

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
    # === MOGRADER: VERIFICATION SUMMARY ===
    _mograder_checks = [
        ("Q1: Palindrome checker", "PASS"),
        ("Q2: Word counter", "FAIL"),
    ]
    _cell_errors = 0
    _table = "\n".join(
        f"| {label} | {'PASS' if s == 'PASS' else 'FAIL' if s == 'FAIL' else 'WAIT'} |"
        for label, s in _mograder_checks
    )
    mo.callout(mo.md(f"## Verification Summary\n\n"
        f"| Check | Result |\n|-------|--------|\n{_table}\n\n"
        f"Cell errors: {_cell_errors}"),
        kind="success" if all(s == "PASS" for _, s in _mograder_checks) else "danger")
    return

@app.cell
def _(mo):
    # === MOGRADER: GTA FEEDBACK ===
    # Set the mark (0-100) and write 2-3 sentences of feedback, then save.
    _mark = 55       # e.g. _mark = 65
    _feedback = "Palindrome correct but word_count is case-sensitive."     # e.g. _feedback = "Good analysis of the DP approach..."

    # --- display (do not edit below) ---
    if _mark is not None:
        mo.callout(mo.md(f"**Mark: {_mark}/100**\n\n{_feedback}"), kind="success")
    else:
        mo.callout(mo.md("**Awaiting GTA feedback** — edit `_mark` and `_feedback` above"), kind="warn")
    return

if __name__ == "__main__":
    app.run()
