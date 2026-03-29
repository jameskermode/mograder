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
uv sync --extra dev
```

## Optional extras

mograder has several optional dependency groups:

| Extra | Purpose |
|-------|---------|
| `asgi` | ASGI deployment (`starlette`, `uvicorn`) |
| `grader` | Grader dashboard (includes `asgi` + `altair`) |
| `hub` | Hub multi-user server (includes `grader` + `fastapi`, `lzstring`, `python-multipart`) |
| `dev` | Testing and linting (includes `hub` + `pytest`, `ruff`, `markdown-it-py`) |
| `editor` | Marimo sandbox support (`marimo[sandbox]`) |
| `docs` | Documentation site building (`mkdocs-material`, `mkdocstrings`) |

Install extras with:

```bash
uv pip install "mograder[grader]" # grader dashboard
uv pip install "mograder[hub]"    # hub server (includes grader)
uv pip install "mograder[dev]"    # development (includes hub)
# or with uv:
uv sync --extra dev
```
