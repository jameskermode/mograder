"""Tests for AST-based safety scanner."""

from mograder.safety import check_safety


def test_safe_code():
    """Numpy/matplotlib imports and basic math → safe."""
    code = (
        "import numpy as np\nimport matplotlib.pyplot as plt\nx = np.array([1,2,3])\n"
    )
    result = check_safety(code)
    assert result.safe


def test_denied_import():
    """import os → finding."""
    result = check_safety("import os\n")
    assert not result.safe
    assert any("os" in f.description for f in result.findings)


def test_denied_import_from():
    """from subprocess import run → finding."""
    result = check_safety("from subprocess import run\n")
    assert not result.safe
    assert any("subprocess" in f.description for f in result.findings)


def test_denied_import_submodule():
    """import os.path → finding."""
    result = check_safety("import os.path\n")
    assert not result.safe
    assert any("os" in f.description for f in result.findings)


def test_denied_builtin_eval():
    """eval("1+1") → finding."""
    result = check_safety('eval("1+1")\n')
    assert not result.safe
    assert any("eval" in f.description for f in result.findings)


def test_denied_builtin_exec():
    """exec("...") → finding."""
    result = check_safety('exec("pass")\n')
    assert not result.safe
    assert any("exec" in f.description for f in result.findings)


def test_denied_dunder_import():
    """__import__("os") → finding."""
    result = check_safety('__import__("os")\n')
    assert not result.safe
    assert any("__import__" in f.description for f in result.findings)


def test_denied_open():
    """open("/etc/passwd") → finding."""
    result = check_safety('open("/etc/passwd")\n')
    assert not result.safe
    assert any("open" in f.description for f in result.findings)


def test_multiple_findings():
    """Several violations → all reported."""
    code = "import os\nimport subprocess\neval('1')\n"
    result = check_safety(code)
    assert len(result.findings) >= 3


def test_inside_function():
    """Dangerous code inside def → still detected."""
    code = "def f():\n    import os\n    eval('x')\n"
    result = check_safety(code)
    assert not result.safe
    assert len(result.findings) >= 2


def test_syntax_error():
    """Unparseable code → safe (don't block, marimo will fail)."""
    result = check_safety("def f(\n")
    assert result.safe


def test_empty_source():
    """Empty string → safe."""
    result = check_safety("")
    assert result.safe
