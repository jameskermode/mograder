# Export Feedback

Export graded notebooks to HTML and aggregate marks:

```bash
mograder feedback hw1                             # by assignment name
mograder feedback autograded/hw1/*.py -o feedback/hw1/
mograder feedback hw1 --grades-csv grades.csv
mograder feedback hw1 --no-penalties              # skip late penalties
mograder feedback hw1 --due-date 2025-06-01T23:59:00  # override deadline
```

## Late penalties

If `[penalties]` is configured in `mograder.toml` (see [Configuration](../configuration.md#penalties)), penalties are computed automatically during feedback export. Submission timestamps are resolved from `.fetch_metadata.json` (created by `mograder moodle fetch-submissions`) with file mtime as fallback. Use `--no-penalties` to skip, or `--due-date` to override the assignment deadline.

The penalty appears as a red line in the HTML feedback callout showing the deduction and reason.

## Hidden test results

When hidden tests are present (see [Source Notebooks: Hidden tests](source-notebooks.md#hidden-tests)), the feedback HTML shows hidden test results labelled with "(hidden)". The check label and PASS/FAIL status are visible, but specific failure messages that might reveal test internals are not included.
