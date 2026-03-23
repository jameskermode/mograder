/**
 * Pyodide compatibility smoke test.
 *
 * Installs mograder from PyPI into a Pyodide environment and verifies that
 * the runtime API matches what the release notebooks in this repo expect.
 *
 * This catches the case where runtime.py changes (e.g. a new function
 * signature) but hasn't been published to PyPI yet — which breaks WASM
 * demos since Pyodide always fetches the latest PyPI version.
 *
 * Usage:  node tests/test_pyodide_compat.js
 */

const { loadPyodide } = require("pyodide");
const fs = require("fs");
const path = require("path");

async function main() {
  console.log("Loading Pyodide...");
  const pyodide = await loadPyodide();
  await pyodide.loadPackage("micropip");

  // Install only the mograder wheel (no deps) — in real WASM usage marimo
  // is already loaded by the marimo WASM runtime, and mograder.runtime only
  // needs marimo + stdlib.
  console.log("Installing mograder from PyPI (no deps)...");
  await pyodide.runPythonAsync(`
import micropip
await micropip.install("mograder", deps=False)
print(f"Installed mograder {micropip.list()['mograder'].version}")
  `);

  // Read release notebooks and detect which API patterns are used
  const releaseDir = path.join(__dirname, "..", "examples", "release");
  const notebooks = [];
  for (const dir of fs.readdirSync(releaseDir)) {
    const nb = path.join(releaseDir, dir, `${dir}.py`);
    if (fs.existsSync(nb)) notebooks.push(nb);
  }

  if (notebooks.length === 0) {
    console.error("ERROR: No release notebooks found");
    process.exit(1);
  }

  let usesCheck = false;
  let usesGrader = false;
  for (const nb of notebooks) {
    const content = fs.readFileSync(nb, "utf-8");
    if (content.includes("from mograder.runtime import check")) usesCheck = true;
    if (content.includes("from mograder.runtime import Grader")) usesGrader = true;
  }

  console.log(`Release notebooks use: check=${usesCheck}, Grader=${usesGrader}`);

  // Verify the API signatures match what release notebooks expect.
  // We can't fully import runtime.py (it does `import marimo as mo` at
  // module level and marimo isn't installed), so we inspect the source
  // via importlib without executing it.
  console.log("\nChecking runtime API signatures...");
  await pyodide.runPythonAsync(`
import ast, importlib.resources

# Read the installed runtime.py source
source = importlib.resources.files("mograder").joinpath("runtime.py").read_text()
tree = ast.parse(source)

# Extract top-level function and class definitions
defs = {}
for node in ast.iter_child_nodes(tree):
    if isinstance(node, ast.FunctionDef):
        defs[node.name] = [arg.arg for arg in node.args.args]
    elif isinstance(node, ast.ClassDef):
        defs[node.name] = {}
        for item in node.body:
            if isinstance(item, ast.FunctionDef):
                defs[node.name][item.name] = [arg.arg for arg in item.args.args]

# --- Verify standalone check() ---
assert "check" in defs, "check() function not found in runtime.py"
check_params = defs["check"]
print(f"  check({', '.join(check_params)})")
assert "label" in check_params, f"check() missing 'label': {check_params}"
assert "checks" in check_params, f"check() missing 'checks': {check_params}"
print("  OK: check() signature matches")

# --- Verify Grader class ---
assert "Grader" in defs, "Grader class not found in runtime.py"
grader_methods = defs["Grader"]

# __init__ should accept (self, marks) — NOT (self, mo, marks)
init_params = grader_methods.get("__init__", [])
print(f"  Grader.__init__({', '.join(init_params)})")
assert "marks" in init_params, f"Grader.__init__() missing 'marks': {init_params}"
assert "mo" not in init_params, (
    f"Grader.__init__() still has 'mo' param (outdated PyPI version): {init_params}"
)

# check method
assert "check" in grader_methods, "Grader missing check() method"
check_params = grader_methods["check"]
print(f"  Grader.check({', '.join(check_params)})")
assert "label" in check_params, f"Grader.check() missing 'label': {check_params}"
assert "checks" in check_params, f"Grader.check() missing 'checks': {check_params}"

# scores method
assert "scores" in grader_methods, "Grader missing scores() method"
print("  OK: Grader API matches")
  `);

  console.log("\nAll Pyodide compatibility checks passed.");
}

main().catch((err) => {
  console.error("FAILED:", err.message || err);
  process.exit(1);
});
