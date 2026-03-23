"""Tests for hub warm cache / PEP 723 dep parsing (Phase 6)."""

from mograder.hub.spawner import parse_pep723_deps


def test_parses_pep723_deps():
    """Extracts dependencies from PEP 723 inline script metadata."""
    source = """# /// script
# dependencies = [
#     "numpy>=1.26",
#     "jax",
#     "marimo",
# ]
# ///

import numpy as np
"""
    deps = parse_pep723_deps(source)
    assert deps == ["numpy>=1.26", "jax", "marimo"]


def test_no_deps():
    """No PEP 723 block returns empty list."""
    deps = parse_pep723_deps("import numpy as np\n")
    assert deps == []


def test_empty_deps():
    """Empty dependencies list returns empty list."""
    source = """# /// script
# dependencies = []
# ///

print("hello")
"""
    deps = parse_pep723_deps(source)
    assert deps == []


def test_multiple_metadata_fields():
    """Only dependencies are extracted, other fields ignored."""
    source = """# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "numpy",
# ]
# ///
"""
    deps = parse_pep723_deps(source)
    assert deps == ["numpy"]
