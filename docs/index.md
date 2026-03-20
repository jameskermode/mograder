# mograder

<p align="center">
  <img src="assets/mograder.svg" alt="mograder logo" width="128" height="128">
</p>

Semi-automated grading for [Marimo](https://marimo.io) notebooks.

[![PyPI](https://img.shields.io/pypi/v/mograder)](https://pypi.org/project/mograder/)
[![Tests](https://img.shields.io/github/actions/workflow/status/jameskermode/mograder/ci.yml?branch=main&label=tests)](https://github.com/jameskermode/mograder/actions/workflows/ci.yml)
[![Docs](https://img.shields.io/github/actions/workflow/status/jameskermode/mograder/docs.yml?branch=main&label=docs)](https://jameskermode.github.io/mograder/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue)](https://github.com/jameskermode/mograder/blob/main/LICENSE)
[![Python 3.11+](https://img.shields.io/pypi/pyversions/mograder)](https://pypi.org/project/mograder/)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)

---

mograder aspires to become a Marimo equivalent of [nbgrader](https://nbgrader.readthedocs.io/). It doesn't yet have full feature parity but should already be useable. mograder has been developed based on experiences teaching computational modelling and machine learning with Jupyter and nbgrader in [HetSys CDT](https://warwick.ac.uk/fac/sci/hetsys/) and the [Predictive Modelling and Scientific Computing MSc course](https://warwick.ac.uk/study/postgraduate/courses/pga-pgcert-pgdip-msc-predictive-modelling-scientific-computing/), both at the University of Warwick.

## Three grading modes

- **Workshop mode** — fully formative (no marks assigned). Model solutions can be unlocked automatically by students when they pass automated tests. Solutions can also be released one by one by an instructor from a web dashboard, allowing 'un-sticking' of students during a live workshop.
- **Manual grading** of a single holistic mark. Instant formative feedback is available to students on coding questions, while reflective interpretation is manually graded.
- **Hybrid grading** — automated per-question marks on coding exercises, plus a single mark for the reflective component.

Two transports are currently available: [Moodle integration](usage/moodle.md) and [HTTPS transport](usage/https-transport.md) for standalone usage.

## How it works

Instructors author source notebooks with solution blocks and automated checks. `mograder generate` strips solutions to create release versions. Students complete the notebooks and get instant formative feedback from `check()` calls. `mograder autograde` executes submissions in sandboxed subprocesses, parses results, and stores grades in an SQLite gradebook. Markers review and add manual marks via the formgrader dashboard. `mograder feedback` exports annotated HTML for students.

## Try it

A live demo is available with three components:

1. **[Student Dashboard](https://jameskermode.github.io/mograder/dashboard/?server=https://mograder-demo.jrkermode.uk&wasm_base=notebooks)** — WASM app hosted on GitHub Pages. Lists assignments and links to self-hosted WASM notebooks for editing in the browser.
2. **[Formgrader + Assignment Server](https://mograder-demo.jrkermode.uk)** — Combined ASGI app. The formgrader UI shows the full grading workflow (assignments, submissions, grading, students tabs) with pre-populated demo data. The same service also handles the assignment API at `/assignments`. No login required (for a real server, token-based authentication should be used).
3. **Notebook Editor** — Click "Edit in Browser" in the dashboard to open a notebook as a standalone WASM app with full edit mode or "Edit in Molab" to open a full editor. Each notebook has a submit cell to send your work back to the demonstration assignment server.

There is also a **[Demo Workshop](https://jameskermode.github.io/mograder/dashboard/notebooks/demo-workshop.html)** which is a WASM notebook demonstrating hints and encrypted solutions for formative workshops. The **[Instructor Dashboard](https://mograder-demo.jrkermode.uk/dashboard.html#token=mograder-demo-secret)** controls which model solutions are visible to students. The workshop key for this demo is `mograder`.

A demonstration **[GitHub Codespaces](https://codespaces.new/jameskermode/mograder)** shows how to open this repo in a Codespace for a full development environment with uv, marimo, and the student dashboard pre-configured.

## Quick start

```bash
pip install mograder          # or: uv add mograder
mograder generate hw1         # strip solutions → release/
mograder autograde hw1        # grade submissions → autograded/
mograder feedback hw1         # export HTML → feedback/
```

See the [Installation](installation.md) page for full details, the [Instructor Guide](instructor-guide.md) for a step-by-step walkthrough, or the [Usage](usage/index.md) section for reference on each command.

## For students

**Easiest:** download the [desktop app](https://github.com/jameskermode/mograder-tauri/releases/latest) — no terminal needed.

**Or via the command line:**

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
uvx mograder student <CONFIG_URL>
```

Or open in **[GitHub Codespaces](student-guide.md#option-3-github-codespaces)** — one click, no install needed.
