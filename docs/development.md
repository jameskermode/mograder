# Development

## Setup

```bash
git clone https://github.com/jameskermode/mograder.git
cd mograder
uv sync --extra dev
```

## Testing

```bash
uv run pytest              # run all tests
uv run pytest -x -q        # stop on first failure
uv run pytest -k pattern   # run tests matching pattern
```

## Linting and formatting

```bash
uv run ruff check src/     # lint
uv run ruff format src/ tests/  # auto-format
```

A pre-commit hook enforces formatting and checks that `examples/release/` stays in sync with regenerated output from `examples/source/`.

## Regenerating examples

CI checks freshness — release examples must be committed in sync with source:

```bash
uv run mograder generate examples/source/demo-assignment/demo-assignment.py examples/source/demo-holistic/demo-holistic.py -o examples/release
```

## License

MIT
