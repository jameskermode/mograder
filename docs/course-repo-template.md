# Course Repository Template

Use this as a starting point for your course repository's README. Replace placeholders with your course-specific details.

---

## [Course Name]

### Getting started

There are three ways to work on assignments — pick one:

#### Option A: GitHub Codespaces (recommended)

No install needed — works entirely in your browser:

1. **[Open in Codespaces](<CODESPACES_URL>)** — click this link
2. Wait for the environment to build (~1 minute)
3. The student dashboard starts automatically — open port **2718** in the Ports tab

See the [full Codespaces guide](https://jameskermode.github.io/mograder/student-guide/#option-2-github-codespaces) for usage tips and managing hours.

#### Option B: Local install

**1. Install uv (one time)**

=== "macOS / Linux"

    ```bash
    curl -LsSf https://astral.sh/uv/install.sh | sh
    ```

=== "Windows (PowerShell)"

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

**Returning sessions:** after the first run, just `cd` into the course directory and run:

```bash
cd <course-directory>
uvx mograder student
```

#### Option C: Molab

If you're working on [Molab](https://molab.marimo.io) (no install needed, but Validate is not available):

1. Cache your auth token (one time): `uvx mograder https login --token <YOUR_TOKEN> --url <SERVER_URL>`
2. Download the notebook: `uvx mograder https fetch "hw1" -o hw1/` (or from Moodle)
3. Upload to Molab — dependencies install automatically
4. Work on the notebook in your browser
5. Download and submit: `uvx mograder https submit hw1/homework.py -a "hw1"` (or via Moodle)

### Troubleshooting

See the [mograder Student Setup Guide](https://jameskermode.github.io/mograder/student-guide/#troubleshooting).
