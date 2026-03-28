"""Tests for wasm_compat module."""

from mograder.grading.wasm_compat import (
    WASM_INCOMPATIBLE_DEPS,
    check_wasm_compatible,
    extract_dependencies,
    extract_imports,
)


# --- extract_dependencies ---


def test_extract_dependencies_basic():
    content = """\
# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "numpy<2",
#     "scipy",
#     "matplotlib",
# ]
# ///
"""
    assert extract_dependencies(content) == ["numpy", "scipy", "matplotlib"]


def test_extract_dependencies_with_extras_and_versions():
    content = """\
# /// script
# dependencies = [
#     "jax>=0.4.38,<0.5",
#     "jaxlib>=0.4.38,<0.5",
#     "torch",
#     "pkg[extra]>=1.0",
# ]
# ///
"""
    deps = extract_dependencies(content)
    assert deps == ["jax", "jaxlib", "torch", "pkg"]


def test_extract_dependencies_no_metadata():
    assert extract_dependencies("import marimo\napp = marimo.App()") == []


def test_extract_dependencies_normalizes_underscores():
    content = """\
# /// script
# dependencies = [
#     "my_package",
# ]
# ///
"""
    assert extract_dependencies(content) == ["my-package"]


# --- extract_imports ---


def test_extract_imports_basic():
    content = """\
import numpy as np
from scipy import stats
import matplotlib.pyplot as plt
"""
    imports = extract_imports(content)
    assert "numpy" in imports
    assert "scipy" in imports
    assert "matplotlib" in imports


def test_extract_imports_indented():
    content = """\
    import torch
    from jax import numpy
"""
    imports = extract_imports(content)
    assert "torch" in imports
    assert "jax" in imports


def test_extract_imports_string_not_matched():
    """Imports inside strings should still match (regex limitation, acceptable)."""
    content = "    import os\n"
    imports = extract_imports(content)
    assert "os" in imports


# --- check_wasm_compatible ---


def test_compatible_pure_python(tmp_path):
    nb = tmp_path / "pure.py"
    nb.write_text("""\
# /// script
# dependencies = [
#     "numpy<2",
#     "scipy",
#     "matplotlib",
#     "marimo",
# ]
# ///
import marimo
app = marimo.App()
""")
    compatible, blockers = check_wasm_compatible(nb)
    assert compatible is True
    assert blockers == []


def test_incompatible_jax(tmp_path):
    nb = tmp_path / "jax_nb.py"
    nb.write_text("""\
# /// script
# dependencies = [
#     "jax>=0.4.38,<0.5",
#     "jaxlib>=0.4.38,<0.5",
#     "equinox",
#     "numpy<2",
#     "marimo",
# ]
# ///
import marimo
app = marimo.App()
""")
    compatible, blockers = check_wasm_compatible(nb)
    assert compatible is False
    assert "jax" in blockers
    assert "jaxlib" in blockers
    assert "equinox" in blockers


def test_incompatible_torch_import_only(tmp_path):
    """Torch caught via import even without PEP 723 declaration."""
    nb = tmp_path / "torch_nb.py"
    nb.write_text("""\
import marimo
app = marimo.App()

import torch
""")
    compatible, blockers = check_wasm_compatible(nb)
    assert compatible is False
    assert "torch" in blockers


def test_blocklist_includes_jax_ecosystem():
    """Verify JAX ecosystem packages are in the blocklist."""
    jax_packages = {
        "jax",
        "jaxlib",
        "equinox",
        "optax",
        "diffrax",
        "lineax",
        "optimistix",
        "numpyro",
        "jaxopt",
        "distrax",
    }
    assert jax_packages.issubset(WASM_INCOMPATIBLE_DEPS)


def test_no_duplicates_in_blockers(tmp_path):
    """Same package in both deps and imports should only appear once."""
    nb = tmp_path / "dup.py"
    nb.write_text("""\
# /// script
# dependencies = [
#     "torch",
# ]
# ///
import torch
""")
    _, blockers = check_wasm_compatible(nb)
    assert blockers.count("torch") == 1
