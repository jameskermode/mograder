"""Tests for mograder.runtime — check() and Grader."""

from unittest.mock import MagicMock, patch

import pytest

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


@pytest.fixture
def mock_mo():
    """Patch mograder.runtime.mo with a mock for the duration of the test."""
    mo = _mock_mo()
    with patch("mograder.runtime.mo", mo):
        yield mo


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


def test_grader_check_pass(mock_mo):
    grader = Grader({"Q1": 10, "Q2": 15})
    result = grader.check("Q1: Array creation", [(True, "ok")])
    content, kind = result
    assert kind == "success"
    assert "[10/10 marks]" in content


def test_grader_check_fail(mock_mo):
    grader = Grader({"Q1": 10})
    result = grader.check("Q1: Array creation", [(False, "wrong")])
    content, kind = result
    assert kind == "danger"
    assert "[0/10 marks]" in content


def test_grader_check_wait(mock_mo):
    grader = Grader({"Q1": 10})
    result = grader.check("Q1: Array creation", [])
    content, kind = result
    assert kind == "warn"
    assert "[0/10 marks]" in content


def test_grader_check_no_marks_for_key(mock_mo):
    """Labels not in marks dict get no badge."""
    grader = Grader({"Q1": 10})
    result = grader.check("Q99: Unknown", [(True, "ok")])
    content, kind = result
    assert kind == "success"
    assert "marks]" not in content


# --- Grader state tracking ---


def test_grader_state_tracking(mock_mo):
    grader = Grader({"Q1": 10, "Q2": 15})
    grader.check("Q1: Array creation", [(True, "ok")])
    grader.check("Q2: Diff", [(False, "bad")])
    # Read state via the getter — now (earned_weight, total_weight) tuples
    state = grader._state()
    assert state == {"Q1": (1.0, 1.0), "Q2": (0, 1.0)}


def test_grader_state_updates(mock_mo):
    grader = Grader({"Q1": 10})
    grader.check("Q1: Foo", [(False, "fail")])
    assert grader._state()["Q1"] == (0, 1.0)
    grader.check("Q1: Foo", [(True, "ok")])
    assert grader._state()["Q1"] == (1.0, 1.0)


# --- Grader.scores() ---


def test_grader_scores_all_pass(mock_mo):
    grader = Grader({"Q1": 10, "Q2": 15})
    grader.check("Q1: Foo", [(True, "ok")])
    grader.check("Q2: Bar", [(True, "ok")])
    result = grader.scores()
    content, kind = result
    assert kind == "success"
    assert "10/10" in content
    assert "15/15" in content
    assert "**25/25**" in content


def test_grader_scores_partial(mock_mo):
    grader = Grader({"Q1": 10, "Q2": 15})
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


# --- Partial credit ---


def test_grader_check_partial_credit(mock_mo):
    """3/5 checks pass (uniform weight), 10 marks → badge [6/10 marks]."""
    grader = Grader({"Q1": 10})
    result = grader.check(
        "Q1: Array creation",
        [(True, "a"), (True, "b"), (True, "c"), (False, "d"), (False, "e")],
    )
    content, kind = result
    assert "[6/10 marks]" in content
    assert kind == "info"  # partial → blue


def test_grader_check_weighted_partial(mock_mo):
    """Weighted checks → correct fractional marks."""
    grader = Grader({"Q1": 10})
    result = grader.check(
        "Q1: Foo",
        [
            (True, "a"),  # weight 1
            (True, "b"),  # weight 1
            (False, "c", 3),  # weight 3
        ],
    )
    content, kind = result
    # earned_w=2, total_w=5, marks=round(10*2/5,1)=4.0
    assert "[4/10 marks]" in content


def test_grader_check_all_pass_unchanged(mock_mo):
    """All pass → full marks, green."""
    grader = Grader({"Q1": 10})
    result = grader.check("Q1: Foo", [(True, "a"), (True, "b")])
    content, kind = result
    assert "[10/10 marks]" in content
    assert kind == "success"


