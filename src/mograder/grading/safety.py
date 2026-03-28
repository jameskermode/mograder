"""AST-based safety scanner for submitted notebook code."""

import ast
import dataclasses


@dataclasses.dataclass
class SafetyFinding:
    line: int
    description: str


@dataclasses.dataclass
class SafetyResult:
    findings: list[SafetyFinding]

    @property
    def safe(self) -> bool:
        return not self.findings


DENIED_MODULES = frozenset(
    {
        "os",
        "subprocess",
        "shutil",
        "sys",
        "ctypes",
        "socket",
        "http",
        "urllib",
        "requests",
        "pathlib",
        "signal",
        "multiprocessing",
        "threading",
        "code",
        "codeop",
        "importlib",
        "pkgutil",
        "inspect",
        "builtins",
        "io",
        "tempfile",
        "glob",
        "fnmatch",
        "pickle",
        "shelve",
        "marshal",
    }
)

DENIED_BUILTINS = frozenset(
    {
        "eval",
        "exec",
        "compile",
        "__import__",
        "breakpoint",
        "exit",
        "quit",
        "open",
        "input",
    }
)


class _SafetyVisitor(ast.NodeVisitor):
    def __init__(self):
        self.findings: list[SafetyFinding] = []

    def visit_Import(self, node: ast.Import):
        for alias in node.names:
            top = alias.name.split(".")[0]
            if top in DENIED_MODULES:
                self.findings.append(
                    SafetyFinding(node.lineno, f"denied import: {alias.name}")
                )
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom):
        if node.module:
            top = node.module.split(".")[0]
            if top in DENIED_MODULES:
                self.findings.append(
                    SafetyFinding(node.lineno, f"denied import: {node.module}")
                )
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call):
        if isinstance(node.func, ast.Name) and node.func.id in DENIED_BUILTINS:
            self.findings.append(
                SafetyFinding(node.lineno, f"denied builtin call: {node.func.id}")
            )
        self.generic_visit(node)


def check_safety(source: str) -> SafetyResult:
    """Scan source code for dangerous patterns.

    Returns a SafetyResult with any findings. If the code cannot be parsed,
    returns safe (the notebook runner will report the syntax error).
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return SafetyResult(findings=[])

    visitor = _SafetyVisitor()
    visitor.visit(tree)
    return SafetyResult(findings=visitor.findings)
