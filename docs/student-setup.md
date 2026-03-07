# Student Setup Guide

## Quick Start

### macOS / Linux

```bash
# 1. Install uv (one time)
curl -LsSf https://astral.sh/uv/install.sh | sh

# 2. Launch the student dashboard (first time — uses URL)
uvx mograder student <CONFIG_URL>
```

Your instructor will provide the `<CONFIG_URL>` (a link to the course's `mograder.toml` file).

### Windows (PowerShell)

```powershell
# 1. Install uv (one time)
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

**Restart your terminal**, then:

```powershell
# 2. Launch the student dashboard (first time — uses URL)
uvx mograder student <CONFIG_URL>
```

### Returning sessions (all platforms)

After the first run, a course directory is created for you. Just `cd` into it and run:

```bash
cd <course-directory>
uvx mograder student
```

The dashboard will automatically fetch the latest assignment list.

## What is uv?

[uv](https://docs.astral.sh/uv/) is a fast Python package manager. The `uvx` command runs Python tools without needing to install them globally — it creates a temporary environment, installs mograder and its dependencies, and launches the dashboard. No virtual environments or `pip install` needed.

## Platform details

- **macOS / Linux**: The `curl` command installs uv to `~/.local/bin`. You may need to restart your shell or run `source ~/.bashrc` (or `~/.zshrc`) for the `uvx` command to be available.
- **Windows**: After running the PowerShell installer, you **must** restart your terminal for `uvx` to be on your PATH.
- **Molab (cloud)**: See the [Molab workflow](#molab-cloud-workflow) section below — no local install needed.

## Working on assignments

The student dashboard shows your course assignments with:

- **Fetch** — opens the Moodle assignment page where you can download the notebook file
- **Validate** — runs the notebook's checks locally to verify your answers pass
- **Edit** — opens the notebook in marimo for editing
- **Submit** — opens the Moodle submission page where you can upload your completed notebook
- **Feedback** — view your grade and feedback after marking is complete

### Opening notebooks directly

You can also work on notebooks without the dashboard:

```bash
marimo edit --sandbox notebook.py
```

The `--sandbox` flag tells marimo to read the PEP 723 inline metadata in the notebook and install dependencies automatically.

## Molab (cloud workflow)

If you're using [Molab](https://molab.marimo.io), no local installation is required:

1. Download the `.py` notebook file from Moodle
2. Upload the file to Molab
3. Molab automatically installs dependencies from the notebook's inline metadata
4. Work on the notebook in your browser
5. Download the completed `.py` file from Molab
6. Submit via the Moodle web interface

## Troubleshooting

### "command not found: uvx"

- Make sure you've installed uv (step 1 above)
- Restart your terminal after installing uv
- On macOS/Linux, check that `~/.local/bin` is on your PATH

### "Error: ... is not a directory"

Make sure you're either:
- Passing a URL for first-time setup: `uvx mograder student https://...`
- Running from inside the course directory: `cd <course> && uvx mograder student`

### Network / proxy issues

If fetching the config fails behind a corporate proxy or firewall, ask your instructor for the `mograder.toml` file directly. Place it in a new directory and run `uvx mograder student` from that directory.

### "No assignments found"

Your instructor may not have published assignments yet. The dashboard refreshes the assignment list each time you launch it.
