"""Workshop notebooks with encrypted solutions and progressive answer checking.

Provides crypto primitives for answer hashing and solution encryption,
exercise parsing from source notebooks, and notebook generation for
interactive workshop use (including WASM deployment on GitHub Pages).
"""

import ast
import base64
import hashlib
import json
import re
import secrets
from pathlib import Path

from mograder.markers import (
    SOLUTION_BEGIN,
    SOLUTION_END,
    _inject_before_main,
    strip_solutions,
    validate_markers,
)

ANSWERS_MARKER = "# === MOGRADER: ANSWERS ==="
_WORKSHOP_CHECKER_PREFIX = "# === MOGRADER: WORKSHOP CHECKER"

# Reuse pattern from integrity.py
_CHECK_CALL_RE = re.compile(r"""check\(\s*["']([^"':]+)""")


# ---------------------------------------------------------------------------
# Crypto primitives (pure Python, Pyodide-compatible)
# ---------------------------------------------------------------------------


def normalize_answer(answer, tolerance=6) -> str:
    """JSON-serialize answer, rounding floats to *tolerance* decimal places."""
    return json.dumps(_round_floats(answer, tolerance), sort_keys=True)


def _round_floats(obj, tolerance):
    """Recursively round floats in nested structures."""
    if isinstance(obj, float):
        return round(obj, tolerance)
    if isinstance(obj, list):
        return [_round_floats(x, tolerance) for x in obj]
    if isinstance(obj, dict):
        return {k: _round_floats(v, tolerance) for k, v in obj.items()}
    if isinstance(obj, tuple):
        return [_round_floats(x, tolerance) for x in obj]
    return obj


def make_hash(normalized: str, salt: str) -> str:
    """SHA256(salt + ':' + normalized) -> hex digest."""
    return hashlib.sha256(f"{salt}:{normalized}".encode()).hexdigest()


def xor_encrypt(data: str, key: str) -> str:
    """XOR encrypt *data* with *key*, return base64-encoded ciphertext."""
    if not data:
        return ""
    data_bytes = data.encode("utf-8")
    key_bytes = key.encode("utf-8") or b"\x00"
    result = bytes(d ^ key_bytes[i % len(key_bytes)] for i, d in enumerate(data_bytes))
    return base64.b64encode(result).decode("ascii")


def xor_decrypt(ciphertext: str, key: str) -> str:
    """Decode base64 *ciphertext*, XOR with *key*, return plaintext."""
    if not ciphertext:
        return ""
    data_bytes = base64.b64decode(ciphertext)
    key_bytes = key.encode("utf-8") or b"\x00"
    result = bytes(d ^ key_bytes[i % len(key_bytes)] for i, d in enumerate(data_bytes))
    return result.decode("utf-8")


def check_answer(
    exercise_id: str,
    submitted_answer,
    exercises: dict,
    released_keys: dict,
    salt: str,
) -> tuple[str, str | None]:
    """Check answer against exercises dict.

    Returns ("correct", solution) | ("released", solution) | ("incorrect", None).
    """
    ex = exercises.get(exercise_id)
    if ex is None:
        return ("incorrect", None)

    expected_hash = ex["hash"]
    encrypted_solution = ex["solution"]

    # Check if answer is correct
    normalized = normalize_answer(submitted_answer)
    answer_hash = make_hash(normalized, salt)

    if answer_hash == expected_hash:
        solution = xor_decrypt(encrypted_solution, answer_hash)
        return ("correct", solution)

    # Check if key has been released
    if exercise_id in released_keys:
        released_normalized = released_keys[exercise_id]
        released_hash = make_hash(released_normalized, salt)
        if released_hash == expected_hash:
            solution = xor_decrypt(encrypted_solution, released_hash)
            return ("released", solution)

    return ("incorrect", None)


