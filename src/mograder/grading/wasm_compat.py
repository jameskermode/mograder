"""WASM compatibility checking for marimo notebooks.

Determines whether a notebook's dependencies can run in the browser
via Pyodide/WASM. Uses a static blocklist of packages with native
extensions that are known to be incompatible.
"""

import re
from pathlib import Path

# Packages known to have native extensions that don't work in WASM/Pyodide
WASM_INCOMPATIBLE_DEPS: set[str] = {
    # JAX ecosystem (native CUDA/XLA extensions)
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
    # PyTorch ecosystem
    "torch",
    "pytorch",
    "torchaudio",
    "torchvision",
    "torchsummary",
    "torchviz",
    # TensorFlow
    "tensorflow",
    "tensorflow-gpu",
    # Gaussian process libraries (depend on JAX)
    "tinygp",
    # Other ML with native code
    "numba",
    "cython",
    # File system / OS-level (native extensions)
    "watchdog",
    "psutil",
    "watchfiles",
    # Database drivers with native code
    "psycopg2",
    "psycopg2-binary",
    "mysqlclient",
    "pymssql",
    # Image processing with native code
    "opencv-python",
    "opencv-python-headless",
    "cv2",
    # XML/parsing with native code
    "lxml",
    # Cryptography with native code
    "cryptography",
    "bcrypt",
    "pynacl",
    # Networking/async with native code
    "grpcio",
    "uvloop",
    "gevent",
    # Data formats with native code
    "pyarrow",
    "fastparquet",
    "h5py",
    "tables",
    # Atomistic simulation (Fortran extensions)
    "atomistica",
    # Visualisation with native code
    "graphviz",
}


def extract_dependencies(content: str) -> list[str]:
    """Extract package names from PEP 723 script metadata.

    Parses the ``# /// script`` block for ``dependencies = [...]``
    and returns normalized package names (lowercase, underscores → hyphens).
    """
    metadata_match = re.search(r"# /// script\n(.*?)# ///", content, re.DOTALL)
    if not metadata_match:
        return []

    metadata = metadata_match.group(1)

    # Extract everything between `dependencies = [` and the matching `]`
    # by first collecting all quoted strings from the deps block.
    # We find `dependencies = [` then greedily collect quoted strings
    # until we hit `# ]` (which closes the array in PEP 723 format).
    deps_str = ""
    in_deps = False
    for line in metadata.splitlines():
        stripped = line.lstrip("#").strip()
        if not in_deps:
            if stripped.startswith("dependencies"):
                in_deps = True
                # Get content after the opening [
                idx = stripped.find("[")
                if idx >= 0:
                    deps_str += stripped[idx + 1 :]
            continue
        if stripped == "]" or stripped == "],":
            break
        deps_str += " " + stripped
    dependencies = []

    for dep in re.findall(r'"([^"]+)"', deps_str):
        # Remove extras like [dev] and version specifiers
        pkg_name = re.split(r"[\[<>=!;]", dep)[0].strip().lower()
        pkg_name = pkg_name.replace("_", "-")
        if pkg_name:
            dependencies.append(pkg_name)

    return dependencies


def extract_imports(content: str) -> list[str]:
    """Extract imported module names from Python source code.

    Finds top-level ``import X`` and ``from X import ...`` statements.
    """
    imports = []
    for match in re.finditer(r"^\s*(?:import|from)\s+(\w+)", content, re.MULTILINE):
        imports.append(match.group(1).lower())
    return imports


def check_wasm_compatible(notebook_path: Path) -> tuple[bool, list[str]]:
    """Check if a notebook's dependencies are WASM-compatible.

    Uses a static blocklist — no network calls.

    Returns:
        Tuple of (is_compatible, list_of_blocking_deps).
    """
    content = notebook_path.read_text()
    blockers: list[str] = []

    # Check declared dependencies
    for dep in extract_dependencies(content):
        dep_normalized = dep.lower().replace("_", "-")
        if dep_normalized in WASM_INCOMPATIBLE_DEPS and dep not in blockers:
            blockers.append(dep)

    # Check imports (catches undeclared deps)
    for imp in extract_imports(content):
        imp_normalized = imp.lower().replace("_", "-")
        if imp_normalized in WASM_INCOMPATIBLE_DEPS and imp not in blockers:
            blockers.append(imp)

    return (len(blockers) == 0, blockers)
