# Validate a Notebook

Run a notebook in a sandbox and report check results (useful for students to self-check before submitting):

```bash
mograder validate hw1.py
mograder validate hw1.py --timeout 600
mograder validate hw1.py --fix --release release/hw1/hw1.py
```

Installs dependencies in a sandbox, executes the notebook, and prints PASS/FAIL for each check. Exits with code 1 if any check fails. An HTML report is saved alongside the notebook.

If the release notebook was generated with `mograder generate` (v0.1.1+), cell hashes are embedded in the PEP 723 metadata block. `validate` compares these hashes against the current cells and warns if any non-solution cells have been accidentally modified. Use `--fix` to restore them from the release version (found automatically in `.mograder/release/` if previously fetched, or specify `--release <path>`).
