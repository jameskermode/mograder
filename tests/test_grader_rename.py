"""Verify formgrader → grader rename."""

from click.testing import CliRunner

from mograder.cli import cli


def test_grader_command_exists():
    runner = CliRunner()
    result = runner.invoke(cli, ["grader", "--help"])
    assert result.exit_code == 0
    assert "grader" in result.output.lower()


def test_formgrader_command_gone():
    runner = CliRunner()
    result = runner.invoke(cli, ["formgrader", "--help"])
    assert result.exit_code != 0
