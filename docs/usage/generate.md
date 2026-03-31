# Generate Release Notebooks

## Assignments

Strip solution blocks from source notebooks:

```bash
mograder generate hw1                             # by assignment name
mograder generate source/hw1/hw1.py -o release/   # by file path
mograder generate hw1 --dry-run                   # preview only
mograder generate hw1 --validate                  # check markers only
mograder generate hw1 --submit-url https://server.example.com  # inject submit cell
```

Arguments without `/` or `.py` suffix are treated as assignment names and resolved to files in the source directory. Auxiliary files (data, helper modules) are automatically copied from the source directory.

Use `--submit-url` to inject a submit cell into release notebooks, allowing students to submit directly from within the notebook to an HTTPS assignment server.

## Lectures

Generate a student-facing release from a lecture notebook:

```bash
mograder generate --lecture source/L01-Intro/L01-Intro.py
mograder generate --lecture L01-Intro.py -o release/
mograder generate --lecture L01-Intro.py --dry-run
```

The `--lecture` flag:

- **Strips slide layout metadata** — removes `layout_file` and `html_head_file` from `marimo.App()` so students get a plain scrollable notebook instead of a slide deck
- **Rewrites inter-notebook links** — lecture links (`../L02-Name/L02-Name.py`) become hub `/run/L02-Name/` URLs; assignment links are stripped to plain text
- **Injects `mograder-type = "lecture"`** into the PEP 723 script block, making the notebook self-describing (the hub auto-detects this during publishing)
- **Copies auxiliary files** — images, data files, and helper `.py` modules from the source directory (when the notebook lives in its own subdirectory)
- **Builds a release zip** when there are multiple files

Unlike assignment generation, lecture generation skips solution stripping, validation, and cell hash injection (none of these apply to lectures).

### Source directory layout

Lectures should live in their own subdirectory under `source/` alongside any auxiliary files:

```
source/
  L01-Intro/
    L01-Intro.py           # lecture notebook
    diagram.png            # image referenced by notebook
  L02-Methods/
    L02-Methods.py
    helper.py              # helper module imported by notebook
    data.csv
```

### PEP 723 dependencies

Lectures can declare their own dependencies via PEP 723 inline script metadata. These are preserved during generation and used by the hub to create per-lecture virtual environments:

```python
# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "numpy>=2",
#     "chaospy",
#     "matplotlib",
# ]
# ///
```
