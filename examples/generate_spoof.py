#!/usr/bin/env python3
"""Generate spoof submissions for testing the formgrader UI.

Creates submitted/ notebooks with various solution quality, then runs
mograder autograde to produce autograded/ versions, simulates GTA grading
on some, and exports feedback HTML for a few.

Usage:
    uv run python examples/generate_spoof.py
"""

import csv
import shutil
from pathlib import Path

EXAMPLES = Path(__file__).parent
RELEASE_HOLISTIC = EXAMPLES / "release" / "demo-holistic" / "demo-holistic.py"
RELEASE_ASSIGNMENT = EXAMPLES / "release" / "demo-assignment" / "demo-assignment.py"

STUDENT_NAMES = {
    "alice": "Alice Johnson",
    "bob": "Bob Smith",
    "carol": "Carol Williams",
    "dave": "Dave Brown",
    "eve": "Eve Davis",
    "frank": "Frank Miller",
}


# ---------------------------------------------------------------------------
# demo-holistic: Q1 (palindrome), Q2 (word counter), holistic _mark 0-100
# ---------------------------------------------------------------------------

HOLISTIC_SOLUTIONS = {
    "alice": {
        # Both correct
        "is_palindrome": '''\
    def is_palindrome(s):
        cleaned = s.lower().replace(" ", "")
        return cleaned == cleaned[::-1]''',
        "word_count": '''\
    def word_count(text):
        counts = {}
        for word in text.lower().split():
            counts[word] = counts.get(word, 0) + 1
        return counts''',
    },
    "bob": {
        # Q1 correct, Q2 wrong (forgot lower())
        "is_palindrome": '''\
    def is_palindrome(s):
        cleaned = s.lower().replace(" ", "")
        return cleaned == cleaned[::-1]''',
        "word_count": '''\
    def word_count(text):
        counts = {}
        for word in text.split():
            counts[word] = counts.get(word, 0) + 1
        return counts''',
    },
    "carol": {
        # Both wrong
        "is_palindrome": '''\
    def is_palindrome(s):
        return s == s[::-1]''',
        "word_count": '''\
    def word_count(text):
        return {w: 1 for w in text.split()}''',
    },
    "dave": {
        # Q1 correct, Q2 correct
        "is_palindrome": '''\
    def is_palindrome(s):
        s = s.lower().replace(" ", "")
        return s == s[::-1]''',
        "word_count": '''\
    def word_count(text):
        result = {}
        for w in text.lower().split():
            result[w] = result.get(w, 0) + 1
        return result''',
    },
    "eve": {
        # Both correct (will be left ungraded by GTA)
        "is_palindrome": '''\
    def is_palindrome(s):
        cleaned = s.replace(" ", "").lower()
        return cleaned == cleaned[::-1]''',
        "word_count": '''\
    def word_count(text):
        d = {}
        for word in text.lower().split():
            d[word] = d.get(word, 0) + 1
        return d''',
    },
    "frank": {
        # Q1 wrong, Q2 correct
        "is_palindrome": '''\
    def is_palindrome(s):
        return s.lower() == s.lower()[::-1]''',
        "word_count": '''\
    def word_count(text):
        counts = {}
        for w in text.lower().split():
            counts[w] = counts.get(w, 0) + 1
        return counts''',
    },
}


def _make_holistic_submission(student: str, solutions: dict) -> str:
    """Replace YOUR CODE HERE blocks in the holistic release notebook."""
    text = RELEASE_HOLISTIC.read_text()

    # Replace is_palindrome
    text = text.replace(
        "    def is_palindrome(s):\n        # YOUR CODE HERE\n        pass",
        solutions["is_palindrome"],
    )

    # Replace word_count
    text = text.replace(
        "    def word_count(text):\n        # YOUR CODE HERE\n        pass",
        solutions["word_count"],
    )

    return text


# ---------------------------------------------------------------------------
# demo-assignment: Q1=10, Q2=15, Q3=15, Analysis=60 (per-question marks)
# ---------------------------------------------------------------------------

