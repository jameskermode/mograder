# Generate Release Notebooks

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
