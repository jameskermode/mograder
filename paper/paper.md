---
title: 'mograder: Semi-automated grading for Marimo notebooks'
tags:
  - Python
  - education
  - grading
  - notebooks
  - marimo
  - autograding
authors:
  - name: James Kermode
    orcid: 0000-0001-6755-6271
    affiliation: 1
affiliations:
  - name: University of Warwick, UK
    index: 1
date: 20 March 2026
bibliography: paper.bib
---

# Summary

mograder is a Python tool for semi-automated grading of computational
notebooks written with Marimo [@marimo], a next-generation reactive
notebook framework. It provides a complete pipeline from authoring
assessments with embedded solutions through to distributing release
versions, collecting student submissions, autograding, manual review,
and feedback delivery. Unlike existing autograders that target Jupyter's
JSON-based `.ipynb` format, mograder works with Marimo's pure-Python
`.py` notebooks, making assignments fully version-control friendly and
diff-readable.

mograder supports three grading modes — fully automated workshop
exercises, manual marking with holistic scores, and a hybrid approach
with per-question marks combining automated partial credit and manual
assessment. It integrates natively with Moodle [@moodle] via its Web
Services API for fetching submissions, uploading grades, and delivering
feedback, and also provides a standalone HTTPS transport for
institutions without Moodle. A browser-based student dashboard lets
students validate their work, submit assignments, and view feedback.

# Statement of need

Computational notebooks are widely used in science and engineering
education for teaching programming, data analysis, and mathematical
modelling. Autograding tools such as nbgrader [@nbgrader] and
otter-grader [@otter] have made it practical to assess notebook-based
assignments at scale, but both are tightly coupled to the Jupyter
ecosystem and its `.ipynb` format.

The `.ipynb` format stores code, outputs, and metadata in a single JSON
file. This makes notebooks difficult to version-control — diffs are
noisy, merge conflicts are common, and cell outputs can contain large
binary blobs. Marimo addresses these issues with a pure-Python notebook
format where each cell is a standard Python function, outputs are never
stored, and the dependency graph is computed at runtime from variable
references. Marimo's reactive execution model also eliminates hidden
state bugs, a common source of frustration for students working with
Jupyter notebooks.

mograder brings autograding to the Marimo ecosystem. Its design
prioritises:

- **Version-control friendliness**: Source notebooks, release versions,
  and student submissions are all plain `.py` files that produce clean
  diffs and can be reviewed with standard code-review tools.
- **VLE integration**: Native Moodle support via the Web Services API
  means grades and feedback flow directly into the institution's
  learning management system, avoiding manual CSV upload/download
  workflows.
- **Flexible grading modes**: Instructors can choose fully automated
  checks, holistic manual marks, or a hybrid with weighted partial
  credit — adapting the tool to the assessment rather than the other way
  around.
- **Low barrier to adoption**: A course repository template, student
  guide, a cross-platform desktop app, and browser-based WebAssembly
  demos make it straightforward for both new instructors and students to
  get started.

# Software description

mograder follows the nbgrader terminology of source, release, submitted,
autograded, and feedback stages [@nbgrader]. Instructors author source
notebooks containing solutions delimited by `### BEGIN SOLUTION` /
`### END SOLUTION` markers. The `generate` command strips solutions and
produces release notebooks for distribution to students.

Student submissions are autograded by executing each notebook via
`marimo export html` in a sandboxed subprocess. Check results are
extracted from the HTML output and injected back into the `.py` source
alongside feedback placeholders for manual review. An integrity check
compares check and marks cells between the source and submitted
notebooks, detecting and repairing any student tampering before
execution.

For per-question marks, a `Grader` class provides reactive score
tracking using Marimo's `mo.state`, with partial credit proportional to
the weight of passing checks. The `feedback` command exports graded
notebooks to HTML and aggregates grades into a CSV file compatible with
Moodle's offline grading worksheet format.

A transport abstraction (`Transport` protocol) decouples the grading
pipeline from the submission mechanism. Two implementations are
provided: `MoodleTransport` wrapping the Moodle Web Services API, and
`HTTPSTransport` for a lightweight standalone server. This allows the
same CLI commands (`fetch`, `submit`, `upload-feedback`) to work with
either backend.

Beyond summative assessment, mograder supports formative workshop
notebooks with encrypted solutions that can be revealed progressively
during a live session or automatically when a student's check passes.
These can be deployed as WebAssembly apps via Marimo's WASM export,
requiring no server infrastructure.

# Classroom application

<!-- TODO: Fill in with specific details about your teaching context:
     - Which modules/courses use mograder?
     - How many students?
     - What types of assessments?
     - Student feedback or evaluation data? -->

mograder has been used at the University of Warwick for teaching
computational methods in the HetSys Centre for Doctoral Training and the
Predictive Modelling and Scientific Computing MSc programme.

Adoption is supported by a course repository template that provides a
ready-made directory structure, CI configuration, and a customisable
student guide. Instructors clone the template, add source notebooks, and
the pipeline handles the rest. Students can work via the cross-platform
desktop app (mograder-tauri), GitHub Codespaces, a local `uv`-based
install, or the browser-based Molab cloud editor — accommodating a range
of technical backgrounds and institutional constraints.

# AI usage disclosure

Development of mograder made extensive use of Claude Code (Anthropic's
AI coding assistant) for code generation, test writing, and
documentation authoring. AI contributions are transparently recorded in
the git history via `Co-Authored-By` trailer lines on commits. All
AI-generated code was reviewed by the author and verified through an
automated CI pipeline comprising pytest (33 test files, 763 tests)
running across multiple operating systems (Linux, macOS) and Python
versions (3.11, 3.12, 3.13), together with ruff linting and formatting
checks.

# References
