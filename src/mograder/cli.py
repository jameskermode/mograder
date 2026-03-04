"""Click CLI for mograder: generate, verify, feedback."""

import sys
from pathlib import Path

import click

from mograder import cells, feedback, markers, runner
from mograder.models import CheckResult


@click.group()
def cli():
    """mograder — Semi-automated grading for Marimo notebooks."""


@cli.command()
@click.argument("files", nargs=-1, required=True, type=click.Path(exists=True, path_type=Path))
@click.option("-o", "--output-dir", type=click.Path(path_type=Path), default="release",
              help="Output directory (default: release/)")
@click.option("--dry-run", is_flag=True, help="Preview changes without writing files")
@click.option("--validate", is_flag=True, help="Only validate markers, don't generate output")
def generate(files, output_dir, dry_run, validate):
    """Strip solutions from staff notebooks to produce student versions."""
    success = True
    for filepath in files:
        if filepath.suffix != ".py":
            click.echo(f"SKIP: {filepath} (not a .py file)")
            continue
        if not markers.process_file(filepath, output_dir, dry_run, validate):
            success = False
    if not success:
        sys.exit(1)


@cli.command()
@click.argument("files", nargs=-1, required=True, type=click.Path(exists=True, path_type=Path))
@click.option("--staff", type=click.Path(exists=True, path_type=Path), default=None,
              help="Staff source notebook (run first to establish expected labels)")
@click.option("--csv", "csv_path", type=click.Path(path_type=Path), default=None,
              help="Write verification results to CSV file")
@click.option("-j", "--jobs", type=int, default=4, help="Number of parallel workers")
@click.option("--timeout", type=int, default=300, help="Timeout per notebook in seconds")
@click.option("-o", "--output-dir", type=click.Path(path_type=Path), default="grading",
              help="Output directory for grading copies (default: grading/)")
def verify(files, staff, csv_path, jobs, timeout, output_dir):
    """Run notebooks and inject grading cells for GTA review."""
    notebooks = [f for f in files if f.suffix == ".py"]
    if not notebooks:
        click.echo("ERROR: no valid .py files found", err=True)
        sys.exit(1)

    # Optionally run staff solution first
    all_labels: list[str] = []
    if staff:
        click.echo(f"Running staff solution: {staff}")
        staff_result = runner.run_notebook(staff, timeout=timeout)
        if staff_result.checks:
            all_labels = [c.label for c in staff_result.checks]
            n_pass = sum(1 for c in staff_result.checks if c.status == "success")
            click.echo(
                f"  → {n_pass}/{len(staff_result.checks)} checks pass "
                f"({staff_result.cell_errors} cell errors)"
            )
        else:
            click.echo("  → WARNING: no check results found in staff notebook")

    # Run student submissions
    click.echo(f"Verifying {len(notebooks)} submission(s) with {jobs} workers...")
    results = runner.run_batch(notebooks, jobs=jobs, timeout=timeout)

    # Discover labels from results if no staff notebook
    if not all_labels:
        all_labels = runner.discover_labels(results)

    # Print summary
    runner.print_summary(results, all_labels)

    # Inject grading cells and write to output dir
    output_dir.mkdir(parents=True, exist_ok=True)
    for result in results:
        if not result.export_ok:
            continue
        source_lines = result.path.read_text().splitlines(keepends=True)
        modified = cells.inject_grading_cells(source_lines, result.checks, result.cell_errors)
        dest = output_dir / result.path.name
        dest.write_text("".join(modified))
        click.echo(f"  Grading copy: {dest}")

    # Write CSV if requested
    if csv_path:
        runner.write_csv(results, all_labels, csv_path)


@cli.command()
@click.argument("files", nargs=-1, required=True, type=click.Path(exists=True, path_type=Path))
@click.option("-o", "--output-dir", type=click.Path(path_type=Path), default="feedback",
              help="Output directory for HTML feedback (default: feedback/)")
@click.option("--grades-csv", type=click.Path(path_type=Path), default=None,
              help="Write aggregated grades to CSV")
@click.option("--timeout", type=int, default=300, help="Timeout per notebook in seconds")
@click.option("-j", "--jobs", type=int, default=4, help="Number of parallel workers")
def feedback_cmd(files, output_dir, grades_csv, timeout, jobs):
    """Export graded notebooks to HTML and aggregate grades."""
    notebooks = [f for f in files if f.suffix == ".py"]
    if not notebooks:
        click.echo("ERROR: no valid .py files found", err=True)
        sys.exit(1)

    # Collect grades from graded notebooks
    grades = feedback.collect_grades(notebooks)
    n_graded = sum(1 for g in grades if g["mark"] is not None)
    click.echo(f"{n_graded}/{len(notebooks)} notebooks have been graded")

    # Export each to HTML
    output_dir_path = Path(output_dir) if not isinstance(output_dir, Path) else output_dir
    for nb in notebooks:
        try:
            html_path = feedback.export_feedback_html(nb, output_dir_path, timeout=timeout)
            click.echo(f"  Exported: {html_path}")
        except Exception as e:
            click.echo(f"  FAILED: {nb} — {e}", err=True)

    # Write grades CSV if requested
    if grades_csv:
        feedback.write_grades_csv(grades, grades_csv)


# Register the feedback command with its proper name
cli.add_command(feedback_cmd, "feedback")
