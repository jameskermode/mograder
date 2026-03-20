# Contributing to mograder

Thank you for your interest in contributing to mograder! This document explains how to get involved.

## Reporting bugs

Please open an issue on [GitHub Issues](https://github.com/jameskermode/mograder/issues) with:

- A clear description of the problem
- Steps to reproduce
- Expected vs actual behaviour
- Your environment (OS, Python version, mograder version)

## Suggesting features

Open a [GitHub Issue](https://github.com/jameskermode/mograder/issues) describing the feature, your use case, and any alternatives you've considered.

## Contributing code

1. Fork the repository and create a branch from `main`.
2. Set up the development environment — see the [development guide](docs/development.md).
3. Make your changes, adding tests where appropriate.
4. Ensure all tests pass and code is formatted:
   ```bash
   uv run pytest
   uv run ruff check src/
   uv run ruff format src/ tests/
   ```
5. Open a pull request against `main` with a clear description of the change.

## Code style

- Code is formatted and linted with [ruff](https://docs.astral.sh/ruff/).
- A pre-commit hook enforces formatting — run `uv run ruff format src/ tests/` before committing.
- If you modify files in `examples/source/`, regenerate release examples and commit the updated files (see [development guide](docs/development.md#regenerating-examples)).

## Testing

- Tests live in `tests/` and use pytest.
- CI runs tests on Python 3.11, 3.12, and 3.13 across Linux and macOS.
- Please add or update tests for any new functionality or bug fixes.

## Code of Conduct

This project follows the [Contributor Covenant Code of Conduct](CODE_OF_CONDUCT.md). By participating, you are expected to uphold this code.

## License

By contributing, you agree that your contributions will be licensed under the [MIT License](LICENSE).
