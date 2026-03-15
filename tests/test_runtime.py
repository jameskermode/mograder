"""Tests for mograder.runtime — check() and Grader."""

from unittest.mock import MagicMock, patch

from mograder.runtime import Grader


def _mock_mo():
    """Create a mock marimo module with callout, md, and state."""
    mo = MagicMock()
    mo.md.side_effect = lambda text: text
    mo.callout.side_effect = lambda content, kind="neutral": (content, kind)

    def _make_state(init):
        container = [init]

        def getter():
            return container[0]

        def setter(fn):
            container[0] = fn(container[0])

        return getter, setter

    mo.state.side_effect = _make_state
    return mo


def _make_check(mock_mo):
    """Create a standalone check function using a mock mo."""
    from mograder import runtime

    with patch.object(runtime, "mo", mock_mo):
        from mograder.runtime import check

        # We need to call check while mo is patched, so return a wrapper
        def _check(label, checks):
            with patch.object(runtime, "mo", mock_mo):
                return check(label, checks)

        return _check


# --- standalone check() ---


def test_check_pass():
    mo = _mock_mo()
    _check = _make_check(mo)
    result = _check("Q1: Foo", [(True, "ok")])
    content, kind = result
    assert kind == "success"
    assert "all checks passed" in content


def test_check_fail():
    mo = _mock_mo()
    _check = _make_check(mo)
    result = _check("Q1: Foo", [(False, "bad thing")])
    content, kind = result
    assert kind == "danger"
    assert "bad thing" in content


def test_check_wait():
    mo = _mock_mo()
    _check = _make_check(mo)
    result = _check("Q1: Foo", [])
    content, kind = result
    assert kind == "warn"
    assert "waiting" in content


def test_check_mixed():
    mo = _mock_mo()
    _check = _make_check(mo)
    result = _check("Q1: Foo", [(True, "a"), (False, "b")])
    content, kind = result
    assert kind == "danger"
    assert "b" in content


# --- Grader.check() ---


def test_grader_check_pass():
    mo = _mock_mo()
    grader = Grader(mo, {"Q1": 10, "Q2": 15})
    result = grader.check("Q1: Array creation", [(True, "ok")])
    content, kind = result
    assert kind == "success"
    assert "[10/10 marks]" in content


def test_grader_check_fail():
    mo = _mock_mo()
    grader = Grader(mo, {"Q1": 10})
    result = grader.check("Q1: Array creation", [(False, "wrong")])
    content, kind = result
    assert kind == "danger"
    assert "[0/10 marks]" in content


def test_grader_check_wait():
    mo = _mock_mo()
    grader = Grader(mo, {"Q1": 10})
    result = grader.check("Q1: Array creation", [])
    content, kind = result
    assert kind == "warn"
    assert "[0/10 marks]" in content


def test_grader_check_no_marks_for_key():
    """Labels not in marks dict get no badge."""
    mo = _mock_mo()
    grader = Grader(mo, {"Q1": 10})
    result = grader.check("Q99: Unknown", [(True, "ok")])
    content, kind = result
    assert kind == "success"
    assert "marks]" not in content


# --- Grader state tracking ---


def test_grader_state_tracking():
    mo = _mock_mo()
    grader = Grader(mo, {"Q1": 10, "Q2": 15})
    grader.check("Q1: Array creation", [(True, "ok")])
    grader.check("Q2: Diff", [(False, "bad")])
    # Read state via the getter
    state = grader._state()
    assert state == {"Q1": True, "Q2": False}


def test_grader_state_updates():
    mo = _mock_mo()
    grader = Grader(mo, {"Q1": 10})
    grader.check("Q1: Foo", [(False, "fail")])
    assert grader._state()["Q1"] is False
    grader.check("Q1: Foo", [(True, "ok")])
    assert grader._state()["Q1"] is True


# --- Grader.scores() ---


def test_grader_scores_all_pass():
    mo = _mock_mo()
    grader = Grader(mo, {"Q1": 10, "Q2": 15})
    grader.check("Q1: Foo", [(True, "ok")])
    grader.check("Q2: Bar", [(True, "ok")])
    result = grader.scores()
    content, kind = result
    assert kind == "success"
    assert "10/10" in content
    assert "15/15" in content
    assert "**25/25**" in content


def test_grader_scores_partial():
    mo = _mock_mo()
    grader = Grader(mo, {"Q1": 10, "Q2": 15})
    grader.check("Q1: Foo", [(True, "ok")])
    grader.check("Q2: Bar", [(False, "bad")])
    result = grader.scores()
    content, kind = result
    assert kind == "neutral"
    assert "**10/25**" in content
    assert "PASS" in content
    assert "FAIL" in content


# --- hint() ---


def test_hint_single():
    mo = _mock_mo()
    mo.accordion.side_effect = lambda items: items
    from mograder import runtime

    with patch.object(runtime, "mo", mo):
        from mograder.runtime import hint

        with patch.object(runtime, "mo", mo):
            result = hint("Think about insertion order")
    assert "Hint" in result
    assert len(result) == 1


def test_hint_multiple():
    mo = _mock_mo()
    mo.accordion.side_effect = lambda items: items
    from mograder import runtime

    with patch.object(runtime, "mo", mo):
        from mograder.runtime import hint

        with patch.object(runtime, "mo", mo):
            result = hint("First hint", "Second hint", "Third hint")
    assert "Hint 1" in result
    assert "Hint 2" in result
    assert "Hint 3" in result
    assert len(result) == 3


def test_hint_renders_markdown():
    mo = _mock_mo()
    mo.accordion.side_effect = lambda items: items
    from mograder import runtime

    with patch.object(runtime, "mo", mo):
        from mograder.runtime import hint

        with patch.object(runtime, "mo", mo):
            hint("Some **bold** text", "More text")
    # mo.md should have been called for each hint string
    assert mo.md.call_count >= 2


# --- Grader.scores() ---


def test_grader_scores_unattempted():
    mo = _mock_mo()
    grader = Grader(mo, {"Q1": 10, "Q2": 15})
    # No checks run — all unattempted
    result = grader.scores()
    content, kind = result
    assert kind == "neutral"
    assert "**0/25**" in content
    assert "\u2014" in content  # em dash for unattempted
