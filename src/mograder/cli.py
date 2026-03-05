"""Click CLI for mograder: generate, autograde, feedback."""

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path


def _rel(p: Path) -> str:
    """Return a short relative path string for display."""
    try:
        return os.path.relpath(p)
    except ValueError:
        return str(p)


import click

from mograder import cells, feedback, integrity, markers, moodle, runner


def _infer_output_dir(
    input_path: Path,
    expected_parent: str,
    target_dir: str,
    fallback: str,
) -> Path:
    """Infer output directory from nbgrader-style directory convention.

    If *input_path* is inside *expected_parent/* (e.g. ``source/assignment/nb.py``),
    return the sibling *target_dir* (e.g. ``release/assignment/``).
    Otherwise return *fallback*.
    """
    # Check grandparent: source/assignment-name/file.py → grandparent = source
    grandparent = input_path.parent.parent
    if grandparent.name == expected_parent:
        return grandparent.parent / target_dir / input_path.parent.name
    # Check parent: source/file.py → parent = source
    if input_path.parent.name == expected_parent:
        return input_path.parent.parent / target_dir
    return Path(fallback)


def _find_source(submitted_path: Path) -> Path | None:
    """Auto-discover the source notebook for a submitted file.

    Looks for ``source/<assignment>/<name>.py`` relative to the submitted
    file's directory structure.
    """
    assignment = submitted_path.parent.name
    name = submitted_path.name
    # Walk up to find source/ sibling
    for ancestor in [submitted_path.parent.parent, submitted_path.parent.parent.parent]:
        candidate = ancestor / "source" / assignment / name
        if candidate.exists():
            return candidate
    return None


@click.group()
def cli():
    """mograder — Semi-automated grading for Marimo notebooks."""


@cli.command()
@click.argument(
    "files", nargs=-1, required=True, type=click.Path(exists=True, path_type=Path)
)
@click.option(
    "-o",
    "--output-dir",
    type=click.Path(path_type=Path),
    default=None,
    help="Output directory (default: release/)",
)
@click.option("--dry-run", is_flag=True, help="Preview changes without writing files")
@click.option(
    "--validate", is_flag=True, help="Only validate markers, don't generate output"
)
def generate(files, output_dir, dry_run, validate):
    """Strip solutions from source notebooks to produce release versions."""
    if output_dir is None:
        output_dir = _infer_output_dir(files[0], "source", "release", "release")

    success = True
    processed_dirs: set[Path] = set()
    files_set = set(files)
    for filepath in files:
        if filepath.suffix != ".py":
            click.echo(f"SKIP: {filepath} (not a .py file)")
            continue
        # Preserve assignment subdirectory in output
        dest_dir = (
            output_dir / filepath.parent.name
            if filepath.parent.name != "."
            else output_dir
        )
        if not markers.process_file(filepath, dest_dir, dry_run, validate):
            success = False
        else:
            processed_dirs.add(filepath.parent)

    # Copy auxiliary files from each source dir to release dir
    if not dry_run and not validate:
        for src_dir in processed_dirs:
            rel_dir = output_dir / src_dir.name if src_dir.name != "." else output_dir
            for f in src_dir.iterdir():
                if f.is_dir():
                    continue
                if f.suffix == ".py" and f in files_set:
                    continue  # already processed as notebook
                dest = rel_dir / f.name
                if not dest.exists() or f.stat().st_mtime > dest.stat().st_mtime:
                    rel_dir.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(f, dest)
                    click.echo(f"COPY: {_rel(f)} → {_rel(dest)}")

    if not success:
        sys.exit(1)


