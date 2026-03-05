from mograder.parser import count_cell_errors, parse_check_results


def test_parse_check_results(fixtures_dir):
    html = (fixtures_dir / "sample_export.html").read_text()
    results = parse_check_results(html)
    assert len(results) == 3
    labels = [r.label for r in results]
    assert "Q1: Data visualisation" in labels
    assert "Q2: Model evaluation" in labels
    assert "Q3: Loss function" in labels


def test_parse_check_statuses(fixtures_dir):
    html = (fixtures_dir / "sample_export.html").read_text()
    results = parse_check_results(html)
    status_map = {r.label.split(":")[0]: r.status for r in results}
    assert status_map["Q1"] == "success"
    assert status_map["Q2"] == "danger"
    assert status_map["Q3"] == "warn"


def test_parse_deduplication(fixtures_dir):
    """Q1 appears twice in the fixture; should be deduplicated."""
    html = (fixtures_dir / "sample_export.html").read_text()
    results = parse_check_results(html)
    q1_results = [r for r in results if r.label.startswith("Q1")]
    assert len(q1_results) == 1


def test_parse_ordering(fixtures_dir):
    html = (fixtures_dir / "sample_export.html").read_text()
    results = parse_check_results(html)
    labels = [r.label for r in results]
    assert labels == sorted(labels)


def test_parse_empty_html():
    assert parse_check_results("") == []
    assert parse_check_results("<html></html>") == []


def test_count_cell_errors(fixtures_dir):
    html = (fixtures_dir / "sample_export.html").read_text()
    assert count_cell_errors(html) == 2


def test_count_cell_errors_none():
    assert count_cell_errors("<html>no errors</html>") == 0
