# Installation

## Stable release

```bash
pip install mograder
# or:
uv add mograder
```

## Development version

```bash
git clone https://github.com/jameskermode/mograder.git
cd mograder
uv venv && uv pip install -e ".[dev]"
```

## Optional extras

mograder has several optional dependency groups:

| Extra | Purpose |
|-------|---------|
| `dev` | Testing, linting, and development tools |
| `editor` | Marimo sandbox support (`marimo[sandbox]`) |
| `grader` | Plotting and visualization for grading (`seaborn`, `matplotlib`) |
| `asgi` | ASGI deployment of the formgrader (`starlette`, `uvicorn`) |
| `docs` | Documentation site building (`mkdocs-material`, `mkdocstrings`) |

Install multiple extras with:

```bash
pip install "mograder[dev,asgi]"
# or:
uv sync --extra dev --extra asgi
```