@cli.command()
@click.argument(
    "files", nargs=-1, required=True, type=click.Path(exists=True, path_type=Path)
)
@click.option(
    "--source",
    "source_path",
    type=click.Path(exists=True, path_type=Path),
    default=None,
    help="Source notebook (with solutions); auto-discovered from source/ directory if omitted",
)
@click.option(
    "--csv",
    "csv_path",
    type=click.Path(path_type=Path),
    default=None,
    help="Write verification results to CSV file",
)
@click.option("-j", "--jobs", type=int, default=4, help="Number of parallel workers")
@click.option(
    "--timeout", type=int, default=300, help="Timeout per notebook in seconds"
)
@click.option(
    "-o",
    "--output-dir",
    type=click.Path(path_type=Path),
    default=None,
    help="Output directory for grading copies (default: autograded/)",
)
@click.option(
    "--progress",
    "progress",
    is_flag=True,
    hidden=True,
    help="Emit JSON progress lines to stderr (machine-readable)",
)
def autograde(files, source_path, csv_path, jobs, timeout, output_dir, progress):
    """Run notebooks and inject grading cells for GTA review."""
    notebooks = [f for f in files if f.suffix == ".py"]
    if not notebooks:
        click.echo("ERROR: no valid .py files found", err=True)
        sys.exit(1)

    if output_dir is None:
        output_dir = _infer_output_dir(
            notebooks[0], "submitted", "autograded", "autograded"
        )

    # Auto-discover source notebook if not given
    if source_path is None:
        found = _find_source(notebooks[0])
        if found:
            source_path = found
            click.echo(f"Auto-discovered source: {_rel(source_path)}")

    # Optionally run source solution first
    all_labels: list[str] = []
    marks: dict[str, int | float] | None = None
    source_text: str | None = None
    shared_sandbox: Path | None = None
    if source_path:
        click.echo(f"Running source notebook: {_rel(source_path)}")
        if progress:
            click.echo(json.dumps({"event": "sandbox_start"}), err=True)
        shared_sandbox = runner.create_shared_sandbox(source_path)
        if progress:
            click.echo(
                json.dumps(
                    {"event": "sandbox_done", "created": shared_sandbox is not None}
                ),
                err=True,
            )
        if shared_sandbox:
            click.echo(f"  Shared sandbox: {_rel(shared_sandbox)}")
        source_result = runner.run_notebook(
            source_path, timeout=timeout, sandbox_dir=shared_sandbox
        )
        if source_result.checks:
            all_labels = [c.label for c in source_result.checks]
            n_pass = sum(1 for c in source_result.checks if c.status == "success")
            click.echo(
                f"  → {n_pass}/{len(source_result.checks)} checks pass "
                f"({source_result.cell_errors} cell errors)"
            )
        else:
            click.echo("  → WARNING: no check results found in source notebook")

        # Parse per-question marks metadata
        source_text = source_path.read_text()
        source_lines = source_text.splitlines(keepends=True)
        marks = cells.parse_marks_metadata(source_lines)
        if marks:
            marks_info = " ".join(f"{k}={v}" for k, v in marks.items())
            total = sum(marks.values())
            click.echo(f"  Marks metadata: {marks_info} (total: {total})")

    # Integrity check + reinject tampered cells
    run_paths: list[Path] = list(notebooks)
    tamper_info: dict[str, integrity.IntegrityResult] = {}
    fixed_dir: Path | None = None
    if source_text:
        fixed_dir = Path(tempfile.mkdtemp())
        run_paths = []
        for nb in notebooks:
            ir = integrity.check_integrity(source_text, nb.read_text())
            if ir.tampered_checks or ir.tampered_marks:
                fixed = fixed_dir / nb.name
                fixed.write_text(ir.fixed_source)
                run_paths.append(fixed)
                tamper_info[nb.stem] = ir
                warns = [f"check({k})" for k in ir.tampered_checks]
                if ir.tampered_marks:
                    warns.append("marks")
                click.echo(
                    f"  WARNING: {nb.stem} — tampered cells reinjected: "
                    f"{', '.join(warns)}"
                )
            else:
                run_paths.append(nb)

    # Run student submissions
    click.echo(f"Autograding {len(notebooks)} submission(s) with {jobs} workers...")

    progress_cb = None
    if progress:
        click.echo(
            json.dumps({"event": "start", "total": len(run_paths)}),
            err=True,
        )

        def progress_cb(completed, total, nb_path):
            click.echo(
                json.dumps(
                    {
                        "event": "progress",
                        "completed": completed,
                        "total": total,
                        "notebook": nb_path.name,
                    }
                ),
                err=True,
            )

    results = runner.run_batch(
        run_paths,
        jobs=jobs,
        timeout=timeout,
        on_progress=progress_cb,
        sandbox_dir=shared_sandbox,
    )

    # Map results back to original paths + record tampering
    for r in results:
        original = next((nb for nb in notebooks if nb.name == r.path.name), r.path)
        r.path = original
        if original.stem in tamper_info:
            ti = tamper_info[original.stem]
            r.tampered = [f"check({k})" for k in ti.tampered_checks]
            if ti.tampered_marks:
                r.tampered.append("marks")

    if fixed_dir:
        shutil.rmtree(fixed_dir, ignore_errors=True)

    # Discover labels from results if no source notebook
    if not all_labels:
        all_labels = runner.discover_labels(results)

    # Print summary
    runner.print_summary(results, all_labels, marks)

    # Inject grading cells and write to output dir
    output_dir.mkdir(parents=True, exist_ok=True)
    for result in results:
        if not result.export_ok:
            continue
        source_lines = result.path.read_text().splitlines(keepends=True)
        modified = cells.inject_grading_cells(
            source_lines, result.checks, result.cell_errors, marks
        )
        dest = output_dir / result.path.name
        dest.write_text("".join(modified))
        click.echo(f"  Grading copy: {_rel(dest)}")

    # Write CSV if requested
    if csv_path:
        runner.write_csv(results, all_labels, csv_path, marks)


