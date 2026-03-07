# [Course Name]

## Getting started

### 1. Install uv (one time)

**macOS / Linux:**
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

**Windows (PowerShell):**
```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

Restart your terminal after installing.

### 2. Launch the student dashboard

```bash
uvx mograder student <CONFIG_URL>
```

Replace `<CONFIG_URL>` with the URL provided by your instructor, e.g.:
```
https://raw.githubusercontent.com/<user>/<repo>/main/mograder.toml
```

### Returning sessions

After the first run, just `cd` into the course directory and run:

```bash
cd <course-directory>
uvx mograder student
```

## Molab

If you're working on [Molab](https://molab.marimo.io):

1. Download the notebook from Moodle
2. Upload to Molab — dependencies install automatically
3. Work on the notebook in your browser
4. Download and submit via Moodle

## Troubleshooting

See the [mograder Student Setup Guide](https://github.com/jameskermode/mograder/blob/main/docs/student-setup.md#troubleshooting).
