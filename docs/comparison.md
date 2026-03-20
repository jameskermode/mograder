# Comparison with nbgrader and otter-grader

| Feature | mograder | nbgrader | otter-grader |
|---|---|---|---|
| Notebook format | Marimo `.py` | Jupyter `.ipynb` | Jupyter `.ipynb` |
| Version control friendly | Yes | No | No |
| Student UX | Student dashboard | Requires JupyterHub | Minimal |
| Moodle integration | Native API | None | None |
| Parallel autograding | Yes | Manual | Docker |
| Sandboxed execution | Partial (uv + rlimits) | Partial (JupyterHub) | Docker |
| Partial credit | Yes (weighted) | Limited | Yes |
| Gradescope/Canvas support | No | Partial | Yes |
| Community/maturity | Solo/new | Mature | Active |
| Documentation | Growing | Good | Good |
