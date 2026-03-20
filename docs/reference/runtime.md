# Runtime API

Public symbols exported from `mograder.runtime`, used inside notebooks for autograding checks, per-question marks, and hints.

```python
from mograder.runtime import check, Grader, hint
```

## API Reference

::: mograder.runtime
    options:
      members:
        - check
        - Grader
        - hint
      show_source: true
      show_root_heading: false

## Known Constraints

- **Reactive ordering:** In marimo, cells execute in dependency order, not top-to-bottom. Ensure `check()` cells depend on the variables they test.
- **Empty checks = WAIT:** An empty checks list always produces an amber "waiting" callout and does not write to the sidecar. This is by design for `mo.stop()` guards.
- **Question key extraction:** The key is `label.split(":")[0].strip()`. If your label has no colon, the entire label is the key. Ensure keys match between `check()` labels and the `_marks` dictionary.
- **Sidecar is append-only:** If a cell re-executes (e.g. due to reactive updates), multiple entries for the same label may appear. The runner uses the last entry per label.
- **Sidecar mechanism:** During `mograder autograde`, the environment variable `MOGRADER_SIDECAR_PATH` is set to a temp JSONL file. Each `check()` call appends a JSON record `{"label", "status", "details"}` to this file. The runner polls it for live progress. Empty-check calls (the `mo.stop()` guard) do not write to the sidecar to avoid false results.
