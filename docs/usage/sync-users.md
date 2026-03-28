# Sync Users

Sync enrolled students from Moodle to the hub allowlist and gradebook.

## From Moodle

Fetch enrolled participants and sync to the hub and local gradebook:

```bash
mograder moodle sync-users --hub-url HUB_URL --hub-token TOKEN
```

This command:

1. Fetches participants from the first Moodle assignment via the API
2. Updates the local gradebook with student full names (for grader display)
3. Pushes the username list to the hub's `/sync-users` endpoint (if `--hub-url` provided)

If `--hub-url` is omitted, writes `allowed_users.txt` locally instead of
pushing to a remote hub.

Use `--dry-run` to preview the user list without syncing.

Requires `mograder moodle sync` to be run first to populate assignment metadata.

## Manual (HTTPS transport)

For non-Moodle deployments, upload a username list from a file:

```bash
mograder hub sync-users users.txt --url HUB_URL --token TOKEN
```

The file should contain one username per line (`#` comments allowed).
This updates the hub allowlist only (no gradebook names).