@cli.command()
@click.argument(
    "files", nargs=-1, required=True, type=click.Path(exists=True, path_type=Path)
)
@click.option(
    "-o",
    "--output-dir",
    type=click.Path(path_type=Path),
    default=None,
    help="Output directory for HTML feedback (default: feedback/)",
)
@click.option(
    "--grades-csv",
    type=click.Path(path_type=Path),
    default=None,
    help="Write aggregated grades to CSV",
)
@click.option(
    "--timeout", type=int, default=300, help="Timeout per notebook in seconds"
)
@click.option("-j", "--jobs", type=int, default=4, help="Number of parallel workers")
def feedback_cmd(files, output_dir, grades_csv, timeout, jobs):
    """Export graded notebooks to HTML and aggregate grades."""
    notebooks = [f for f in files if f.suffix == ".py"]
    if not notebooks:
        click.echo("ERROR: no valid .py files found", err=True)
        sys.exit(1)

    if output_dir is None:
        output_dir = _infer_output_dir(
            notebooks[0], "autograded", "feedback", "feedback"
        )

    # Collect grades from graded notebooks
    grades = feedback.collect_grades(notebooks)
    n_graded = sum(1 for g in grades if g["mark"] is not None)
    click.echo(f"{n_graded}/{len(notebooks)} notebooks have been graded")

    # Export each to HTML
    output_dir_path = (
        Path(output_dir) if not isinstance(output_dir, Path) else output_dir
    )
    for nb in notebooks:
        try:
            html_path = feedback.export_feedback_html(
                nb, output_dir_path, timeout=timeout
            )
            click.echo(f"  Exported: {_rel(html_path)}")
        except Exception as e:
            click.echo(f"  FAILED: {_rel(nb)} — {e}", err=True)

    # Write grades CSV if requested
    if grades_csv:
        feedback.write_grades_csv(grades, grades_csv)


# Register the feedback command with its proper name
cli.add_command(feedback_cmd, "feedback")


@cli.command()
@click.argument("worksheet", type=click.Path(exists=True, path_type=Path))
@click.option(
    "--grades-csv",
    required=True,
    type=click.Path(exists=True, path_type=Path),
    help="mograder grades CSV",
)
@click.option(
    "--feedback-dir",
    type=click.Path(exists=True, path_type=Path),
    default=None,
    help="Directory with {student}.html files; creates feedback ZIP",
)
@click.option(
    "-o",
    "--output-dir",
    type=click.Path(path_type=Path),
    default="export",
    help="Output directory (default: export/)",
)
@click.option(
    "--match-column",
    default="Username",
    help="Moodle CSV column to match student against (default: Username)",
)
def moodle_cmd(worksheet, grades_csv, feedback_dir, output_dir, match_column):
    """Merge grades into a Moodle offline grading worksheet."""
    # Read inputs
    fieldnames, moodle_rows = moodle.read_moodle_worksheet(worksheet)

    # Validate match column
    if match_column not in fieldnames:
        click.echo(
            f"ERROR: match column '{match_column}' not found in worksheet "
            f"(available: {', '.join(fieldnames)})",
            err=True,
        )
        sys.exit(1)

    grades = moodle.read_grades_csv(grades_csv)

    # Merge
    updated_rows, result = moodle.merge_grades(moodle_rows, grades, match_column)

    # Report
    click.echo(f"Matched: {result.matched}, Skipped: {result.skipped}")
    for warning in result.warnings:
        click.echo(f"  {warning}")

    # Write updated CSV
    output_dir.mkdir(parents=True, exist_ok=True)
    out_csv = output_dir / worksheet.name
    moodle.write_moodle_csv(updated_rows, fieldnames, out_csv)
    click.echo(f"Wrote: {_rel(out_csv)}")

    # Build feedback ZIP if requested
    if feedback_dir:
        zip_path = output_dir / f"feedback_{worksheet.stem}.zip"
        count = moodle.build_feedback_zip(
            updated_rows, feedback_dir, zip_path, match_column
        )
        click.echo(f"Feedback ZIP: {_rel(zip_path)} ({count} files)")

    # Statistics
    if result.marks:
        click.echo("")
        click.echo(moodle.compute_statistics(result.marks))


cli.add_command(moodle_cmd, "moodle")


@cli.command()
@click.argument(
    "course_dir",
    type=click.Path(exists=True, path_type=Path),
    default=".",
)
@click.option("-p", "--port", type=int, default=None, help="Port for marimo app")
@click.option("--headless", is_flag=True, help="Don't open browser")
def formgrader(course_dir, port, headless):
    """Launch the formgrader dashboard for managing grading."""
    import os
    import subprocess as sp

    app_path = Path(__file__).parent / "formgrader_app.py"
    os.environ["MOGRADER_COURSE_DIR"] = str(course_dir.resolve())

    cmd = [sys.executable, "-m", "marimo", "run", str(app_path)]
    if port:
        cmd.extend(["--port", str(port)])
    if headless:
        cmd.append("--headless")

    click.echo(f"Launching formgrader for: {course_dir.resolve()}")
    try:
        proc = sp.run(cmd)
        sys.exit(proc.returncode)
    except KeyboardInterrupt:
        pass