def fetch_released_keys(url: str = "./keys.json") -> dict:
    """Fetch released keys. Uses pyodide.http.pyfetch in WASM, urllib locally."""
    try:
        # Try Pyodide first (WASM environment)
        from pyodide.http import open_url  # type: ignore[import-not-found]

        text = open_url(url)
        return json.loads(text)
    except ImportError:
        pass

    import urllib.request

    try:
        with urllib.request.urlopen(url) as resp:  # noqa: S310
            return json.loads(resp.read().decode())
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# Answer parsing (generate-time only)
# ---------------------------------------------------------------------------


def parse_answers_metadata(source_lines: list[str]) -> dict | None:
    """Extract _answers = {...} from the ANSWERS_MARKER cell.

    Same approach as cells.parse_marks_metadata for _marks.
    """
    text = "".join(source_lines)
    if ANSWERS_MARKER not in text:
        return None

    marker_idx = text.index(ANSWERS_MARKER)
    section = text[marker_idx:]

    dict_match = re.search(r"_answers\s*=\s*(\{[^}]+\})", section)
    if not dict_match:
        return None
    try:
        answers = ast.literal_eval(dict_match.group(1))
    except (ValueError, SyntaxError):
        return None

    return answers if answers else None


def extract_solution_for_key(source_lines: list[str], key: str) -> str | None:
    """Find the ### BEGIN/END SOLUTION block in the cell whose check() label starts with key."""
    text = "".join(source_lines)

    # Split into cells by @app.cell boundaries
    cell_pattern = re.compile(r"@app\.cell(?:\([^)]*\))?\s*\ndef ")
    cell_starts = [m.start() for m in cell_pattern.finditer(text)]

    for i, start in enumerate(cell_starts):
        end = cell_starts[i + 1] if i + 1 < len(cell_starts) else len(text)
        cell_code = text[start:end]

        # Check if this cell has a check() call matching our key
        m = _CHECK_CALL_RE.search(cell_code)
        if not m or m.group(1).strip() != key:
            continue

        # Found the check cell — now look for the solution cell that precedes it
        # (the solution is typically in the cell just before the check cell)
        if i > 0:
            prev_start = cell_starts[i - 1]
            prev_code = text[prev_start:start]
            sol = _extract_solution_block(prev_code)
            if sol:
                return sol

    # Alternative: scan all cells for solution blocks containing the key
    for i, start in enumerate(cell_starts):
        end = cell_starts[i + 1] if i + 1 < len(cell_starts) else len(text)
        cell_code = text[start:end]
        if SOLUTION_BEGIN in cell_code:
            sol = _extract_solution_block(cell_code)
            if sol:
                # Check if the next cell has the matching check
                if i + 1 < len(cell_starts):
                    next_end = (
                        cell_starts[i + 2] if i + 2 < len(cell_starts) else len(text)
                    )
                    next_code = text[cell_starts[i + 1] : next_end]
                    nm = _CHECK_CALL_RE.search(next_code)
                    if nm and nm.group(1).strip() == key:
                        return sol

    return None


def _extract_solution_block(cell_code: str) -> str | None:
    """Extract text between BEGIN SOLUTION and END SOLUTION markers."""
    lines = cell_code.split("\n")
    in_solution = False
    solution_lines = []
    for line in lines:
        if line.strip() == SOLUTION_BEGIN:
            in_solution = True
            continue
        if line.strip() == SOLUTION_END:
            in_solution = False
            continue
        if in_solution:
            solution_lines.append(line)
    if solution_lines:
        # Dedent: find minimum indentation
        non_empty = [ln for ln in solution_lines if ln.strip()]
        if non_empty:
            min_indent = min(len(ln) - len(ln.lstrip()) for ln in non_empty)
            solution_lines = [
                ln[min_indent:] if len(ln) > min_indent else ln.lstrip()
                for ln in solution_lines
            ]
        return "\n".join(solution_lines).strip()
    return None


