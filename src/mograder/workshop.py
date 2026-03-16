"""Workshop notebooks with encrypted solutions.

Solutions are XOR-encrypted with a secret salt known only to the instructor.
The generated notebook contains a SHA-256 hash of the salt (for verification)
and encrypted solution blobs. Solutions are revealed when:

1. The student's ``check()`` passes AND they have entered the correct
   workshop key (shared verbally by the instructor), or
2. The instructor releases solutions via ``keys.json``.

Provides encryption helpers, exercise parsing from source notebooks, and
notebook generation for interactive workshop use (including WASM deployment).
"""

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

EXERCISES_MARKER = "# === MOGRADER: EXERCISES ==="
_WORKSHOP_SOLUTION_PREFIX = "# === MOGRADER: WORKSHOP SOLUTION"

# Reuse pattern from integrity.py
_CHECK_CALL_RE = re.compile(r"""check\(\s*["']([^"':]+)""")


# ---------------------------------------------------------------------------
# Crypto primitives (pure Python, Pyodide-compatible)
# ---------------------------------------------------------------------------


def make_salt_hash(salt: str) -> str:
    """SHA-256 hash of the salt, for verification without exposing it."""
    return hashlib.sha256(salt.encode()).hexdigest()


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


def verify_key(workshop_key: str, salt_hash: str) -> bool:
    """Check whether *workshop_key* matches the stored salt hash."""
    return make_salt_hash(workshop_key) == salt_hash


def reveal_solution(
    exercise_id: str,
    check_passed: bool,
    exercises: dict,
    released_keys: dict,
    workshop_key: str,
    salt_hash: str,
) -> tuple[str, str | None]:
    """Reveal a solution if authorised.

    Returns ("passed", solution) | ("released", solution) |
            ("no_key", None) | ("locked", None).
    """
    ex = exercises.get(exercise_id)
    if ex is None:
        return ("locked", None)

    encrypted = ex["solution"]

    # Released keys work regardless of check or key
    if released_keys.get(exercise_id):
        # Need correct key to decrypt — use the released key value as the salt
        released_salt = released_keys[exercise_id]
        if isinstance(released_salt, str) and released_salt:
            return ("released", xor_decrypt(encrypted, released_salt))
        # If released_keys has True (legacy), can't decrypt without the key
        if workshop_key and verify_key(workshop_key, salt_hash):
            return ("released", xor_decrypt(encrypted, workshop_key))
        return ("released", None)

    if check_passed:
        if not workshop_key:
            return ("no_key", None)
        if verify_key(workshop_key, salt_hash):
            return ("passed", xor_decrypt(encrypted, workshop_key))
        return ("no_key", None)

    return ("locked", None)


def fetch_released_keys(url: str = "./keys.json") -> dict:
    """Fetch released keys. Uses pyodide.http.open_url in WASM, urllib locally."""
    try:
        from pyodide.http import open_url  # type: ignore[import-not-found]

        text = open_url(url).read()
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
# Exercise parsing (generate-time only)
# ---------------------------------------------------------------------------


def parse_exercises_metadata(source_lines: list[str]) -> list[str] | None:
    """Extract _exercises = [...] from the EXERCISES_MARKER cell.

    Returns a list of exercise key strings, or None if no marker found.
    """
    import ast

    text = "".join(source_lines)
    if EXERCISES_MARKER not in text:
        return None

    marker_idx = text.index(EXERCISES_MARKER)
    section = text[marker_idx:]

    list_match = re.search(r"_exercises\s*=\s*(\[[^\]]+\])", section)
    if not list_match:
        return None
    try:
        exercises = ast.literal_eval(list_match.group(1))
    except (ValueError, SyntaxError):
        return None

    return exercises if exercises else None


