# Autograde Submissions

Run student notebooks and prepare grading copies with injected feedback cells:

```bash
mograder autograde hw1                            # by assignment name
mograder autograde submitted/hw1/*.py -o autograded/hw1/
mograder autograde submitted/hw1/*.py --source source/hw1/hw1.py --csv results.csv
mograder autograde hw1 -j 8 --timeout 600
```

When `--source` is provided (or auto-discovered from a sibling `source/` directory), mograder performs an integrity check — tampered check cells or marks definitions are reinjected from the source before execution. Default values for `-j` and `--timeout` can be set in `mograder.toml` (see [Configuration](../configuration.md)).

Use `--force` to re-grade all submissions even if the output is already up to date. Use `--safety-check` to scan submitted code for dangerous patterns before execution.

## Autograde directly from Moodle downloads

Instead of manually extracting submissions, you can pass the Moodle offline grading CSV and submission ZIP directly:

```bash
mograder autograde --moodle-csv grades.csv --moodle-zip submissions.zip --source source/hw1/hw1.py
```

This extracts submissions from the ZIP (mapping participant IDs to usernames via the CSV), then runs the normal autograde flow. The output directory and assignment name are inferred from the source notebook path.

## Hidden tests

When the source notebook contains `### BEGIN HIDDEN TESTS` / `### END HIDDEN TESTS` blocks, the release version has these replaced with a `# HIDDEN TESTS` placeholder. During autograde (with `--source` provided), hidden test blocks are reinjected from the source into each submission before execution. This means hidden checks run and contribute to the mark, but students never see the test code.