# ---------------------------------------------------------------------------
# Notebook generation (generate-time only)
# ---------------------------------------------------------------------------


def build_exercises_dict(
    answers: dict, salt: str, source_lines: list[str]
) -> dict[str, dict]:
    """Build EXERCISES dict with hashes + encrypted solutions for each answer key."""
    exercises = {}
    for key, answer in answers.items():
        normalized = normalize_answer(answer)
        answer_hash = make_hash(normalized, salt)

        solution_code = extract_solution_for_key(source_lines, key) or ""
        encrypted_solution = xor_encrypt(solution_code, answer_hash)

        exercises[key] = {
            "hash": answer_hash,
            "solution": encrypted_solution,
        }
    return exercises


def build_exercises_cell(exercises: dict, salt: str) -> str:
    """Return marimo cell source defining EXERCISES dict + SALT constant."""
    exercises_repr = json.dumps(exercises, indent=4)
    return f"""
@app.cell(hide_code=True)
def _():
    from mograder.workshop import check_answer, fetch_released_keys

    EXERCISES = {exercises_repr}

    SALT = {salt!r}
    return EXERCISES, SALT, check_answer, fetch_released_keys


"""


def build_checker_cell(key: str, title: str) -> str:
    """Return marimo cells with answer input + check button + status display for one question."""
    safe_key = key.replace('"', '\\"')
    return f'''
@app.cell(hide_code=True)
def _(mo):
    {_WORKSHOP_CHECKER_PREFIX} {key} ===
    input_{key} = mo.ui.text(label="Your answer for: {safe_key}")
    btn_{key} = mo.ui.run_button(label="Check")
    mo.hstack([input_{key}, btn_{key}])
    return (btn_{key}, input_{key})


@app.cell(hide_code=True)
def _(mo, input_{key}, btn_{key}, EXERCISES, SALT, released_keys, check_answer):
    import ast as _ast
    mo.stop(not btn_{key}.value)
    try:
        _answer = _ast.literal_eval(input_{key}.value)
    except Exception:
        _answer = input_{key}.value
    _status, _solution = check_answer("{safe_key}", _answer, EXERCISES, released_keys(), SALT)
    if _status == "correct":
        mo.callout(mo.md(f"**Correct!**\\n\\n```python\\n{{_solution}}\\n```"), kind="success")
    elif _status == "released":
        mo.callout(mo.md(f"**Released by instructor**\\n\\n```python\\n{{_solution}}\\n```"), kind="info")
    else:
        mo.callout(mo.md("**Incorrect** — try again"), kind="danger")
    return


'''


def build_key_fetch_cell() -> str:
    """Return marimo cells with state-based released keys and fetch button."""
    return """
@app.cell(hide_code=True)
def _(mo):
    released_keys, set_released_keys = mo.state({})
    return released_keys, set_released_keys


@app.cell(hide_code=True)
def _(mo, fetch_released_keys, set_released_keys):
    def _on_fetch(_):
        _keys = fetch_released_keys()
        set_released_keys(_keys)

    fetch_btn = mo.ui.button(label="Check for released solutions", on_click=_on_fetch)
    fetch_btn
    return (fetch_btn,)


"""


def process_workshop(
    source_path: Path, output_dir: Path, salt: str | None = None
) -> Path:
    """Full pipeline: parse _answers -> strip solutions -> encrypt -> inject cells -> write."""
    source_lines = source_path.read_text().splitlines(keepends=True)

    errors = validate_markers(source_lines, str(source_path))
    if errors:
        raise ValueError(f"Marker errors in {source_path}: {errors}")

    answers = parse_answers_metadata(source_lines)
    if not answers:
        raise ValueError(f"No {ANSWERS_MARKER} cell found in {source_path}")

    if salt is None:
        salt = secrets.token_hex(8)

    # Build exercises dict from source (before stripping)
    exercises = build_exercises_dict(answers, salt, source_lines)

    # Strip solutions
    stripped = strip_solutions(source_lines)

    # Remove the _answers line and replace with EXERCISES setup
    # Also remove any MARKS_MARKER cell and Grader references
    processed = _replace_answers_cell(stripped, exercises, salt, answers)

    # Build injected cells — key fetch first (defines released_keys state),
    # then per-question checkers
    injected_text = ""
    injected_text += build_key_fetch_cell()
    for key in answers:
        title = key
        injected_text += build_checker_cell(key, title)

    # Inject before __main__
    processed = _inject_before_main(processed, injected_text)

    output_dir.mkdir(parents=True, exist_ok=True)
    dest = output_dir / source_path.name
    dest.write_text("".join(processed))
    return dest


