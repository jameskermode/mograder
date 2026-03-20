# Moodle Integration

The `mograder moodle` command group provides both offline CSV-based workflows and live Moodle API access.

## Export grades (offline)

Merge grades into a Moodle offline grading worksheet and bundle feedback:

```bash
mograder moodle export "HW1" -o export/
mograder moodle export "HW1" --feedback-dir feedback/ -o export/
mograder moodle export "HW1" --worksheet custom.csv -o export/
```

The worksheet is auto-discovered at `import/<assignment>.csv` (matching formgrader convention). Grades are read from `gradebook.db` by default. The match column and name column can be configured in `mograder.toml` (see [Configuration](../configuration.md)). Student names are auto-imported into the gradebook when the moodle command runs.

## Fetch assignment (student)

Download assignment files from Moodle:

```bash
mograder moodle fetch "HW1"                     # download by name
mograder moodle fetch "HW1" -o ~/coursework/     # custom output directory
mograder moodle fetch --list                     # list available assignments
```

Downloads all attached files (`.py` notebooks and `.zip` archives with input data). ZIP files are automatically extracted. Assignment matching is flexible: exact name, numeric ID, or case-insensitive substring.

## Submit assignment (student)

Upload a completed notebook to Moodle:

```bash
mograder moodle submit "HW1" hw1.py              # upload and finalize
mograder moodle submit "HW1" hw1.py --dry-run    # check without uploading
mograder moodle submit "HW1" hw1.py --no-finalize  # upload draft only
```

Only `.py` files are accepted. By default, submissions are finalized (visible to graders). Use `--no-finalize` to save as draft.

## Fetch submissions (instructor)

Bulk-download all student submissions for an assignment:

```bash
mograder moodle fetch-submissions "HW1" -o submitted/hw1/
```

Downloads each student's latest `.py` submission, named by username.

## Upload release files (instructor)

Zip release files and open the Moodle assignment edit page for manual attachment:

```bash
mograder moodle upload "HW1"                    # auto-discovers from release/HW1/
mograder moodle upload "HW1" file1.py data.csv  # explicit files
mograder moodle upload "HW1" --dry-run          # preview without creating zip
mograder moodle upload "HW1" --no-open          # create zip without opening browser
```

Files are zipped into `<assignment>.zip` in the current directory. If no files are given, all files in `release/<assignment>/` are included. The Moodle assignment edit page is opened automatically so you can attach the zip as an introattachment.

## Upload feedback (instructor)

Push grades and feedback to Moodle via the API:

```bash
mograder moodle upload-feedback "HW1"                          # from gradebook.db
mograder moodle upload-feedback "HW1" --dry-run                # preview without pushing
mograder moodle upload-feedback "HW1" --grades-csv grades.csv  # from CSV
mograder moodle upload-feedback "HW1" --feedback-dir feedback/HW1/  # with HTML feedback files
mograder moodle upload-feedback "HW1" --workflow-state released     # make grades visible immediately
```

## Sync assignment metadata (instructor)

Fetch assignment metadata from Moodle and write it to `mograder.toml`:

```bash
mograder moodle sync                          # sync all visible assignments
mograder moodle sync --include '^A[1-8]'      # only assignments matching regex
```

Only assignments visible to students are included (hidden assignments are excluded). Students receive this metadata via the config URL or file. Re-run after publishing or hiding assignments.

## View feedback (student)

Check your submission status and view grade/feedback:

```bash
mograder moodle feedback "HW1"
```

Shows submission status, grade (if graded), and instructor feedback text.

## Login (obtain API token)

Obtain and cache a Moodle API token for subsequent commands:

```bash
mograder moodle login                    # username/password prompt
mograder moodle login --sso              # browser-based SSO (CAS/SAML/Shibboleth)
mograder moodle login --url https://moodle.uni.ac.uk
```

The token is cached at `~/.config/mograder/token.json`. For SSO sites, `--sso` opens the Moodle Security Keys page in your browser where you can copy the token.

All Moodle API commands accept `--url` and `--token` flags, or read from `MOGRADER_MOODLE_URL` / `MOGRADER_MOODLE_TOKEN` environment variables, or from the `[moodle]` section in `mograder.toml`.