def extract_solution_for_key(source_lines: list[str], key: str) -> str | None:
    """Find the ### BEGIN/END SOLUTION block in the cell before the check() matching *key*."""
    text = "".join(source_lines)

    # Split into cells by @app.cell boundaries
    cell_pattern = re.compile(r"@app\.cell(?:\([^)]*\))?\s*\ndef ")
    cell_starts = [m.start() for m in cell_pattern.finditer(text)]

    for i, start in enumerate(cell_starts):
        end = cell_starts[i + 1] if i + 1 < len(cell_starts) else len(text)
        cell_code = text[start:end]

        m = _CHECK_CALL_RE.search(cell_code)
        if not m or m.group(1).strip() != key:
            continue

        if i > 0:
            prev_start = cell_starts[i - 1]
            prev_code = text[prev_start:start]
            sol = _extract_solution_block(prev_code)
            if sol:
                return sol

    # Fallback: scan all cells with solution blocks, check if the *next* cell matches
    for i, start in enumerate(cell_starts):
        end = cell_starts[i + 1] if i + 1 < len(cell_starts) else len(text)
        cell_code = text[start:end]
        if SOLUTION_BEGIN in cell_code:
            sol = _extract_solution_block(cell_code)
            if sol and i + 1 < len(cell_starts):
                next_end = cell_starts[i + 2] if i + 2 < len(cell_starts) else len(text)
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
    exercise_keys: list[str], salt: str, source_lines: list[str]
) -> dict[str, dict]:
    """Build EXERCISES dict with encrypted solutions for each exercise key."""
    exercises = {}
    for key in exercise_keys:
        solution_code = extract_solution_for_key(source_lines, key) or ""
        encrypted_solution = xor_encrypt(solution_code, salt)
        exercises[key] = {"solution": encrypted_solution}
    return exercises


def build_solution_cell(key: str) -> str:
    """Return marimo cell that auto-reveals the solution when check() passes."""
    safe_key = key.replace('"', '\\"')
    var_name = f"check_passed_{key}"
    return f'''
@app.cell(hide_code=True)
def _(mo, EXERCISES, SALT_HASH, released_keys, reveal_solution, workshop_key, {var_name}):
    {_WORKSHOP_SOLUTION_PREFIX} {key} ===
    _status, _solution = reveal_solution("{safe_key}", {var_name}, EXERCISES, released_keys(), workshop_key.value, SALT_HASH)
    if _status == "passed":
        _out = mo.callout(mo.md(f"**Model solution**\\n\\n```python\\n{{_solution}}\\n```"), kind="success")
    elif _status == "released":
        if _solution:
            _out = mo.callout(mo.md(f"**Released solution**\\n\\n```python\\n{{_solution}}\\n```"), kind="info")
        else:
            _out = mo.callout(mo.md("**Solution released** — enter the workshop key to view"), kind="info")
    elif _status == "no_key":
        _out = mo.callout(mo.md("**Checks passed!** Enter the workshop key below to reveal the model solution"), kind="warn")
    else:
        _out = mo.md("")
    _out
    return


'''


def build_key_fetch_cell() -> str:
    """Return marimo cells with released-keys state, workshop key input, and fetch button."""
    return """
@app.cell(hide_code=True)
def _(mo):
    released_keys, set_released_keys = mo.state({})
    return released_keys, set_released_keys


@app.cell(hide_code=True)
def _(mo):
    workshop_key = mo.ui.text(label="Workshop key", placeholder="Enter key from instructor")
    fetch_btn = mo.ui.run_button(label="Check for released solutions")
    mo.hstack([workshop_key, fetch_btn], justify="start", gap=1)
    return fetch_btn, workshop_key


@app.cell(hide_code=True)
def _(mo, fetch_btn, fetch_released_keys, set_released_keys):
    mo.stop(not fetch_btn.value)
    _keys = fetch_released_keys()
    set_released_keys(_keys)
    _n = len(_keys)
    if _n:
        _out = mo.callout(mo.md(f"**{_n} solution(s) released** — scroll up to see them"), kind="success")
    else:
        _out = mo.callout(mo.md("No additional solutions released by instructor"), kind="neutral")
    _out
    return


"""