ASSIGNMENT_SOLUTIONS = {
    "alice": {
        # All 3 auto Qs correct
        "q1": """\
    x = np.linspace(0, 2 * np.pi, 50)
    y = np.sin(x)""",
        "q2": """\
    def finite_diff(x, y):
        dydx = np.zeros_like(y)
        dydx[0] = (y[1] - y[0]) / (x[1] - x[0])
        dydx[-1] = (y[-1] - y[-2]) / (x[-1] - x[-2])
        dydx[1:-1] = (y[2:] - y[:-2]) / (x[2:] - x[:-2])
        return dydx""",
        "q3": """\
    integral = float(np.sum((y[:-1] + y[1:]) / 2 * np.diff(x)))""",
    },
    "bob": {
        # Q1 correct, Q2 wrong (forward diff only), Q3 correct
        "q1": """\
    x = np.linspace(0, 2 * np.pi, 50)
    y = np.sin(x)""",
        "q2": """\
    def finite_diff(x, y):
        dydx = np.zeros_like(y)
        for i in range(len(x) - 1):
            dydx[i] = (y[i+1] - y[i]) / (x[i+1] - x[i])
        dydx[-1] = dydx[-2]
        return dydx""",
        "q3": """\
    integral = float(np.sum((y[:-1] + y[1:]) / 2 * np.diff(x)))""",
    },
    "carol": {
        # Q1 correct only
        "q1": """\
    x = np.linspace(0, 2 * np.pi, 50)
    y = np.sin(x)""",
        "q2": """\
    def finite_diff(x, y):
        return np.gradient(y)""",
        "q3": """\
    integral = sum(y)""",
    },
    "dave": {
        # All 3 correct
        "q1": """\
    x = np.linspace(0, 2 * np.pi, 50)
    y = np.sin(x)""",
        "q2": """\
    def finite_diff(x, y):
        n = len(x)
        dydx = np.empty(n)
        dydx[0] = (y[1] - y[0]) / (x[1] - x[0])
        dydx[-1] = (y[-1] - y[-2]) / (x[-1] - x[-2])
        for i in range(1, n - 1):
            dydx[i] = (y[i+1] - y[i-1]) / (x[i+1] - x[i-1])
        return dydx""",
        "q3": """\
    integral = float(np.trapz(y, x))""",
    },
    "eve": {
        # Q1 and Q3 correct, Q2 wrong
        "q1": """\
    x = np.linspace(0, 2 * np.pi, 50)
    y = np.sin(x)""",
        "q2": """\
    def finite_diff(x, y):
        return np.diff(y) / np.diff(x)""",
        "q3": """\
    integral = float(np.trapz(y, x))""",
    },
    "frank": {
        # Nothing correct (didn't even try Q1 properly)
        "q1": """\
    x = list(range(50))
    y = x""",
        "q2": """\
    def finite_diff(x, y):
        pass""",
        "q3": """\
    integral = 42""",
    },
}


def _make_assignment_submission(student: str, solutions: dict) -> str:
    """Replace YOUR CODE HERE blocks in the assignment release notebook."""
    text = RELEASE_ASSIGNMENT.read_text()

    # Q1: array creation
    text = text.replace(
        "    x = None\n    y = None\n    # YOUR CODE HERE\n    pass",
        solutions["q1"],
    )

    # Q2: finite_diff
    text = text.replace(
        "    def finite_diff(x, y):\n        # YOUR CODE HERE\n        pass",
        solutions["q2"],
    )

    # Q3: trapezoidal rule
    text = text.replace(
        "    integral = None\n    # YOUR CODE HERE\n    pass",
        solutions["q3"],
    )

    return text


# ---------------------------------------------------------------------------
# Moodle CSV
# ---------------------------------------------------------------------------


