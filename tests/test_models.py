from pathlib import Path

from mograder.models import CheckResult, NotebookResult


def test_check_result_defaults():
    cr = CheckResult(label="Q1: Foo", status="success")
    assert cr.label == "Q1: Foo"
    assert cr.status == "success"
    assert cr.details == []


def test_check_result_with_details():
    cr = CheckResult(label="Q2: Bar", status="danger", details=["x != y"])
    assert cr.details == ["x != y"]


def test_notebook_result_defaults():
    nr = NotebookResult(path=Path("test.py"))
    assert nr.path == Path("test.py")
    assert nr.checks == []
    assert nr.export_ok is True
    assert nr.export_error == ""
    assert nr.cell_errors == 0
    assert nr.html_path is None


def test_notebook_result_with_checks():
    checks = [CheckResult("Q1", "success"), CheckResult("Q2", "danger")]
    nr = NotebookResult(path=Path("s.py"), checks=checks, cell_errors=2)
    assert len(nr.checks) == 2
    assert nr.cell_errors == 2
