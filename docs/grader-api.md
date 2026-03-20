# Grader API Reference

Public symbols exported from `mograder.runtime`:

```python
from mograder.runtime import check, Grader, hint
```

## `check(label, checks)`

Run a list of boolean checks and display coloured feedback.

```python
check(label: str, checks: list[tuple[bool, str] | tuple[bool, str, int | float]]) -> mo.Html
```

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `label` | `str` | Name of the test, e.g. `"Q2: Model evaluation"` |
| `checks` | `list[tuple[bool, str] \| tuple[bool, str, weight]]` | List of `(condition, message)` or `(condition, message, weight)` tuples. Default weight is 1. |

**Returns:** A marimo `Html` callout element.

**Behaviour:**

| Condition | Callout | Sidecar |
|-----------|---------|---------|
| All checks pass | Green: "all checks passed" | `status: "success"` |
| Some pass, some fail | Red: lists failure messages | `status: "danger"` |
| Empty checks list | Amber: "waiting for your code" | Nothing written |

The empty-checks case is designed for use with `mo.stop()` to show a "waiting" state before the student has written code:

```python
@app.cell(hide_code=True)
def _(check, mo, x):
    mo.stop(x is None, check("Q1: Array creation", []))
    check("Q1: Array creation", [
        (x.shape == (50,), f"x should have shape (50,), got {x.shape}"),
    ])
    return
```

When `x is None`, the first `check()` call returns the amber callout and `mo.stop()` halts the cell. Once `x` is defined, execution continues to the real check.

**Sidecar mechanism:** During `mograder autograde`, the environment variable `MOGRADER_SIDECAR_PATH` is set to a temp JSONL file. Each `check()` call appends a JSON record `{"label", "status", "details", "earned_weight", "total_weight"}` to this file. The runner polls it for live progress. Empty-check calls (the `mo.stop()` guard) do not write to the sidecar to avoid false results.

## `Grader(mo, marks)`

Per-question marks with reactive score tracking.

```python
grader = Grader(mo, marks: dict[str, int | float])
check = grader.check
```

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `mo` | module | The `marimo` module (pass the `mo` import) |
| `marks` | `dict[str, int\|float]` | Mapping of question key to available marks |

### `grader.check(label, checks)`

Same signature as the standalone `check()` (including optional weights), plus:

- Looks up marks from `self.marks` using the **question key** (text before the first colon in `label`). So `check("Q1: Array creation", [...])` maps to `marks["Q1"]`.
- Awards **partial credit**: earned marks = `round(available × earned_weight / total_weight, 1)`
- Displays a marks badge: `[10/10 marks]` (all pass), `[6/10 marks]` (partial), or `[0/10 marks]` (none pass)
- Callout colour: green (all pass), blue (partial), red (none pass)
- Updates reactive state for the score table

### `grader.scores()`

Display a reactive score table showing earned/available marks per question.

```python
grader.scores() -> mo.Html
```

Returns a callout with a markdown table:

| Question | Status | Marks |
|----------|--------|-------|
| Q1 | PASS | 10/10 |
| Q2 | PARTIAL | 6/15 |
| Analysis | — | 0/60 |
| **Total** | | **16/85** |

Status values: **PASS** (all checks pass), **PARTIAL** (some pass — fractional marks), **FAIL** (none pass), **—** (not yet attempted). Questions without a matching `check()` call show "—" (manual grading required). The table updates reactively as students complete questions.

### Complete per-question example

```python
@app.cell(hide_code=True)
def _():
    import marimo as mo
    from mograder.runtime import Grader

    # === MOGRADER: MARKS ===
    _marks = {"Q1": 10, "Q2": 15, "Analysis": 60}
    grader = Grader(mo, _marks)
    check = grader.check
    return check, grader, mo


@app.cell
def _(np):
    ### BEGIN SOLUTION
    x = np.linspace(0, 2 * np.pi, 50)
    ### END SOLUTION
    return (x,)


@app.cell(hide_code=True)
def _(check, mo, np, x):
    mo.stop(x is None, check("Q1: Array creation", []))
    check("Q1: Array creation", [
        (isinstance(x, np.ndarray), "x should be a numpy array"),
        (x.shape == (50,), f"Expected shape (50,), got {x.shape}"),
        (abs(x[0]) < 1e-10, "x should start at 0", 3),  # weight 3
    ])
    return


@app.cell(hide_code=True)
def _(grader):
    grader.scores()
    return
```

## `hint(*hints)`

Display progressive hints in collapsed accordions.

```python
hint(*hints: str) -> mo.Html
```

**Single hint** — accordion label is "Hint":

```python
hint("Think about what preserves insertion order")
```

**Multiple hints** — numbered "Hint 1", "Hint 2", ...:

```python
hint(
    "Think about which data structure preserves insertion order",
    "Consider using `collections.OrderedDict`",
    "Use `OrderedDict.move_to_end()`",
)
```

## Solution markers

Source notebooks use `### BEGIN SOLUTION` / `### END SOLUTION` to delimit model solutions. During `mograder generate`:

1. Everything between the markers is replaced with `# YOUR CODE HERE` and `pass`
2. For cells with `response_text = "..."`, the stripped code is further converted to an editable `mo.md()` block
3. Cell hashes are embedded in PEP 723 metadata for integrity checking

### Marker validation

Run `mograder generate --validate` to check for common errors:

- Unmatched BEGIN/END pairs
- Missing solution blocks in cells that define required variables
- Duplicate labels in check calls

## Known constraints

- **Reactive ordering:** In marimo, cells execute in dependency order, not top-to-bottom. Ensure `check()` cells depend on the variables they test.
- **Empty checks = WAIT:** An empty checks list always produces an amber "waiting" callout and does not write to the sidecar. This is by design for `mo.stop()` guards.
- **Question key extraction:** The key is `label.split(":")[0].strip()`. If your label has no colon, the entire label is the key. Ensure keys match between `check()` labels and the `_marks` dictionary.
- **Sidecar is append-only:** If a cell re-executes (e.g. due to reactive updates), multiple entries for the same label may appear. The runner uses the last entry per label.