def test_grader_check_all_fail_unchanged(mock_mo):
    """None pass → 0 marks, red."""
    grader = Grader({"Q1": 10})
    result = grader.check("Q1: Foo", [(False, "a"), (False, "b")])
    content, kind = result
    assert "[0/10 marks]" in content
    assert kind == "danger"


def test_grader_scores_partial_credit(mock_mo):
    """Scores table shows fractional earned marks."""
    grader = Grader({"Q1": 10, "Q2": 15})
    grader.check("Q1: Foo", [(True, "a"), (True, "b"), (False, "c")])  # 2/3 → 6.7
    grader.check("Q2: Bar", [(True, "ok")])  # 1/1 → 15
    result = grader.scores()
    content, kind = result
    assert "6.7/10" in content
    assert "15/15" in content
    assert "PARTIAL" in content
    assert "PASS" in content


def test_grader_scores_backward_compat_bool(mock_mo):
    """Bool state values (from old code) still work in scores()."""
    grader = Grader({"Q1": 10, "Q2": 15})
    # Manually set state with bools (old format)
    grader._set(lambda prev: {"Q1": True, "Q2": False})
    result = grader.scores()
    content, kind = result
    assert "10/10" in content
    assert "0/15" in content
    assert "**10/25**" in content


def test_check_sidecar_includes_weights(tmp_path):
    """Sidecar JSONL has earned_weight/total_weight."""
    import json
    import os

    from mograder import runtime

    sidecar = tmp_path / "sidecar.jsonl"
    os.environ["MOGRADER_SIDECAR_PATH"] = str(sidecar)
    try:
        runtime._write_sidecar("Q1: Foo", "success", [], 3.0, 5.0)
    finally:
        del os.environ["MOGRADER_SIDECAR_PATH"]

    record = json.loads(sidecar.read_text().strip())
    assert record["earned_weight"] == 3.0
    assert record["total_weight"] == 5.0


def test_empty_check_writes_warn_sidecar(tmp_path, mock_mo):
    """check() with empty list writes a 'warn' entry to the sidecar."""
    import json
    import os

    from mograder import runtime

    sidecar = tmp_path / "sidecar.jsonl"
    os.environ["MOGRADER_SIDECAR_PATH"] = str(sidecar)
    try:
        runtime.check("Q1: Foo", [])
    finally:
        del os.environ["MOGRADER_SIDECAR_PATH"]

    record = json.loads(sidecar.read_text().strip())
    assert record["label"] == "Q1: Foo"
    assert record["status"] == "warn"


def test_grader_empty_check_writes_warn_sidecar(tmp_path, mock_mo):
    """Grader.check() with empty list writes a 'warn' entry to the sidecar."""
    import json
    import os

    sidecar = tmp_path / "sidecar.jsonl"
    os.environ["MOGRADER_SIDECAR_PATH"] = str(sidecar)
    try:
        grader = Grader({"Q1": 10})
        grader.check("Q1: Foo", [])
    finally:
        del os.environ["MOGRADER_SIDECAR_PATH"]

    record = json.loads(sidecar.read_text().strip())
    assert record["label"] == "Q1: Foo"
    assert record["status"] == "warn"


def test_check_weighted_tuple_parsing():
    """(bool, str, weight) tuples parsed correctly."""
    from mograder.runtime import _parse_checks

    parsed = _parse_checks([(True, "a", 3), (False, "b", 2.5)])
    assert parsed == [(True, "a", 3.0), (False, "b", 2.5)]


def test_check_mixed_tuple_formats():
    """Mix of 2-tuple and 3-tuple in same check list."""
    from mograder.runtime import _parse_checks

    parsed = _parse_checks([(True, "a"), (False, "b", 5)])
    assert parsed == [(True, "a", 1.0), (False, "b", 5.0)]


def test_grader_scores_unattempted(mock_mo):
    grader = Grader({"Q1": 10, "Q2": 15})
    # No checks run — all unattempted
    result = grader.scores()
    content, kind = result
    assert kind == "neutral"
    assert "**0/25**" in content
    assert "\u2014" in content  # em dash for unattempted
