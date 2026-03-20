# WASM Deployment

mograder provides commands for deploying notebooks as standalone WASM apps (e.g. on GitHub Pages):

```bash
mograder wasm-export hw1                      # export a single assignment
mograder wasm-export --all                    # export all WASM-compatible assignments
mograder wasm-export --check-only             # check compatibility without exporting
mograder wasm-export hw1 --mode run           # export in run mode (default: edit)
```

`wasm-export` checks each assignment's dependencies against Pyodide and runs `marimo export html-wasm` for compatible ones.

## Inject edit links

To inject pre-computed "Edit in Molab" links into a WASM student dashboard app:

```bash
mograder wasm-edit-links student_app.py release/hw1/hw1.py release/hw2/hw2.py
mograder wasm-edit-links student_app.py release/*/*.py -o output_app.py
```

Each notebook is compressed with lzstring and embedded as a Molab URL, keyed by the notebook's filename stem.