def _replace_answers_cell(
    lines: list[str], exercises: dict, salt: str, answers: dict
) -> list[str]:
    """Replace the _answers = {...} line with EXERCISES + SALT definitions.

    Adds imports for check_answer and fetch_released_keys, and replaces
    the _answers dict with the encrypted EXERCISES dict + SALT constant.
    """
    output = []
    found_marker = False

    for line in lines:
        if ANSWERS_MARKER in line:
            found_marker = True
            output.append(line)
            continue

        # Replace _answers = {...} with EXERCISES and SALT
        if found_marker and "_answers" in line and "=" in line:
            # Detect indentation from the _answers line
            indent = line[: len(line) - len(line.lstrip())]
            # Write EXERCISES dict with proper indentation
            exercises_json = json.dumps(exercises, indent=4)
            # Indent all lines of the JSON
            ex_lines = exercises_json.split("\n")
            output.append(f"{indent}EXERCISES = {ex_lines[0]}\n")
            for ex_line in ex_lines[1:]:
                output.append(f"{indent}{ex_line}\n")
            output.append(f"{indent}SALT = {salt!r}\n")
            found_marker = False
            continue

        # Add workshop imports alongside existing imports
        if "from mograder.runtime import" in line and "check" in line:
            output.append(line)
            indent = line[: len(line) - len(line.lstrip())]
            output.append(
                f"{indent}from mograder.workshop import check_answer, fetch_released_keys\n"
            )
            continue

        # Replace WorkshopGrader/Grader import references if present
        if "WorkshopGrader" in line:
            continue

        # Augment return statement in the answers cell to include new names
        if (
            "return" in line
            and "check" in line
            and any(ANSWERS_MARKER in ol for ol in output)
        ):
            # Add EXERCISES, SALT, check_answer, fetch_released_keys to return
            stripped = line.rstrip("\n")
            if stripped.rstrip().endswith(")"):
                # Has trailing paren — not a tuple return
                pass
            new_names = "EXERCISES, SALT, check_answer, fetch_released_keys, "
            # Insert new names after "return "
            line = line.replace("return ", f"return {new_names}", 1)

        output.append(line)

    return output


def write_keys(
    answers: dict,
    salt: str,
    path: Path,
    which: str = "all",
    tolerance: int = 6,
) -> None:
    """Write keys JSON file (empty {} or all normalized answers)."""
    if which == "empty":
        path.write_text("{}\n")
    else:
        keys = {}
        for key, answer in answers.items():
            keys[key] = normalize_answer(answer, tolerance)
        path.write_text(json.dumps(keys, indent=2) + "\n")


def release_key(
    keys_path: Path,
    exercise_id: str,
    answer_str: str,
    tolerance: int = 6,
) -> None:
    """Add one key to a keys.json for incremental release during a live workshop."""
    if keys_path.exists():
        keys = json.loads(keys_path.read_text())
    else:
        keys = {}

    try:
        answer = ast.literal_eval(answer_str)
    except (ValueError, SyntaxError):
        answer = answer_str

    keys[exercise_id] = normalize_answer(answer, tolerance)
    keys_path.write_text(json.dumps(keys, indent=2) + "\n")
