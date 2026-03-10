# Student Setup Guide

There are three ways to work on assignments. Pick whichever suits you best:

| | **Local install** | **GitHub Codespaces** | **Molab** |
|---|---|---|---|
| Setup | Install uv (2 commands) | One click | None |
| Platforms | macOS, Linux, Windows | Any browser | Any browser |
| Best for | Full offline workflow | Windows users, quick start | Light editing, no install |
| Validate | Yes | Yes | No |

## Option 1: Local install

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

> **Tip:** If you have trouble with the Windows install, try [GitHub Codespaces](#option-2-github-codespaces) instead — it works entirely in your browser with no local setup.

### Returning sessions (all platforms)

After the first run, a course directory is created for you. Just `cd` into it and run:

```bash
cd <course-directory>
uvx mograder student
```

The dashboard will automatically fetch the latest assignment list.

### What is uv?

[uv](https://docs.astral.sh/uv/) is a fast Python package manager. The `uvx` command runs Python tools without needing to install them globally — it creates a temporary environment, installs mograder and its dependencies, and launches the dashboard. No virtual environments or `pip install` needed.

### Platform details

- **macOS / Linux**: The `curl` command installs uv to `~/.local/bin`. You may need to restart your shell or run `source ~/.bashrc` (or `~/.zshrc`) for the `uvx` command to be available.
- **Windows**: After running the PowerShell installer, you **must** restart your terminal for `uvx` to be on your PATH.

## Option 2: GitHub Codespaces

GitHub Codespaces gives you a full development environment in your browser — no local install needed.

### Getting started

1. Your instructor will provide a Codespaces link (e.g. `https://codespaces.new/<org>/<repo>`)
2. Click the link and choose **Create codespace**
3. Wait for the environment to build (takes ~1 minute the first time)
4. The student dashboard starts automatically — open port **2718** in the Ports tab or click the link in the terminal

### How editing works

In Codespaces, notebooks open in **headless mode**: marimo runs in the background and you edit in a new browser tab via port forwarding. The dashboard handles this automatically when you click **Edit**.

### Managing usage

GitHub gives free accounts **120 core-hours/month** of Codespaces time. To avoid wasting hours:

- **Stop your Codespace** when you're done: click your profile picture (top-right on github.com) → **Your codespaces** → **⋯** → **Stop codespace**
- **Reopen later**: go to [github.com/codespaces](https://github.com/codespaces) and click on your existing Codespace — it resumes where you left off
- **Check usage**: go to **Settings** → **Billing and plans** → **Codespaces** to see remaining hours

Codespaces automatically stop after 30 minutes of inactivity. Your work is saved until the Codespace is deleted (default: after 30 days of inactivity).

## Option 3: Molab (cloud)

If you're using [Molab](https://molab.marimo.io), no local installation is required:

1. Download the `.py` notebook file from Moodle (or your course's HTTPS server)
2. Upload the file to Molab
3. Molab automatically installs dependencies from the notebook's inline metadata
4. Work on the notebook in your browser
5. Download the completed `.py` file from Molab
6. Submit via the Moodle web interface or `mograder https submit`

> **Note:** Molab does not support the **Validate** button — you won't be able to check your work against the assignment's test cases before submitting.

### Molab with HTTPS transport

If your course uses the mograder HTTPS transport (instead of Moodle), your instructor will provide a server URL. You can fetch and submit assignments via the CLI:

```bash
# Fetch the assignment notebook
uvx mograder https fetch "hw1" --url <SERVER_URL> -o hw1/

# Upload to Molab, work on it, then download the completed file

# Submit your work
uvx mograder https submit hw1/homework.py -a "hw1" --url <SERVER_URL> --user <YOUR_USERNAME>

# Check your status
uvx mograder https feedback "hw1" --url <SERVER_URL> --user <YOUR_USERNAME>
```

Or set the URL in `mograder.toml` so you don't need `--url` every time:

```toml
transport = "https"

[https]
url = "http://your-course-server.example.com:8080"
```

## Working on assignments

When the dashboard launches, log in with your credentials (Moodle token or course username, depending on your course setup). Credentials are cached locally so you only need to do this once.

The dashboard shows your course assignments with status tracking and action buttons:

- **Download** — downloads the assignment `.py` file into a local subdirectory
- **Edit** — opens the notebook in marimo for editing (launches `marimo edit --sandbox`)
- **Validate** — runs the notebook's checks locally and shows results (e.g. "3/5 PASS") with an inline HTML report
- **Submit** — uploads your `.py` file and finalizes the submission

Assignment status updates automatically: **Downloaded** → **Submitted** (after submit) → **Modified** (if you edit after submitting). View grades and feedback directly on Moodle.

### Opening notebooks directly

You can also work on notebooks without the dashboard:

```bash
marimo edit --sandbox notebook.py
```

The `--sandbox` flag tells marimo to read the PEP 723 inline metadata in the notebook and install dependencies automatically.

## Troubleshooting

### "command not found: uvx"

- Make sure you've installed uv (step 1 above)
- Restart your terminal after installing uv
- On macOS/Linux, check that `~/.local/bin` is on your PATH

### "Error: ... is not a directory"

Make sure you're either:
- Passing a URL for first-time setup: `uvx mograder student https://...`
- Running from inside the course directory: `cd <course> && uvx mograder student`

### Windows issues

If you experience problems with uv or marimo on Windows (PATH issues, permission errors, antivirus interference), consider using [GitHub Codespaces](#option-2-github-codespaces) as a hassle-free alternative.

### Network / proxy issues

If fetching the config fails behind a corporate proxy or firewall, ask your instructor for the `mograder.toml` file directly. Place it in a new directory and run `uvx mograder student` from that directory.

### "No assignments found"

Your instructor may not have published assignments yet. The dashboard refreshes the assignment list each time you launch it.