def process_workshop(
    source_path: Path, output_dir: Path, salt: str | None = None
) -> Path:
    """Full pipeline: parse _exercises -> strip solutions -> encrypt -> inject cells -> write."""
    source_lines = source_path.read_text().splitlines(keepends=True)

    errors = validate_markers(source_lines, str(source_path))
    if errors:
        raise ValueError(f"Marker errors in {source_path}: {errors}")

    exercise_keys = parse_exercises_metadata(source_lines)
    if not exercise_keys:
        raise ValueError(f"No {EXERCISES_MARKER} cell found in {source_path}")

    if salt is None:
        salt = secrets.token_hex(8)

    salt_hash = make_salt_hash(salt)

    # Build exercises dict from source (before stripping)
    exercises = build_exercises_dict(exercise_keys, salt, source_lines)

    # Strip solutions
    stripped = strip_solutions(source_lines)

    # Replace _exercises line with EXERCISES + SALT_HASH, add imports
    processed = _replace_exercises_cell(stripped, exercises, salt_hash)

    # Add check_passed_<key> returns to exercise check cells,
    # and inject solution reveal cells right after each check cell
    processed = _add_check_pass_returns(processed, exercise_keys)
    processed = _inject_solution_cells(processed, exercise_keys)

    # Inject key fetch cell before __main__
    processed = _inject_before_main(processed, build_key_fetch_cell())

    output_dir.mkdir(parents=True, exist_ok=True)
    dest = output_dir / source_path.name
    dest.write_text("".join(processed))
    return dest


def _replace_exercises_cell(
    lines: list[str], exercises: dict, salt_hash: str
) -> list[str]:
    """Replace _exercises = [...] with EXERCISES dict + SALT_HASH, add imports."""
    output = []
    in_exercises_cell = False
    augment_next_return = False

    for line in lines:
        if EXERCISES_MARKER in line:
            in_exercises_cell = True
            output.append(line)
            continue

        # Replace _exercises = [...] with EXERCISES and SALT_HASH
        if in_exercises_cell and "_exercises" in line and "=" in line:
            indent = line[: len(line) - len(line.lstrip())]
            exercises_json = json.dumps(exercises, indent=4)
            ex_lines = exercises_json.split("\n")
            output.append(f"{indent}EXERCISES = {ex_lines[0]}\n")
            for ex_line in ex_lines[1:]:
                output.append(f"{indent}{ex_line}\n")
            output.append(f"{indent}SALT_HASH = {salt_hash!r}\n")
            augment_next_return = True
            in_exercises_cell = False
            continue

        # Add workshop imports alongside existing imports
        if "from mograder.runtime import" in line and "check" in line:
            output.append(line)
            indent = line[: len(line) - len(line.lstrip())]
            output.append(
                f"{indent}from mograder.workshop import reveal_solution, fetch_released_keys\n"
            )
            continue

        # Augment the return of the exercises cell only
        if augment_next_return and line.strip().startswith("return "):
            new_names = "EXERCISES, SALT_HASH, reveal_solution, fetch_released_keys, "
            line = line.replace("return ", f"return {new_names}", 1)
            augment_next_return = False

        output.append(line)

    return output


