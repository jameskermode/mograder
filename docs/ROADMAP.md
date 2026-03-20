# Mograder Roadmap

## Competitive Analysis: mograder vs nbgrader vs otter-grader

### Feature Matrix

| Feature | nbgrader | otter-grader | mograder |
|---------|----------|-------------|----------|
| **Notebook platform** | Jupyter | Jupyter | Marimo |
| **Solution stripping** | Yes | Yes | Yes |
| **Auto-grading** | Yes | Yes | Yes |
| **Partial credit** | Manual only | Yes (weighted) | Yes (weighted) |
| **Hidden tests** | Yes | Yes | **Yes** |
| **Manual grading UI** | Web (formgrader) | Gradescope | Web (formgrader) |
| **LMS integration** | Canvas (via plugin) | Canvas, Gradescope | Moodle (API + CSV) |
| **Late penalties** | No (LMS handles) | No (Gradescope) | **Yes** |
| **Integrity checking** | Cell-level checksums | Seed-based | Cell hashing + source reinjection |
| **Reactive notebooks** | No | No | Yes (marimo) |
| **Per-question marks** | Points per cell | Points per test | Dict-based with reactive scores |
| **Feedback export** | HTML notebooks | PDF | HTML (marimo export) |
| **WASM deployment** | No | No | Yes |
| **Sandbox execution** | No | Docker (optional) | bubblewrap + rlimits |

### Mograder Strengths

1. **Marimo-native**: Reactive notebooks with live score tracking
2. **Robust integrity**: Cell hashing + source reinjection detects and fixes all tampering
3. **Moodle-first**: Deep Moodle API integration (fetch, submit, grade, upload feedback)
4. **Lightweight**: No Docker/Kubernetes required; single `pip install`
5. **Flexible marks**: Per-question marks with partial credit and weighted checks
6. **Formgrader dashboard**: Web UI for GTA grading with headless edit sessions

### Identified Gaps (now addressed)

1. **Hidden tests** (Priority 1A) — Implemented
2. **Late penalties** (Priority 1B) — Implemented
3. **Formgrader analytics** — Already existed (histograms + stats in formgrader_app.py)

### Prioritised Roadmap

#### Completed

- [x] **1A: Hidden tests** — `### BEGIN HIDDEN TESTS` / `### END HIDDEN TESTS` markers,
  stripped during generate, reinjected during autograde. Score suppression in release
  notebooks to avoid misleading partial marks.
- [x] **1B: Late penalties** — Configurable per-day deductions applied during feedback phase.
  Grace period, max cap, ceil-to-whole-days. Stored alongside raw marks in gradebook.
- [x] **1C: Formgrader analytics** — Histogram and statistics display (already implemented).

#### Future

- [ ] **2A: Plagiarism detection** — Integration with MOSS or custom token-based similarity.
- [ ] **2B: Rubric-based grading** — Structured rubrics in formgrader with per-criterion scores.
- [ ] **2C: Canvas integration** — Alternative LMS transport alongside Moodle.
- [ ] **3A: Notebook versioning** — Track assignment revisions and re-grade with updated tests.
- [ ] **3B: Student analytics** — Per-student progress tracking across assignments.
- [ ] **3C: Peer review** — Student-to-student feedback workflows.
