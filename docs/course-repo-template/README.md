# [Course Name]

## Getting started

There are three ways to work on assignments — pick one:

### Option A: GitHub Codespaces (recommended)

No install needed — works entirely in your browser:

1. **[Open in Codespaces](<CODESPACES_URL>)** ← click this link
2. Wait for the environment to build (~1 minute)
3. The student dashboard starts automatically — open port **2718** in the Ports tab

See the [full Codespaces guide](https://github.com/jameskermode/mograder/blob/main/docs/student-setup.md#option-2-github-codespaces) for usage tips and managing hours.

### Option B: Local install

**1. Install uv (one time)**

**macOS / Linux:**
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

**Windows (PowerShell):**
```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

Restart your terminal after installing.

**2. Launch the student dashboard**

```bash
uvx mograder student <CONFIG_URL>
```

Replace `<CONFIG_URL>` with the URL provided by your instructor, e.g.:
```
https://raw.githubusercontent.com/<user>/<repo>/main/mograder.toml
```

**Returning sessions**

After the first run, just `cd` into the course directory and run:

```bash
cd <course-directory>
uvx mograder student
```

### Option C: Molab

If you're working on [Molab](https://molab.marimo.io) (no install needed, but Validate is not available):

1. Download the notebook from Moodle (or via `uvx mograder https fetch`)
2. Upload to Molab — dependencies install automatically
3. Work on the notebook in your browser
4. Download and submit via Moodle (or via `uvx mograder https submit`)

## Troubleshooting

See the [mograder Student Setup Guide](https://github.com/jameskermode/mograder/blob/main/docs/student-setup.md#troubleshooting).
