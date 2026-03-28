<p align="center">
  <img src="assets/mograder.svg" alt="mograder logo" width="128" height="128">
</p>

# mograder

[![PyPI](https://img.shields.io/pypi/v/mograder)](https://pypi.org/project/mograder/)
[![Tests](https://img.shields.io/github/actions/workflow/status/jameskermode/mograder/ci.yml?branch=main&label=tests)](https://github.com/jameskermode/mograder/actions/workflows/ci.yml)
[![Docs](https://img.shields.io/github/actions/workflow/status/jameskermode/mograder/docs.yml?branch=main&label=docs)](https://jameskermode.github.io/mograder/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue)](LICENSE)
[![Python 3.11+](https://img.shields.io/pypi/pyversions/mograder)](https://pypi.org/project/mograder/)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![Live Demo](https://img.shields.io/badge/demo-live-blue)](https://mograder-demo.jrkermode.uk)

Semi-automated grading for [Marimo](https://marimo.io) notebooks.

<p align="center">
  <img src="assets/mograder-demo.gif" alt="mograder student demo" width="720">
</p>

**How it works:** Instructors author source notebooks with solution blocks and automated checks. `mograder generate` strips solutions to create release versions. Students complete the notebooks and get instant formative feedback from `check()` calls. `mograder autograde` executes submissions in sandboxed subprocesses, parses results, and stores grades in an SQLite gradebook. Markers review and add manual marks via the grader dashboard. `mograder feedback` exports annotated HTML for students.

## Quick start

```bash
pip install mograder          # or: uv add mograder
mograder generate hw1         # strip solutions → release/
mograder autograde hw1        # grade submissions → autograded/
mograder feedback hw1         # export HTML → feedback/
```

## Live demo

**[Try the student dashboard](https://jameskermode.github.io/mograder/dashboard/?server=https://mograder-demo.jrkermode.uk&wasm_base=notebooks)** — a WASM app running entirely in your browser. See also the **[grader](https://mograder-demo.jrkermode.uk)** with pre-populated demo data and a **[demo workshop](https://jameskermode.github.io/mograder/dashboard/notebooks/demo-workshop.html)** with encrypted solutions.

## Documentation

| | |
|---|---|
| **[Full Documentation](https://jameskermode.github.io/mograder/)** | Overview, installation, and all guides |
| [Instructor Guide](https://jameskermode.github.io/mograder/instructor-guide/) | Step-by-step setup and grading walkthrough |
| [Student Guide](https://jameskermode.github.io/mograder/student-guide/) | Setup instructions to share with students |
| [Usage Reference](https://jameskermode.github.io/mograder/usage/) | All commands: generate, autograde, feedback, moodle, ... |
| [API Reference](https://jameskermode.github.io/mograder/reference/) | `check()`, `Grader`, CLI, and module docs |
| [Configuration](https://jameskermode.github.io/mograder/configuration/) | Full `mograder.toml` reference |
| [Security](https://jameskermode.github.io/mograder/security/) | Threat model and sandboxing options |

## For students

**Easiest:** download the [desktop app](https://github.com/jameskermode/mograder-tauri/releases/latest) — no terminal needed.

**Or via the command line:**

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
uvx mograder student https://mograder-demo.jrkermode.uk/mograder.toml
```

For real courses, your instructor will provide the config URL. Or open in **[GitHub Codespaces](https://jameskermode.github.io/mograder/student-guide/#option-3-github-codespaces)** — one click, no install needed.

## License

MIT