def _add_check_pass_returns(lines: list[str], exercise_keys: list[str]) -> list[str]:
    """Capture check() results and return a pass/fail bool from exercise check cells.

    For each check cell matching an exercise key, finds the standalone
    ``check(`` call (not the ``mo.stop`` guard), prefixes it with
    ``_result =``, and replaces the bare ``return`` with a
    ``check_passed_<key>`` extraction + return.
    """
    # Find @app.cell boundaries
    cell_starts = []
    for i, line in enumerate(lines):
        if line.strip().startswith("@app.cell"):
            cell_starts.append(i)

    # Match cell text (multi-line) to find exercise keys
    cell_key_map: dict[int, str] = {}
    for ci, start in enumerate(cell_starts):
        end = cell_starts[ci + 1] if ci + 1 < len(cell_starts) else len(lines)
        cell_text = "".join(lines[start:end])
        m = _CHECK_CALL_RE.search(cell_text)
        if m and m.group(1).strip() in exercise_keys:
            cell_key_map[start] = m.group(1).strip()

    if not cell_key_map:
        return lines

    output = []
    current_cell_key = None
    captured = False
    for i, line in enumerate(lines):
        if line.strip().startswith("@app.cell"):
            current_cell_key = cell_key_map.get(i)
            captured = False

        if current_cell_key:
            stripped = line.strip()
            if stripped.startswith("check(") and not captured:
                indent = line[: len(line) - len(line.lstrip())]
                line = f"{indent}_result = {stripped}\n"
                captured = True

            # Replace bare "return" with result extraction + display + return
            if stripped == "return" and captured:
                indent = line[: len(line) - len(line.lstrip())]
                var = f"check_passed_{current_cell_key}"
                output.append(
                    f'{indent}{var} = "success" in getattr(_result, "text", "")\n'
                )
                output.append(f"{indent}_result\n")
                output.append(f"{indent}return ({var},)\n")
                current_cell_key = None
                continue

        output.append(line)
    return output


def _inject_solution_cells(lines: list[str], exercise_keys: list[str]) -> list[str]:
    """Insert each solution reveal cell right after its corresponding check cell."""
    # Find @app.cell boundaries
    cell_starts = []
    for i, line in enumerate(lines):
        if line.strip().startswith("@app.cell"):
            cell_starts.append(i)

    # Identify which cells return check_passed_<key>
    insert_points: list[tuple[int, str]] = []
    for ci, start in enumerate(cell_starts):
        end = cell_starts[ci + 1] if ci + 1 < len(cell_starts) else len(lines)
        cell_text = "".join(lines[start:end])
        for key in exercise_keys:
            if f"check_passed_{key}" in cell_text:
                insert_points.append((end, key))
                break

    if not insert_points:
        return lines

    # Find the if __name__ line
    main_idx = len(lines)
    for i, line in enumerate(lines):
        if line.strip().startswith("if __name__"):
            main_idx = i
            break

    output = []
    deferred: list[str] = []
    insert_map = {pos: key for pos, key in insert_points}
    for pos, key in insert_points:
        if pos >= main_idx:
            deferred.append(build_solution_cell(key))

    for i, line in enumerate(lines):
        if i == main_idx and deferred:
            for sol_text in deferred:
                output.extend(sol_text.splitlines(keepends=True))
            deferred.clear()
        if i in insert_map and i < main_idx:
            sol_cell = build_solution_cell(insert_map[i])
            output.extend(sol_cell.splitlines(keepends=True))
        output.append(line)
    return output


def write_keys(
    exercise_keys: list[str], salt: str, path: Path, which: str = "empty"
) -> None:
    """Write keys JSON file.

    ``which="empty"`` writes ``{}``.
    ``which="all"`` writes all keys with the salt as the decryption value
    (so released solutions can be decrypted without the workshop key).
    """
    if which == "empty":
        path.write_text("{}\n")
    else:
        keys = {k: salt for k in exercise_keys}
        path.write_text(json.dumps(keys, indent=2) + "\n")


def release_key(keys_path: Path, exercise_id: str, salt: str) -> None:
    """Add one key to a keys.json for incremental release during a live workshop.

    The value is the salt itself, so the notebook can decrypt without
    the student needing to know the workshop key.
    """
    if keys_path.exists():
        keys = json.loads(keys_path.read_text())
    else:
        keys = {}
    keys[exercise_id] = salt
    keys_path.write_text(json.dumps(keys, indent=2) + "\n")
