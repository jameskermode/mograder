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
| `hub` | Hub multi-user server (`fastapi`, `starlette`, `uvicorn`, `lzstring`) |
| `dev` | Testing and linting (includes `hub` deps + `pytest`, `ruff`, `markdown-it-py`) |
| `editor` | Marimo sandbox support (`marimo[sandbox]`) |
| `docs` | Documentation site building (`mkdocs-material`, `mkdocstrings`) |

Install extras with:

```bash
pip install "mograder[hub]"       # hub server
pip install "mograder[dev]"       # development (includes hub)
# or with uv:
uv sync --extra dev
```