def _generate_moodle_csv():
    """Write a Moodle offline grading worksheet CSV with spoof student names."""
    fieldnames = [
        "Identifier",
        "Full name",
        "Email address",
        "Username",
        "Status",
        "Grade",
        "Maximum grade",
        "Grade can be changed",
        "Last modified (submission)",
        "Last modified (grade)",
        "Feedback comments",
    ]
    rows = []
    for i, (username, full_name) in enumerate(sorted(STUDENT_NAMES.items()), start=1):
        rows.append(
            {
                "Identifier": f"Participant {1000 + i}",
                "Full name": full_name,
                "Email address": f"{username}@example.com",
                "Username": username,
                "Status": "Submitted for grading",
                "Grade": "",
                "Maximum grade": "100",
                "Grade can be changed": "Yes",
                "Last modified (submission)": "Monday, 1 January 2026, 12:00 PM",
                "Last modified (grade)": "",
                "Feedback comments": "",
            }
        )

    moodle_csv = EXAMPLES / "moodle_worksheet.csv"
    with open(moodle_csv, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(f"\n  {moodle_csv.relative_to(EXAMPLES.parent)}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    # Clean up any existing spoof data
    for stage in ["submitted", "autograded", "feedback"]:
        d = EXAMPLES / stage
        if d.exists():
            shutil.rmtree(d)

    # Generate submitted notebooks
    for name in ["demo-holistic", "demo-assignment"]:
        sub_dir = EXAMPLES / "submitted" / name
        sub_dir.mkdir(parents=True, exist_ok=True)

        if name == "demo-holistic":
            for student, solutions in HOLISTIC_SOLUTIONS.items():
                text = _make_holistic_submission(student, solutions)
                (sub_dir / f"{student}.py").write_text(text)
                print(f"  submitted/{name}/{student}.py")
        else:
            for student, solutions in ASSIGNMENT_SOLUTIONS.items():
                text = _make_assignment_submission(student, solutions)
                (sub_dir / f"{student}.py").write_text(text)
                print(f"  submitted/{name}/{student}.py")

    # Generate Moodle CSV for testing name lookup in Students tab
    _generate_moodle_csv()

    print("\nSubmitted notebooks and Moodle CSV created.")
    print("Now run autograde:\n")
    print(
        "  uv run mograder autograde examples/submitted/demo-holistic/*.py "
        "--source examples/source/demo-holistic/demo-holistic.py"
    )
    print(
        "  uv run mograder autograde examples/submitted/demo-assignment/*.py "
        "--source examples/source/demo-assignment/demo-assignment.py"
    )
    print(
        "\nThen run: uv run python examples/generate_spoof.py --postprocess"
        " to simulate GTA grading."
    )


def postprocess():
    """Simulate GTA grading on some autograded notebooks."""
    # Holistic: alice=85, bob=55, carol=20, dave=78, frank=45
    # eve left ungraded
    holistic_grades = {
        "alice": (85, "Excellent work on both questions. Clean implementations."),
        "bob": (55, "Palindrome correct but word_count is case-sensitive."),
        "carol": (20, "Neither function handles edge cases correctly."),
        "dave": (78, "Both correct. Could discuss complexity more."),
        "frank": (45, "Palindrome misses spaces. Word counter is good."),
    }

    hol_dir = EXAMPLES / "autograded" / "demo-holistic"
    if hol_dir.is_dir():
        for student, (mark, fb) in holistic_grades.items():
            path = hol_dir / f"{student}.py"
            if path.exists():
                text = path.read_text()
                text = text.replace("_mark = None", f"_mark = {mark}", 1)
                text = text.replace('_feedback = ""', f'_feedback = "{fb}"', 1)
                path.write_text(text)
                print(f"  Graded: demo-holistic/{student}.py → {mark}/100")

    # Assignment: alice=50, bob=35, dave=55
    # carol, eve, frank left ungraded
    assignment_grades = {
        "alice": (50, "Strong analysis covering accuracy and limitations."),
        "bob": (35, "Decent analysis but missed central vs forward diff discussion."),
        "dave": (55, "Thorough analysis with good examples."),
    }

    asn_dir = EXAMPLES / "autograded" / "demo-assignment"
    if asn_dir.is_dir():
        for student, (mark, fb) in assignment_grades.items():
            path = asn_dir / f"{student}.py"
            if path.exists():
                text = path.read_text()
                text = text.replace("_mark = None", f"_mark = {mark}", 1)
                text = text.replace('_feedback = ""', f'_feedback = "{fb}"', 1)
                path.write_text(text)
                print(f"  Graded: demo-assignment/{student}.py → manual={mark}")

    print("\nGTA grading simulated.")
    print("Now export feedback for graded notebooks:\n")
    print("  uv run mograder feedback examples/autograded/demo-holistic/*.py")
    print("  uv run mograder feedback examples/autograded/demo-assignment/*.py")


if __name__ == "__main__":
    import sys

    if "--postprocess" in sys.argv:
        postprocess()
    else:
        main()
