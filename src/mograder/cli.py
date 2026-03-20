"""Click CLI for mograder: generate, autograde, feedback."""

import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

import click

from mograder import cells, feedback, integrity, markers, moodle, runner
from mograder.gradebook import Gradebook

_TIMESTAMP_RE = re.compile(r"_\d{8}T\d{6}$")


def _rel(p: Path) -> str:
    """Return a short relative path string for display."""
    try:
        return os.path.relpath(p)
    except ValueError:
        return str(p)


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


def _resolve_assignments(
    args: tuple[str | Path, ...],
    base_dir: str,
) -> tuple[Path, ...]:
    """Resolve assignment names or file paths to .py files.

    An arg without path separators or .py suffix is treated as an
    assignment name and expanded to <base_dir>/<name>/*.py.
    Otherwise it's treated as a file path.
    """
    resolved = []
    for arg in args:
        s = str(arg)
        if "/" not in s and os.sep not in s and not s.endswith(".py"):
            d = Path(base_dir) / s
            if not d.is_dir():
                # Try prefix match: "A0" matches "A0-Probability"
                parent = Path(base_dir)
                if parent.is_dir():
                    matches = sorted(
                        p
                        for p in parent.iterdir()
                        if p.is_dir() and p.name.startswith(s + "-")
                    )
                    if len(matches) == 1:
                        d = matches[0]
                    elif len(matches) > 1:
                        names = ", ".join(m.name for m in matches)
                        raise click.UsageError(
                            f"Ambiguous assignment '{s}': matches {names}"
                        )
                if not d.is_dir():
                    raise click.UsageError(f"Assignment directory not found: {d}")
            # Only include the main notebook (matching directory name), not auxiliary modules
            main = d / f"{d.name}.py"
            if main.exists():
                resolved.append(main)
            else:
                # Fallback: all .py files (backward compat for flat layouts)
                py = sorted(
                    f for f in d.glob("*.py") if not _TIMESTAMP_RE.search(f.stem)
                )
                if not py:
                    raise click.UsageError(f"No .py files in {d}")
                resolved.extend(py)
        else:
            p = Path(s)
            if not p.exists():
                raise click.UsageError(f"File not found: {p}")
            resolved.append(p)
    return tuple(resolved)


def _find_source_for_assignment(assignment_name: str, source_dir: str) -> Path | None:
    """Find the source notebook for an assignment by directory name."""
    d = Path(source_dir) / assignment_name
    if not d.is_dir():
        return None
    py = sorted(d.glob("*.py"))
    return py[0] if py else None


def _find_source(submitted_path: Path, source_dir: str = "source") -> Path | None:
    """Auto-discover the source notebook for a submitted file.

    Looks for ``<source_dir>/<assignment>/<name>.py`` relative to the submitted
    file's directory structure.
    """
    assignment = submitted_path.parent.name
    name = submitted_path.name
    # Walk up to find source_dir sibling
    for ancestor in [submitted_path.parent.parent, submitted_path.parent.parent.parent]:
        candidate = ancestor / source_dir / assignment / name
        if candidate.exists():
            return candidate
    return None


def _find_gradebook(path: Path, gradebook_name: str = "gradebook.db") -> Path | None:
    """Walk up from *path* looking for a gradebook database file.

    Searches furthest ancestor first so the course-root DB is preferred
    over a stale copy that may exist closer to the notebook.
    """
    candidates = [path.parent.parent.parent, path.parent.parent, path.parent]
    for ancestor in candidates:
        candidate = ancestor / gradebook_name
        if candidate.is_file():
            return candidate
    return None


def _compute_auto_mark(
    checks: list, marks: dict[str, int | float] | None
) -> float | None:
    """Compute auto-scored marks from check results and marks metadata."""
    if marks is None:
        return None
    check_keys = {c.label.split(":")[0].strip() for c in checks}
    return sum(
        marks[k]
        for k in check_keys
        if k in marks
        and any(
            c.status == "success" for c in checks if c.label.split(":")[0].strip() == k
        )
    )


@click.group()
@click.pass_context
def cli(ctx):
    """mograder — Semi-automated grading for Marimo notebooks."""
    from mograder.config import load_config

    ctx.ensure_object(dict)
    config = load_config(Path.cwd())
    ctx.obj["config"] = config
    ctx.default_map = ctx.default_map or {}
    ctx.default_map.setdefault("autograde", {}).update(
        {"jobs": config.jobs, "timeout": config.timeout}
    )
    ctx.default_map.setdefault("feedback", {}).update(
        {"jobs": config.jobs, "timeout": config.timeout}
    )
    ctx.default_map.setdefault("moodle", {}).setdefault("export", {}).update(
        {"match_column": config.moodle_match_column}
    )


@cli.command()
@click.argument("assignments", nargs=-1, required=True, metavar="ASSIGNMENTS...")
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
@click.option(
    "--no-validate",
    is_flag=True,
    help="Skip source notebook validation (running checks)",
)
@click.option(
    "--submit-url",
    default=None,
    help="Inject a submit cell with this server URL into release notebooks",
)
@click.option(
    "--progress",
    is_flag=True,
    help="Emit JSON progress events to stderr (for formgrader UI)",
)
@click.pass_context
def generate(
    ctx, assignments, output_dir, dry_run, validate, no_validate, submit_url, progress
):
    """Strip solutions from source notebooks to produce release versions.

    ASSIGNMENTS can be assignment names (e.g. "demo-assignment") which are
    auto-expanded to source/demo-assignment/*.py, or explicit file paths.
    """
    config = ctx.obj["config"]
    files = _resolve_assignments(assignments, config.source_dir)
    if output_dir is None:
        # Infer the base release dir — the loop below adds assignment subdirs
        grandparent = files[0].parent.parent
        if grandparent.name == config.source_dir:
            output_dir = grandparent.parent / config.release_dir
        else:
            output_dir = Path(config.release_dir)

    # Pre-run validation: execute source notebooks and check results
    py_files = [f for f in files if f.suffix == ".py"]
    if no_validate and not validate and not dry_run:
        click.echo("WARNING: skipping source validation (--no-validate)")
    elif not validate and not dry_run:
        from .runner import create_shared_sandbox, run_notebook

        if progress:
            # Phase 1: validate source (N) + strip (1) + Phase 3: validate release (N)
            click.echo(
                json.dumps({"event": "start", "total": len(py_files) * 2 + 1}),
                err=True,
            )
            click.echo(json.dumps({"event": "sandbox_start"}), err=True)

        validation_ok = True
        shared_sandbox = None
        for i, filepath in enumerate(py_files):
            click.echo(f"VALIDATE: {_rel(filepath)} ... ", nl=False)
            if shared_sandbox is None:
                shared_sandbox = create_shared_sandbox(filepath)
            if progress:
                click.echo(
                    json.dumps(
                        {
                            "event": "sandbox_done",
                            "created": shared_sandbox is not None,
                        }
                    ),
                    err=True,
                )
                click.echo(
                    json.dumps(
                        {
                            "event": "progress",
                            "completed": i,
                            "total": len(py_files) + 1,
                            "notebook": f"validating {filepath.name}",
                        }
                    ),
                    err=True,
                )
            check_cb = None
            if progress:

                def check_cb(cr, _fp=filepath):
                    status = "PASS" if cr.status == "success" else "FAIL"
                    click.echo(
                        json.dumps(
                            {
                                "event": "check",
                                "notebook": _fp.name,
                                "label": cr.label,
                                "status": status,
                            }
                        ),
                        err=True,
                    )

            result = run_notebook(
                filepath,
                sandbox_dir=shared_sandbox,
                on_check=check_cb,
                rlimit_nproc=0,
                rlimit_nofile=0,
                rlimit_as=0,
            )
            if not result.export_ok:
                click.echo(f"FAIL (export error: {result.export_error})")
                validation_ok = False
                continue
            if result.cell_errors > 0:
                click.echo(f"FAIL ({result.cell_errors} cell errors)")
                validation_ok = False
                continue
            failed = [c for c in result.checks if c.status != "success"]
            if failed:
                labels = ", ".join(c.label for c in failed)
                click.echo(f"FAIL ({len(failed)} checks: {labels})")
                validation_ok = False
                continue
            click.echo("OK")
        if not validation_ok:
            sys.exit(1)

        if progress:
            click.echo(
                json.dumps(
                    {
                        "event": "progress",
                        "completed": len(py_files),
                        "total": len(py_files) + 1,
                        "notebook": "stripping solutions",
                    }
                ),
                err=True,
            )

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
        if not markers.process_file(
            filepath, dest_dir, dry_run, validate, submit_url=submit_url
        ):
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

    # Build release zip for each processed directory
    if not dry_run and not validate:
        for src_dir in processed_dirs:
            rel_dir = output_dir / src_dir.name if src_dir.name != "." else output_dir
            if rel_dir.is_dir():
                zip_path = markers.build_release_zip(rel_dir)
                click.echo(f"ZIP: {_rel(zip_path)}")

    # Phase 3: Validate release notebooks (no cell errors allowed)
    if not dry_run and not validate and not no_validate:
        from .runner import create_shared_sandbox, run_notebook

        click.echo("\n--- Phase 3: Validating release notebooks ---")
        release_ok = True
        release_sandbox = None
        for ri, filepath in enumerate(py_files):
            dest_dir = (
                output_dir / filepath.parent.name
                if filepath.parent.name != "."
                else output_dir
            )
            release_path = dest_dir / filepath.name
            if not release_path.exists():
                continue
            click.echo(f"RELEASE-CHECK: {_rel(release_path)} ... ", nl=False)
            if progress:
                click.echo(
                    json.dumps(
                        {
                            "event": "progress",
                            "completed": len(py_files) + 1 + ri,
                            "total": len(py_files) * 2 + 1,
                            "notebook": f"checking release {release_path.name}",
                        }
                    ),
                    err=True,
                )
            if release_sandbox is None:
                release_sandbox = create_shared_sandbox(release_path)
            result = run_notebook(
                release_path,
                sandbox_dir=release_sandbox,
                rlimit_nproc=0,
                rlimit_nofile=0,
                rlimit_as=0,
            )
            if not result.export_ok:
                click.echo(f"FAIL (export error: {result.export_error})")
                release_ok = False
                continue
            if result.cell_errors > 0:
                click.echo(f"FAIL ({result.cell_errors} cell errors)")
                release_ok = False
                continue
            click.echo("OK")
        if not release_ok:
            click.echo("ERROR: release notebook validation failed", err=True)
            success = False

    if not success:
        sys.exit(1)


@cli.command("wasm-export")
@click.argument("assignments", nargs=-1)
@click.option(
    "--all", "export_all", is_flag=True, help="Export all WASM-compatible assignments"
)
@click.option(
    "--check-only", is_flag=True, help="Only check compatibility, don't export"
)
@click.option("--mode", default="edit", help="WASM mode: edit or run")
@click.pass_context
def wasm_export(ctx, assignments, export_all, check_only, mode):
    """Check WASM compatibility and export compatible assignments.

    With --check-only, prints a compatibility table without exporting.
    Without arguments, use --all to process all assignments.
    """
    import subprocess as sp

    from mograder.wasm_compat import check_wasm_compatible

    config = ctx.obj["config"]
    source_dir = Path(config.source_dir)
    release_dir = Path(config.release_dir)

    # Discover all assignment directories
    if not source_dir.is_dir():
        click.echo(f"ERROR: source directory not found: {source_dir}", err=True)
        sys.exit(1)

    all_dirs = sorted(
        d for d in source_dir.iterdir() if d.is_dir() and any(d.glob("*.py"))
    )

    # Filter to requested assignments
    if assignments:
        selected = []
        for name in assignments:
            matches = [
                d for d in all_dirs if d.name == name or d.name.startswith(name + "-")
            ]
            if not matches:
                # Try matching by dir field from config
                for a in config.assignments:
                    if a.get("dir") == name:
                        matches = [
                            d
                            for d in all_dirs
                            if d.name.startswith(a.get("dir", "") + "-")
                            or d.name == name
                        ]
                        break
                if not matches:
                    click.echo(f"WARNING: no source directory found for '{name}'")
            selected.extend(matches)
        all_dirs = selected
    elif not export_all and not check_only:
        click.echo("ERROR: specify assignment names or use --all", err=True)
        sys.exit(1)

    # Check compatibility of each
    click.echo(f"{'Assignment':<40} {'Status':<8} {'Blockers'}")
    click.echo("-" * 70)

    compatible_dirs: list[Path] = []
    for d in all_dirs:
        py_files = sorted(d.glob("*.py"))
        if not py_files:
            continue
        nb_path = py_files[0]
        is_compat, blockers = check_wasm_compatible(nb_path)
        status = "WASM" if is_compat else "LIVE"
        blocker_str = ", ".join(blockers) if blockers else ""
        click.echo(f"{d.name:<40} {status:<8} {blocker_str}")
        if is_compat:
            compatible_dirs.append(d)

    click.echo(f"\n{len(compatible_dirs)}/{len(all_dirs)} WASM-compatible")

    if check_only:
        return

    # Export each compatible assignment
    wasm_dir = Path(".mograder") / "wasm"
    for d in compatible_dirs:
        if assignments and not any(
            d.name == name or d.name.startswith(name + "-") for name in assignments
        ):
            continue

        # Determine release path
        release_nb = release_dir / d.name / (d.name + ".py")
        if not release_nb.exists():
            click.echo(f"\n  Generating release for {d.name}...")
            ctx.invoke(
                generate,
                assignments=(d.name,),
                output_dir=None,
                dry_run=False,
                validate=False,
                no_validate=True,
                submit_url=None,
                progress=False,
            )

        if not release_nb.exists():
            click.echo(f"  ERROR: release not found at {release_nb}", err=True)
            continue

        # Export to WASM
        # Extract dir name (e.g. A0 from ES98E-A0-Probability)
        short_name = d.name
        for a in config.assignments:
            if d.name.startswith(a.get("dir", "") + "-") or a.get("dir") in d.name:
                short_name = a["dir"]
                break

        out_dir = wasm_dir / short_name
        out_dir.mkdir(parents=True, exist_ok=True)
        click.echo(f"\n  Exporting {release_nb.name} to {out_dir}...")
        cmd = [
            sys.executable,
            "-m",
            "marimo",
            "export",
            "html-wasm",
            str(release_nb),
            "-o",
            str(out_dir) + "/",
            "--mode",
            mode,
        ]
        result = sp.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            click.echo(f"  FAILED: {result.stderr.strip()}", err=True)
        else:
            click.echo(f"  OK: {out_dir}")


@cli.command()
@click.argument("assignments", nargs=-1, required=True, metavar="ASSIGNMENTS...")
@click.option(
    "--timeout",
    type=int,
    default=300,
    help="Timeout per notebook in seconds",
)
@click.option(
    "--fix",
    is_flag=True,
    default=False,
    help="Restore modified non-solution cells from the release version",
)
@click.option(
    "--release",
    "release_path",
    type=click.Path(exists=True, path_type=Path),
    default=None,
    help="Path to release notebook (for --fix); auto-discovered from .mograder/release/ if omitted",
)
@click.pass_context
def validate(ctx, assignments, timeout, fix, release_path):
    """Run notebook(s) in a sandbox and report check results.

    ASSIGNMENTS can be assignment names (e.g. "A3-BayesianLinearRegression")
    which are auto-expanded to source/<name>/<name>.py, or explicit file paths.
    """
    from mograder.integrity import (
        fix_modified_cells,
        parse_assignment_name,
        validate_cell_hashes,
    )
    from mograder.runner import create_shared_sandbox, run_notebook

    config = ctx.obj["config"]
    files = _resolve_assignments(assignments, config.source_dir)

    any_failed = False
    for file in files:
        # --- Cell hash integrity check ---
        notebook_text = file.read_text()
        hash_warnings = validate_cell_hashes(notebook_text)
        if hash_warnings:
            click.echo("WARNING: The following non-solution cells have been modified:")
            for w in hash_warnings:
                click.echo(f"  Cell {w.index + 1}: {w.snippet}")

            if fix:
                # Find release notebook
                release_text = None
                if release_path:
                    release_text = release_path.read_text()
                else:
                    # Try .mograder/release/<assignment>/ cache
                    assignment = parse_assignment_name(notebook_text)
                    if assignment:
                        cache_dir = file.parent / ".mograder" / "release" / assignment
                        candidates = (
                            list(cache_dir.glob("*.py")) if cache_dir.is_dir() else []
                        )
                        if candidates:
                            release_text = candidates[0].read_text()

                if release_text:
                    fix_result = fix_modified_cells(release_text, notebook_text)
                    if fix_result.tampered_cells:
                        file.write_text(fix_result.fixed_source)
                        click.echo(
                            f"Fixed {len(fix_result.tampered_cells)} cell(s) from release"
                        )
                    else:
                        click.echo("No fixable differences found")
                else:
                    click.echo(
                        "Cannot fix: no release notebook found. "
                        "Use --release <path> or run 'mograder fetch' first."
                    )
            click.echo()

        click.echo("Installing dependencies...")
        sandbox = create_shared_sandbox(file)
        click.echo(f"Running {_rel(file)}...")
        result = run_notebook(
            file,
            sandbox_dir=sandbox,
            timeout=timeout,
            html_dir=file.parent,
            rlimit_nproc=0,
            rlimit_nofile=0,
            rlimit_as=0,
        )

        if not result.export_ok:
            click.echo(f"FAILED: {result.export_error}", err=True)
            any_failed = True
            continue

        if result.cell_errors > 0:
            click.echo(f"  {result.cell_errors} cell error(s)")

        if not result.checks:
            click.echo("No checks found")
            continue

        passed = sum(1 for c in result.checks if c.status == "success")
        total = len(result.checks)
        for c in result.checks:
            icon = "PASS" if c.status == "success" else "FAIL"
            click.echo(f"  {icon}: {c.label}")
            for msg in c.details:
                click.echo(f"        {msg}")

        click.echo(f"\n{passed}/{total} checks passed")
        if result.html_path:
            click.echo(f"Report: {result.html_path}")
        if passed < total:
            any_failed = True

    if any_failed:
        sys.exit(1)


@cli.command()
@click.argument("assignments", nargs=-1, required=False, metavar="[ASSIGNMENTS]...")
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
@click.option(
    "--moodle-csv",
    "moodle_csv_path",
    type=click.Path(exists=True, path_type=Path),
    default=None,
    help="Moodle offline grading CSV (use with --moodle-zip)",
)
@click.option(
    "--moodle-zip",
    "moodle_zip_path",
    type=click.Path(exists=True, path_type=Path),
    default=None,
    help="Moodle submission ZIP (use with --moodle-csv)",
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
@click.option(
    "--force",
    is_flag=True,
    help="Re-autograde all submissions even if output is up to date",
)
@click.option(
    "--safety-check",
    is_flag=True,
    help="Scan submitted code for dangerous patterns before execution",
)
@click.option(
    "--max-memory",
    type=int,
    default=None,
    help="Max virtual memory per notebook in MB (overrides config rlimits.as)",
)
@click.pass_context
def autograde(
    ctx,
    assignments,
    source_path,
    csv_path,
    moodle_csv_path,
    moodle_zip_path,
    jobs,
    timeout,
    output_dir,
    progress,
    force,
    safety_check,
    max_memory,
):
    """Run notebooks and inject grading cells for GTA review.

    ASSIGNMENTS can be assignment names (e.g. "A1") which are auto-expanded
    to submitted/A1/*.py, or explicit file paths.
    """
    config = ctx.obj["config"]

    # Moodle extraction mode: extract submissions from ZIP + CSV
    _moodle_submitted_dir = None
    if moodle_csv_path and moodle_zip_path:
        if not source_path:
            click.echo(
                "ERROR: --source is required when using --moodle-csv/--moodle-zip",
                err=True,
            )
            sys.exit(1)
        assignment_name = source_path.parent.name
        if output_dir is None:
            output_dir = (
                source_path.parent.parent.parent
                / config.autograded_dir
                / assignment_name
            )
        _moodle_submitted_dir = Path(tempfile.mkdtemp())
        click.echo(
            f"Extracting submissions from Moodle ZIP to {_rel(_moodle_submitted_dir)}"
        )
        extract_result = moodle.extract_submissions(
            moodle_zip_path,
            moodle_csv_path,
            _moodle_submitted_dir,
            match_column=config.moodle_match_column,
        )
        click.echo(
            f"  Extracted {extract_result.extracted} submissions "
            f"({extract_result.skipped} skipped)"
        )
        for w in extract_result.warnings:
            click.echo(f"  {w}")
        files = tuple(sorted(_moodle_submitted_dir.glob("*.py")))
    elif moodle_csv_path or moodle_zip_path:
        click.echo(
            "ERROR: --moodle-csv and --moodle-zip must be used together", err=True
        )
        sys.exit(1)
    else:
        files = assignments

    if files and not _moodle_submitted_dir:
        files = _resolve_assignments(files, config.submitted_dir)

    notebooks = [f for f in files if f.suffix == ".py"]
    if not notebooks:
        click.echo("ERROR: no valid .py files found", err=True)
        sys.exit(1)

    if output_dir is None:
        output_dir = _infer_output_dir(
            notebooks[0],
            config.submitted_dir,
            config.autograded_dir,
            config.autograded_dir,
        )

    # Auto-discover source notebook if not given
    if source_path is None:
        found = _find_source(notebooks[0], source_dir=config.source_dir)
        if not found:
            found = _find_source_for_assignment(
                notebooks[0].parent.name, config.source_dir
            )
        if found:
            source_path = found
            click.echo(f"Auto-discovered source: {_rel(source_path)}")

    # Skip submissions whose autograded output is already up to date.
    # A submission needs re-grading if:
    #   - the autograded .py doesn't exist, OR
    #   - the submitted .py is newer than the autograded .py, OR
    #   - the source notebook is newer than the autograded .py
    if not force and not _moodle_submitted_dir:
        _source_mtime = source_path.stat().st_mtime if source_path else 0
        _to_grade = []
        _skipped = 0
        for nb in notebooks:
            dest = output_dir / nb.name
            _html_dest = dest.with_suffix(".html")
            if dest.is_file():
                _dest_mtime = dest.stat().st_mtime
                _sub_mtime = nb.stat().st_mtime
                _html_ok = _html_dest.is_file() and _html_dest.stat().st_size > 0
                if (
                    _sub_mtime <= _dest_mtime
                    and _source_mtime <= _dest_mtime
                    and _html_ok
                ):
                    _skipped += 1
                    continue
            _to_grade.append(nb)
        if _skipped:
            click.echo(
                f"Skipping {_skipped} up-to-date submission(s) "
                f"(use --force to re-grade all)"
            )
        notebooks = _to_grade
        if not notebooks:
            click.echo("All submissions are up to date — nothing to do.")
            return

    # Optionally run source solution first
    all_labels: list[str] = []
    marks: dict[str, int | float] | None = None
    source_text: str | None = None
    shared_sandbox: Path | None = None
    if progress:
        click.echo(
            json.dumps({"event": "start", "total": len(notebooks)}),
            err=True,
        )
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

        _src_check_cb = None
        if progress:

            def _src_check_cb(cr):
                _st = "PASS" if cr.status == "success" else "FAIL"
                click.echo(
                    json.dumps(
                        {
                            "event": "check",
                            "notebook": source_path.name,
                            "label": cr.label,
                            "status": _st,
                        }
                    ),
                    err=True,
                )

        source_result = runner.run_notebook(
            source_path,
            timeout=timeout,
            sandbox_dir=shared_sandbox,
            on_check=_src_check_cb,
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

    # Resolve release notebook for cell integrity checking
    release_text: str | None = None
    if safety_check and source_path:
        assignment_name = source_path.parent.name
        release_dir = (
            source_path.parent.parent.parent / config.release_dir / assignment_name
        )
        release_candidates = (
            list(release_dir.glob("*.py")) if release_dir.is_dir() else []
        )
        if release_candidates:
            release_text = release_candidates[0].read_text()
            click.echo(
                f"Cell integrity check using release: {_rel(release_candidates[0])}"
            )

    # Integrity check + reinject tampered cells
    run_paths: list[Path] = list(notebooks)
    tamper_info: dict[str, integrity.IntegrityResult] = {}
    cell_tamper_info: dict[str, integrity.CellIntegrityResult] = {}
    fixed_dir: Path | None = None
    if source_text:
        fixed_dir = Path(tempfile.mkdtemp())
        run_paths = []
        for nb in notebooks:
            nb_text = nb.read_text()

            # Cell integrity check: verify non-solution cells match release
            if release_text:
                cir = integrity.check_cell_integrity(release_text, nb_text)
                if cir.tampered_cells:
                    nb_text = cir.fixed_source
                    cell_tamper_info[nb.stem] = cir
                    click.echo(
                        f"  WARNING: {nb.stem} — non-solution cells reinjected: "
                        f"{len(cir.tampered_cells)} cell(s)"
                    )

            ir = integrity.check_integrity(source_text, nb_text)
            if ir.tampered_checks or ir.tampered_marks or nb.stem in cell_tamper_info:
                fixed = fixed_dir / nb.name
                fixed.write_text(ir.fixed_source)
                run_paths.append(fixed)
                tamper_info[nb.stem] = ir
                warns = [f"check({k})" for k in ir.tampered_checks]
                if ir.tampered_marks:
                    warns.append("marks")
                if warns:
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

    output_dir.mkdir(parents=True, exist_ok=True)
    _rlimit_as = (max_memory * 1024 * 1024) if max_memory else config.rlimit_as
    results = runner.run_batch(
        run_paths,
        jobs=jobs,
        timeout=timeout,
        html_dir=output_dir,
        on_progress=progress_cb,
        sandbox_dir=shared_sandbox,
        safety_check=safety_check,
        rlimit_cpu=config.rlimit_cpu,
        rlimit_nproc=config.rlimit_nproc,
        rlimit_nofile=config.rlimit_nofile,
        rlimit_as=_rlimit_as,
        isolate_cwd=True,
        use_bubblewrap=config.use_bubblewrap,
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
        if original.stem in cell_tamper_info:
            cti = cell_tamper_info[original.stem]
            r.tampered.extend(f"cell: {d}" for d in cti.tampered_cells)

    if fixed_dir:
        shutil.rmtree(fixed_dir, ignore_errors=True)

    # Discover labels from results if no source notebook
    if not all_labels:
        all_labels = runner.discover_labels(results)

    # Print summary
    runner.print_summary(results, all_labels, marks)

    # Emit structured results for --progress consumers
    if progress:
        rows = runner.serialize_results(results, all_labels, marks)
        labels = [lb.split(":")[0].strip() for lb in all_labels]
        click.echo(
            json.dumps({"event": "results", "labels": labels, "rows": rows}),
            err=True,
        )

    # Inject grading cells and write to output dir
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

    # Write results to gradebook at course root.
    # output_dir is typically <course>/<autograded>/<assignment>/
    # so course root = grandparent when parent matches autograded_dir.
    if output_dir.parent.name == config.autograded_dir:
        _course_root = output_dir.parent.parent
    else:
        _course_root = output_dir.parent
    db_path = _course_root / config.gradebook
    with Gradebook(db_path) as gb:
        # Auto-import existing grades if this is a fresh DB
        if gb.is_new:
            # Scan for existing autograded dirs
            for d in output_dir.parent.iterdir() if output_dir.parent.is_dir() else []:
                if d.is_dir() and d != output_dir:
                    for sub_d in d.iterdir():
                        if sub_d.is_dir() and any(sub_d.glob("*.py")):
                            gb.upsert_assignment(sub_d.name)
                            imported = gb.import_from_py(sub_d.name, sub_d)
                            if imported:
                                click.echo(
                                    f"  Auto-imported {imported} grades from {_rel(sub_d)}"
                                )

        assignment_name = (
            source_path.parent.name
            if _moodle_submitted_dir and source_path
            else notebooks[0].parent.name
        )
        max_mark = sum(marks.values()) if marks else 100
        gb.upsert_assignment(assignment_name, max_mark=max_mark, marks_metadata=marks)
        for result in results:
            if not result.export_ok:
                continue
            auto_mark = _compute_auto_mark(result.checks, marks)
            gb.save_autograde_result(
                assignment_name,
                result.path.stem,
                result.checks,
                result.cell_errors,
                auto_mark,
                result.tampered,
            )

    # Write CSV if requested
    if csv_path:
        runner.write_csv(results, all_labels, csv_path, marks)

    # Clean up temp Moodle extraction dir
    if _moodle_submitted_dir:
        shutil.rmtree(_moodle_submitted_dir, ignore_errors=True)


@cli.command()
@click.argument("assignments", nargs=-1, required=True, metavar="ASSIGNMENTS...")
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
@click.pass_context
def feedback_cmd(ctx, assignments, output_dir, grades_csv, timeout, jobs):
    """Export graded notebooks to HTML and aggregate grades.

    ASSIGNMENTS can be assignment names (e.g. "hw1") which are auto-expanded
    to autograded/hw1/*.py, or explicit file paths.
    """
    config = ctx.obj["config"]
    files = _resolve_assignments(assignments, config.autograded_dir)
    notebooks = [f for f in files if f.suffix == ".py"]
    if not notebooks:
        click.echo("ERROR: no valid .py files found", err=True)
        sys.exit(1)

    if output_dir is None:
        output_dir = _infer_output_dir(
            notebooks[0],
            config.autograded_dir,
            config.feedback_dir,
            config.feedback_dir,
        )

    # Collect grades — prefer gradebook, fall back to .py parsing
    assignment_name = notebooks[0].parent.name
    db_path = _find_gradebook(notebooks[0], config.gradebook)
    grades_by_student: dict[str, dict] = {}
    if db_path:
        with Gradebook(db_path) as gb:
            grades = gb.collect_grades(assignment_name)
            grades_by_student = {g["student"]: g for g in grades}
            n_graded = gb.count_graded(assignment_name)
        click.echo(f"Reading grades from {_rel(db_path)}")
    else:
        grades = feedback.collect_grades(notebooks)
        grades_by_student = {g["student"]: g for g in grades}
        n_graded = sum(1 for g in grades if g["mark"] is not None)
    click.echo(f"{n_graded}/{len(notebooks)} notebooks have been graded")

    # Export each to HTML
    output_dir_path = (
        Path(output_dir) if not isinstance(output_dir, Path) else output_dir
    )
    for nb in notebooks:
        try:
            # Use pre-loaded grade data from DB if available
            grade_data = grades_by_student.get(nb.stem)
            html_path = feedback.export_feedback_html(
                nb,
                output_dir_path,
                timeout=timeout,
                mark=grade_data.get("mark") if grade_data else None,
                feedback_text=grade_data.get("feedback") if grade_data else None,
                auto_mark=grade_data.get("auto_mark") if grade_data else None,
            )
            click.echo(f"  Exported: {_rel(html_path)}")
        except Exception as e:
            click.echo(f"  FAILED: {_rel(nb)} — {e}", err=True)

    # Write grades CSV if requested
    if grades_csv:
        feedback.write_grades_csv(grades, grades_csv)


# Register the feedback command with its proper name
cli.add_command(feedback_cmd, "feedback")


@cli.group()
@click.pass_context
def moodle_group(ctx):
    """Moodle integration: fetch, submit, export grades, upload feedback."""
    pass


cli.add_command(moodle_group, "moodle")


# --- Common Moodle API options ---

_moodle_api_options = [
    click.option(
        "--course-id",
        "-c",
        type=int,
        default=None,
        help="Moodle course ID (overrides config)",
    ),
    click.option("--url", default=None, help="Moodle URL (overrides config/env)"),
    click.option("--token", default=None, help="Moodle token (overrides env)"),
]


def _add_moodle_api_options(func):
    for option in reversed(_moodle_api_options):
        func = option(func)
    return func


def _get_course_id(cli_course_id, config):
    """Resolve course ID from CLI flag or config."""
    course_id = cli_course_id or getattr(config, "moodle_course_id", None)
    if not course_id:
        raise click.UsageError(
            "Course ID not set. Provide --course-id / -c, "
            "or add course_id to [moodle] in mograder.toml"
        )
    return course_id


def _build_moodle_transport(ctx, course_id, url, token):
    """Build a MoodleTransport from CLI context and Moodle credentials."""
    from mograder.moodle_api import MoodleAPIClient, resolve_credentials
    from mograder.moodle_transport import MoodleTransport

    config = ctx.obj["config"]
    url, token = resolve_credentials(url, token, config)
    cid = _get_course_id(course_id, config)
    client = MoodleAPIClient(url, token)
    return MoodleTransport(client, cid)


@moodle_group.command("export")
@click.argument("assignment")
@click.option(
    "--worksheet",
    type=click.Path(exists=True, path_type=Path),
    default=None,
    help="Moodle offline grading CSV (default: import/<assignment>.csv)",
)
@click.option(
    "--grades-csv",
    required=False,
    type=click.Path(exists=True, path_type=Path),
    default=None,
    help="mograder grades CSV (auto-discovered from gradebook.db if omitted)",
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
@click.pass_context
def moodle_export(
    ctx, assignment, worksheet, grades_csv, feedback_dir, output_dir, match_column
):
    """Merge grades into a Moodle offline grading worksheet."""
    config = ctx.obj["config"]

    # Auto-discover worksheet from import/<assignment>.csv
    if worksheet is None:
        worksheet = Path(config.import_dir) / f"{assignment}.csv"
        if not worksheet.exists():
            raise click.UsageError(
                f"No worksheet found at {worksheet}. "
                f"Provide --worksheet or place the Moodle CSV at {worksheet}"
            )

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

    # Read grades — prefer CSV if given, otherwise try gradebook
    if grades_csv:
        grades = moodle.read_grades_csv(grades_csv)
    else:
        db_path = Path.cwd() / config.gradebook
        if db_path.is_file():
            grades = moodle.grades_from_gradebook(db_path)
            click.echo(f"Reading grades from {_rel(db_path)}")
        else:
            click.echo(
                "ERROR: no --grades-csv provided and no gradebook.db found",
                err=True,
            )
            sys.exit(1)

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
            updated_rows,
            feedback_dir,
            zip_path,
            match_column,
            name_column=config.moodle_name_column,
        )
        click.echo(f"Feedback ZIP: {_rel(zip_path)} ({count} files)")

    # Auto-upsert student names into gradebook
    db_path = Path.cwd() / config.gradebook
    if db_path.is_file():
        _name_col = config.moodle_name_column
        if _name_col in fieldnames and match_column in fieldnames:
            _student_mapping = {
                r[match_column]: r[_name_col]
                for r in moodle_rows
                if r.get(match_column) and r.get(_name_col)
            }
            if _student_mapping:
                with Gradebook(db_path) as _gb:
                    _gb.upsert_students(_student_mapping)

    # Statistics
    if result.marks:
        click.echo("")
        click.echo(moodle.compute_statistics(result.marks))


@moodle_group.command("fetch")
@click.argument("assignment", required=False, default=None)
@click.option(
    "--list", "list_assignments", is_flag=True, help="List available assignments"
)
@_add_moodle_api_options
@click.option(
    "-o",
    "--output-dir",
    type=click.Path(path_type=Path),
    default=".",
    help="Output directory (default: current dir)",
)
@click.pass_context
def moodle_fetch(ctx, assignment, list_assignments, course_id, url, token, output_dir):
    """Download assignment files from Moodle."""
    from mograder.transport_commands import do_fetch

    transport = _build_moodle_transport(ctx, course_id, url, token)
    do_fetch(transport, assignment, Path(output_dir), list_only=list_assignments)


@moodle_group.command("submit")
@click.argument("assignment")
@click.argument("file", type=click.Path(exists=True, path_type=Path))
@_add_moodle_api_options
@click.option(
    "--no-finalize",
    is_flag=True,
    help="Save draft without submitting for grading",
)
@click.option(
    "--dry-run", is_flag=True, help="Show what would happen without uploading"
)
@click.pass_context
def moodle_submit(ctx, assignment, file, course_id, url, token, no_finalize, dry_run):
    """Upload a .py notebook as a Moodle assignment submission."""
    from mograder.moodle_api import (
        MoodleAPIClient,
        find_assignment,
        resolve_credentials,
    )

    config = ctx.obj["config"]

    if file.suffix != ".py":
        click.echo("ERROR: only .py files can be submitted", err=True)
        sys.exit(1)

    url, token = resolve_credentials(url, token, config)
    cid = _get_course_id(course_id, config)
    client = MoodleAPIClient(url, token)

    match = find_assignment(client, cid, assignment)

    if dry_run:
        click.echo(f"Would submit: {_rel(file)}")
        click.echo(f"  Assignment: {match['name']} (id={match['id']})")
        click.echo(f"  Finalize: {'no' if no_finalize else 'yes'}")
        return

    click.echo(f"Uploading {_rel(file)}...")
    item_id = client.upload_file(file)
    click.echo(f"  Uploaded to draft area (itemid={item_id})")

    client.save_submission(match["id"], item_id)
    click.echo(f"  Saved submission for '{match['name']}'")

    if not no_finalize:
        client.submit_for_grading(match["id"])
        click.echo("  Submitted for grading")

    click.echo("Done.")


@moodle_group.command("fetch-submissions")
@click.argument("assignment")
@_add_moodle_api_options
@click.option(
    "-o",
    "--output-dir",
    type=click.Path(path_type=Path),
    default=None,
    help="Output directory (default: submitted/<assignment>/)",
)
@click.option("--force", is_flag=True, help="Re-download even if file exists")
@click.pass_context
def moodle_fetch_submissions(ctx, assignment, course_id, url, token, output_dir, force):
    """Bulk download all student submissions for an assignment (instructor)."""
    from mograder.transport_commands import do_fetch_submissions

    config = ctx.obj["config"]
    transport = _build_moodle_transport(ctx, course_id, url, token)

    if output_dir is None:
        output_dir = Path(config.submitted_dir) / assignment
    do_fetch_submissions(transport, assignment, Path(output_dir), force=force)


@moodle_group.command("upload-feedback")
@click.argument("assignment")
@_add_moodle_api_options
@click.option(
    "--feedback-dir",
    type=click.Path(exists=True, path_type=Path),
    default=None,
    help="Directory with {student}.html feedback files",
)
@click.option(
    "--grades-csv",
    type=click.Path(exists=True, path_type=Path),
    default=None,
    help="Grades CSV (auto-discovered from gradebook.db if omitted)",
)
@click.option("--dry-run", is_flag=True, help="Show what would be uploaded")
@click.option(
    "--workflow-state",
    default="readyforrelease",
    help="Marking workflow state (default: readyforrelease). Use 'released' to make visible immediately.",
)
@click.pass_context
def moodle_upload_feedback(
    ctx,
    assignment,
    course_id,
    url,
    token,
    feedback_dir,
    grades_csv,
    dry_run,
    workflow_state,
):
    """Upload grades and feedback to Moodle via API (instructor)."""
    from mograder.moodle_api import (
        MoodleAPIClient,
        find_assignment,
        resolve_credentials,
    )

    config = ctx.obj["config"]
    url, token = resolve_credentials(url, token, config)
    cid = _get_course_id(course_id, config)
    client = MoodleAPIClient(url, token)

    match = find_assignment(client, cid, assignment)
    assignment_id = match["id"]

    # Read grades
    if grades_csv:
        grades = moodle.read_grades_csv(grades_csv)
    else:
        db_path = Path.cwd() / config.gradebook
        if db_path.is_file():
            grades = moodle.grades_from_gradebook(db_path)
            click.echo(f"Reading grades from {_rel(db_path)}")
        else:
            click.echo(
                "ERROR: no --grades-csv provided and no gradebook.db found",
                err=True,
            )
            sys.exit(1)

    # Auto-discover feedback directory if not provided
    if feedback_dir is None:
        # Try feedback/<assignment>/ matching the assignment name pattern
        for a in config.assignments:
            if a["name"] == match["name"]:
                candidate = Path.cwd() / config.feedback_dir / assignment
                if candidate.is_dir() and any(candidate.glob("*.html")):
                    feedback_dir = candidate
                    click.echo(f"Using feedback from {_rel(feedback_dir)}")
                break
        if feedback_dir is None:
            candidate = Path.cwd() / config.feedback_dir / assignment
            if candidate.is_dir() and any(candidate.glob("*.html")):
                feedback_dir = candidate
                click.echo(f"Using feedback from {_rel(feedback_dir)}")

    # Map usernames → Moodle user IDs
    participants = client.list_participants(assignment_id)
    username_to_uid = {p["username"]: p["id"] for p in participants}

    # Build grade payloads
    grade_payloads = []
    for username, gdata in grades.items():
        uid = username_to_uid.get(username)
        if uid is None:
            click.echo(f"  WARNING: no Moodle user for '{username}', skipping")
            continue
        mark = gdata.get("mark")
        if mark is None:
            continue
        fb_text = moodle.markdown_to_plaintext(gdata.get("feedback", ""))
        fb_file = None

        # Attach HTML feedback file if available
        if feedback_dir:
            html_file = Path(feedback_dir) / f"{username}.html"
            if html_file.is_file():
                fb_file = str(html_file)

        grade_payloads.append(
            {
                "userid": uid,
                "grade": mark,
                "feedback": fb_text,
                "feedback_file": fb_file,
            }
        )

    if dry_run:
        click.echo(
            f"Would upload {len(grade_payloads)} grade(s) "
            f"to '{match['name']}' (id={assignment_id})"
        )
        click.echo(f"{'Username':<20} {'Grade':>6}")
        click.echo("-" * 28)
        for gp in grade_payloads:
            uname = next(
                (u for u, uid in username_to_uid.items() if uid == gp["userid"]),
                str(gp["userid"]),
            )
            click.echo(f"{uname:<20} {gp['grade']:>6}")
        return

    if not grade_payloads:
        click.echo("No grades to upload")
        return

    client.save_grades(assignment_id, grade_payloads, workflow_state=workflow_state)
    click.echo(f"Uploaded {len(grade_payloads)} grade(s) to '{match['name']}'")


@moodle_group.command("upload")
@click.argument("assignment")
@click.argument("files", nargs=-1, type=click.Path(exists=True, path_type=Path))
@_add_moodle_api_options
@click.option("--dry-run", is_flag=True, help="Show what would be uploaded")
@click.option("--open/--no-open", default=True, help="Open Moodle edit page in browser")
@click.pass_context
def moodle_upload(ctx, assignment, files, course_id, url, token, dry_run, open):
    """Prepare release files for upload to a Moodle assignment.

    Files are zipped into <assignment>.zip and the Moodle assignment
    edit page is opened for manual attachment.
    If no FILES are given, auto-discovers from release/<assignment>/.
    """
    import webbrowser
    import zipfile

    from mograder.moodle_api import (
        MoodleAPIClient,
        find_assignment,
        resolve_credentials,
    )

    config = ctx.obj["config"]
    url, token = resolve_credentials(url, token, config)
    cid = _get_course_id(course_id, config)
    client = MoodleAPIClient(url, token)

    match = find_assignment(client, cid, assignment)

    # Auto-discover release files if none given
    if not files:
        release_dir = Path(config.release_dir) / assignment
        if not release_dir.is_dir():
            raise click.UsageError(
                f"No files specified and release directory not found: {release_dir}"
            )
        files = sorted(f for f in release_dir.iterdir() if f.is_file())
        if not files:
            raise click.UsageError(f"No files found in {release_dir}")

    # Build zip in current directory
    zip_name = f"{assignment}.zip"
    zip_path = Path(zip_name)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in files:
            zf.write(f, Path(f).name)

    if dry_run:
        click.echo(
            f"Would create {zip_name} for '{match['name']}' (cmid={match['cmid']}):"
        )
        for f in files:
            click.echo(f"  {_rel(f)}")
        zip_path.unlink()
        return

    click.echo(f"Created {zip_name} ({len(files)} file(s)):")
    for f in files:
        click.echo(f"  {_rel(f)}")

    # Build edit URL and open in browser
    cmid = match.get("cmid")
    if cmid:
        edit_url = f"{url}/course/modedit.php?update={cmid}"
        click.echo(f"\nUpload {zip_name} to the 'Additional files' section:")
        click.echo(f"  {edit_url}")
        if open:
            webbrowser.open(edit_url)
    else:
        click.echo(
            "\nNo cmid found — open the assignment edit page manually "
            f"and upload {zip_name} to 'Additional files'.",
            err=True,
        )


@moodle_group.command("feedback")
@click.argument("assignment")
@_add_moodle_api_options
@click.pass_context
def moodle_feedback(ctx, assignment, course_id, url, token):
    """Check submission status and view grade/feedback for an assignment."""
    from mograder.moodle_api import (
        MoodleAPIClient,
        find_assignment,
        resolve_credentials,
    )

    config = ctx.obj["config"]
    url, token = resolve_credentials(url, token, config)
    cid = _get_course_id(course_id, config)
    client = MoodleAPIClient(url, token)

    match = find_assignment(client, cid, assignment)
    click.echo(f"Assignment: {match['name']} (id={match['id']})")

    status = client.get_submission_status(match["id"])
    click.echo(f"Status: {status['status']}")

    if status["graded"]:
        click.echo(f"Grade: {status['grade']}")
        if status["feedback"]:
            click.echo(f"Feedback:\n  {status['feedback']}")
    elif status["status"] == "new":
        click.echo("No submission yet.")
    else:
        click.echo("Not yet graded.")


@moodle_group.command("sync")
@_add_moodle_api_options
@click.option(
    "--include",
    "-i",
    "include_pattern",
    default=None,
    help="Only include assignments matching this regex (e.g. '^A[1-8]').",
)
@click.option(
    "--edit-links",
    is_flag=True,
    default=False,
    help="Push edit links (molab, codespaces) into Moodle assignment descriptions.",
)
@click.pass_context
def moodle_sync(ctx, course_id, url, token, include_pattern, edit_links):
    """Sync assignment metadata from Moodle into mograder.toml.

    Fetches assignment names, IDs, due dates, and file info from the Moodle API
    and writes them to the [moodle] section of mograder.toml. This metadata is
    used by the student dashboard to show assignments and open Moodle pages
    without requiring students to have API tokens.

    Run this as an instructor whenever assignments change, then commit the
    updated mograder.toml so students get the latest info.
    """
    import tomllib

    from mograder.moodle_api import (
        MoodleAPIClient,
        resolve_credentials,
        sync_assignments,
    )

    config = ctx.obj["config"]
    url, token = resolve_credentials(url, token, config)
    cid = _get_course_id(course_id, config)
    client = MoodleAPIClient(url, token)

    toml_assignments = sync_assignments(client, cid, include_pattern=include_pattern)

    # Count skipped/filtered for reporting
    all_assignments = client.get_assignments(cid)
    skipped = len(all_assignments) - len(toml_assignments)
    filtered = 0
    if include_pattern:
        import re

        include_re = re.compile(include_pattern)
        filtered = sum(1 for a in all_assignments if not include_re.search(a["name"]))
        skipped -= filtered

    # Update mograder.toml — preserve existing content, replace assignments
    toml_path = Path.cwd() / "mograder.toml"
    if toml_path.is_file():
        with open(toml_path, "rb") as f:
            toml_data = tomllib.load(f)
    else:
        toml_data = {}

    moodle_section = toml_data.get("moodle", {})
    moodle_section["assignments"] = toml_assignments

    # Ensure url and course_id are set
    if "url" not in moodle_section and url:
        moodle_section["url"] = url
    if "course_id" not in moodle_section and cid:
        moodle_section["course_id"] = cid

    toml_data["moodle"] = moodle_section

    # Also write top-level [[assignments]] for transport-agnostic access
    toml_data["assignments"] = toml_assignments

    # Write back — tomllib is read-only, so we use a simple writer
    from mograder.config import write_toml

    write_toml(toml_path, toml_data)

    click.echo(
        f"Synced {len(toml_assignments)} visible assignment(s) to {_rel(toml_path)}"
    )
    if skipped:
        click.echo(f"  ({skipped} hidden assignment(s) excluded)")
    if filtered:
        click.echo(f"  ({filtered} assignment(s) excluded by --include filter)")
    for a in toml_assignments:
        n_files = len(a["files"])
        click.echo(f"  {a['name']} ({n_files} file(s))")

    # --edit-links: push edit links into Moodle assignment descriptions
    if edit_links and config.edit_links:
        from mograder.edit_links import build_edit_link_html, inject_edit_links
        from mograder.moodle_api import MoodleAPIError

        # Build a map from cmid → existing intro from the API response
        intro_map = {a["cmid"]: a.get("intro", "") for a in all_assignments}
        release_dir = Path.cwd() / config.release_dir

        pushed = 0
        manual_entries: list[tuple[str, str, str]] = []  # (name, edit_url, html)
        for entry in toml_assignments:
            dir_key = entry.get("dir", "")
            cmid = entry.get("cmid")
            if not dir_key or not cmid:
                continue
            release_path = release_dir / dir_key
            links_html = build_edit_link_html(release_path, dir_key, config.edit_links)
            if not links_html:
                continue
            existing_intro = intro_map.get(cmid, "")
            new_intro = inject_edit_links(existing_intro, links_html)
            try:
                client.update_intro(cmid, new_intro)
                pushed += 1
                click.echo(f"  Updated edit links for {entry['name']}")
            except MoodleAPIError:
                edit_url = f"{url}/course/modedit.php?update={cmid}"
                manual_entries.append((entry["name"], edit_url, links_html))

        if pushed:
            click.echo(f"Pushed edit links for {pushed} assignment(s)")
        if manual_entries:
            html_path = Path.cwd() / "edit-links.html"
            _write_edit_links_html(html_path, manual_entries, url)
            click.echo(
                f"\nWrote {len(manual_entries)} edit link(s) to {_rel(html_path)}"
                " (core_course_edit_module not in web service).\n"
                "Open the file, copy each HTML snippet, and paste into "
                "the Moodle assignment description."
            )


def _write_edit_links_html(
    path: Path,
    entries: list[tuple[str, str, str]],
    moodle_url: str,
) -> None:
    """Write an HTML file with edit links and copy-paste instructions."""
    parts = [
        "<!DOCTYPE html>",
        "<html><head><meta charset='utf-8'>",
        "<title>Mograder Edit Links</title>",
        "<style>",
        "body { font-family: system-ui, sans-serif; max-width: 900px; "
        "margin: 2em auto; padding: 0 1em; }",
        "h2 { margin-top: 2em; }",
        ".edit-link { margin-bottom: 0.5em; }",
        ".snippet { background: #f5f5f5; border: 1px solid #ddd; "
        "padding: 1em; border-radius: 4px; overflow-x: auto; "
        "font-family: monospace; font-size: 0.85em; white-space: pre-wrap; "
        "word-break: break-all; }",
        "a { color: #1a73e8; }",
        "</style></head><body>",
        "<h1>Edit Links for Moodle</h1>",
        "<p>For each assignment below:</p><ol>",
        "<li>Click the <b>Edit assignment</b> link to open Moodle</li>",
        "<li>In the Description field, switch to HTML source (&lt;/&gt; button)</li>",
        "<li>Paste the HTML snippet at the end</li>",
        "<li>Save</li></ol>",
    ]
    for name, edit_url, links_html in entries:
        parts.append(f"<h2>{name}</h2>")
        parts.append(
            f'<p class="edit-link"><a href="{edit_url}" '
            f'target="_blank">Edit assignment in Moodle</a></p>'
        )
        parts.append("<p><b>HTML to paste into Description:</b></p>")
        import html as html_mod

        parts.append(f'<div class="snippet">{html_mod.escape(links_html)}</div>')
        parts.append("<p><b>Preview:</b></p>")
        parts.append(f"<div>{links_html}</div>")
    parts.append("</body></html>")
    path.write_text("\n".join(parts))


@moodle_group.command("login")
@click.option("--url", default=None, help="Moodle URL (overrides config/env)")
@click.option(
    "--sso",
    is_flag=True,
    default=False,
    help="Use browser-based SSO login (for sites with CAS/SAML/OAuth)",
)
@click.pass_context
def moodle_login(ctx, url, sso):
    """Obtain and cache a Moodle API token.

    For sites with SSO (CAS, SAML, Shibboleth), use --sso to open a browser
    login flow. Otherwise, uses username/password via /login/token.php.
    """
    import webbrowser

    from mograder.moodle_api import (
        MoodleAPIClient,
        MoodleAPIError,
        request_token,
        save_cached_token,
    )

    config = ctx.obj["config"]
    url = (
        url
        or os.environ.get("MOGRADER_MOODLE_URL")
        or getattr(config, "moodle_url", None)
    )
    if not url:
        raise click.UsageError(
            "Moodle URL not set. Provide --url, set MOGRADER_MOODLE_URL, "
            "or add url to [moodle] in mograder.toml"
        )

    if sso:
        token_page = f"{url.rstrip('/')}/user/managetoken.php"
        click.echo("Opening your Moodle Security keys page...")
        click.echo(f"  URL: {token_page}")
        click.echo()
        click.echo("In your browser:")
        click.echo("  1. Log in if prompted")
        click.echo('  2. Find the row for "Moodle mobile web service"')
        click.echo("  3. Copy the token value (32-character string)")
        click.echo()
        webbrowser.open(token_page)
        token = click.prompt("Paste your token").strip()
        if not token:
            click.echo("ERROR: no token provided", err=True)
            sys.exit(1)
    else:
        username = click.prompt("Username")
        password = click.prompt("Password", hide_input=True)
        try:
            token = request_token(url, username, password)
        except MoodleAPIError as e:
            click.echo(f"Login failed: {e}", err=True)
            sys.exit(1)

    # Verify token works
    try:
        client = MoodleAPIClient(url, token)
        info = client.get_site_info()
    except MoodleAPIError as e:
        click.echo(f"Token verification failed: {e}", err=True)
        sys.exit(1)

    save_cached_token(url, token, info["fullname"])
    click.echo(f"Logged in as {info['fullname']} ({info['username']})")
    click.echo("Token cached to ~/.config/mograder/token.json")


@cli.command("import-students")
@click.argument("worksheet", type=click.Path(exists=True, path_type=Path))
@click.option(
    "--match-column",
    default=None,
    help="Moodle CSV column to match student against (default: from config)",
)
@click.pass_context
def import_students(ctx, worksheet, match_column):
    """Import student names from a Moodle CSV into the gradebook."""
    config = ctx.obj["config"]
    match_col = match_column or config.moodle_match_column
    name_col = config.moodle_name_column

    fieldnames, rows = moodle.read_moodle_worksheet(worksheet)
    if match_col not in fieldnames:
        click.echo(
            f"ERROR: match column '{match_col}' not found in worksheet "
            f"(available: {', '.join(fieldnames)})",
            err=True,
        )
        sys.exit(1)
    if name_col not in fieldnames:
        click.echo(
            f"ERROR: name column '{name_col}' not found in worksheet "
            f"(available: {', '.join(fieldnames)})",
            err=True,
        )
        sys.exit(1)

    mapping = {
        r[match_col]: r[name_col]
        for r in rows
        if match_col in r and name_col in r and r[match_col] and r[name_col]
    }

    db_path = Path.cwd() / config.gradebook
    with Gradebook(db_path) as gb:
        gb.upsert_students(mapping)
    click.echo(f"Imported {len(mapping)} students into {_rel(db_path)}")


@cli.command()
@click.argument(
    "autograded_dir",
    type=click.Path(exists=True, path_type=Path),
)
@click.option(
    "--remote",
    default=None,
    help="SSH host alias (default: from mograder.toml [sync] remote)",
)
@click.option(
    "--course-dir",
    "remote_course_dir",
    default=None,
    help="Course directory on remote (default: from mograder.toml [sync] remote_course_dir)",
)
@click.option(
    "--venv-dir",
    "remote_venv_dir",
    default=None,
    help="Directory with uv venv on remote (default: from mograder.toml [sync] remote_venv_dir)",
)
@click.pass_context
def sync(ctx, autograded_dir, remote, remote_course_dir, remote_venv_dir):
    """Sync autograded results to a remote server via rsync + SSH."""
    import subprocess as sp

    config = ctx.obj["config"]
    remote = remote or config.sync_remote
    remote_course_dir = remote_course_dir or config.sync_remote_course_dir
    remote_venv_dir = remote_venv_dir or config.sync_remote_venv_dir

    if not remote:
        click.echo(
            "ERROR: --remote is required (or set [sync] remote in mograder.toml)",
            err=True,
        )
        sys.exit(1)
    if not remote_course_dir:
        click.echo(
            "ERROR: --course-dir is required "
            "(or set [sync] remote_course_dir in mograder.toml)",
            err=True,
        )
        sys.exit(1)

    # Infer assignment name from directory
    assignment = autograded_dir.name

    # 1. rsync autograded files to remote
    remote_path = f"{remote}:{remote_course_dir}/{config.autograded_dir}/{assignment}/"
    local_path = str(autograded_dir) + "/"
    click.echo(f"Syncing {_rel(autograded_dir)} → {remote_path}")

    rsync_cmd = [
        "rsync",
        "-avz",
        "--include=*.py",
        "--include=*.html",
        "--exclude=*",
        local_path,
        remote_path,
    ]
    result = sp.run(rsync_cmd)
    if result.returncode != 0:
        click.echo("ERROR: rsync failed", err=True)
        sys.exit(1)
    click.echo("  rsync complete")

    # 2. Run gradebook import on remote via SSH
    python_cmd = "uv run python" if remote_venv_dir else "python"
    cd_venv = f"cd {remote_venv_dir} && " if remote_venv_dir else ""
    import_script = (
        f"{cd_venv}"
        f'{python_cmd} -c "'
        f"import sys; sys.path.insert(0, '.'); "
        f"from mograder.gradebook import Gradebook; "
        f"gb = Gradebook('{remote_course_dir}/{config.gradebook}'); "
        f"gb.upsert_assignment('{assignment}'); "
        f"n = gb.import_from_py('{assignment}', "
        f"'{remote_course_dir}/{config.autograded_dir}/{assignment}'); "
        f"gb.close(); "
        f"print(f'Imported {{n}} grades into gradebook')"
        f'"'
    )
    click.echo(f"Importing grades on {remote}...")
    ssh_result = sp.run(["ssh", remote, import_script])
    if ssh_result.returncode != 0:
        click.echo(
            "WARNING: remote gradebook import failed — grades may need manual import",
            err=True,
        )
    else:
        click.echo("  Remote import complete")


@cli.command()
@click.argument(
    "course_dir",
    type=click.Path(exists=True, path_type=Path),
    default=".",
)
@click.option("-p", "--port", type=int, default=None, help="Port for marimo app")
@click.option("--headless", is_flag=True, help="Don't open browser")
@click.option("--base-url", default=None, help="Base URL path for reverse proxy")
def formgrader(course_dir, port, headless, base_url):
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
    if base_url:
        cmd.extend(["--base-url", base_url])

    click.echo(f"Launching formgrader for: {course_dir.resolve()}")
    try:
        proc = sp.run(cmd)
        sys.exit(proc.returncode)
    except KeyboardInterrupt:
        pass


@cli.command("formgrader-asgi")
@click.argument(
    "course_dir",
    type=click.Path(exists=True, path_type=Path),
    default=".",
)
@click.option("-p", "--port", type=int, default=2718, help="Port for uvicorn")
@click.option("--host", default="0.0.0.0", help="Bind address")
@click.option("--base-url", default="/", help="Base URL path for reverse proxy")
@click.option(
    "--instructors",
    default="",
    help="Comma-separated instructor user IDs",
)
@click.option(
    "--trusted-proxies",
    default="",
    help="Comma-separated trusted proxy IPs",
)
@click.option(
    "--reload",
    is_flag=True,
    help="Auto-reload on source changes (for development)",
)
def formgrader_asgi(
    course_dir, port, host, base_url, instructors, trusted_proxies, reload
):
    """Launch the formgrader as a persistent ASGI service.

    Uses uvicorn with trusted-proxy authentication middleware.
    Intended for deployment behind a reverse proxy (e.g. on sciml).
    """
    import os
    import subprocess as sp

    os.environ["MOGRADER_COURSE_DIR"] = str(course_dir.resolve())
    os.environ["MOGRADER_BASE_URL"] = base_url
    if instructors:
        os.environ["MOGRADER_INSTRUCTORS"] = instructors
    if trusted_proxies:
        os.environ["MOGRADER_TRUSTED_PROXIES"] = trusted_proxies

    cmd = [
        sys.executable,
        "-m",
        "uvicorn",
        "mograder.formgrader_asgi:app",
        "--host",
        host,
        "--port",
        str(port),
    ]
    if reload:
        src_dir = str(Path(__file__).parent)
        cmd.extend(["--reload", "--reload-dir", src_dir])

    click.echo(f"Launching ASGI formgrader for: {course_dir.resolve()}")
    click.echo(f"  base-url: {base_url}")
    click.echo(f"  bind: {host}:{port}")
    if trusted_proxies:
        click.echo(f"  trusted-proxies: {trusted_proxies}")
    if reload:
        click.echo(f"  reload: watching {src_dir}")
    try:
        proc = sp.run(cmd)
        sys.exit(proc.returncode)
    except KeyboardInterrupt:
        pass


def _refresh_config(course: Path):
    """Fetch latest mograder.toml from config_url if set."""
    import tomllib

    import requests

    config_path = course / "mograder.toml"
    if not config_path.is_file():
        return
    with open(config_path, "rb") as f:
        data = tomllib.load(f)
    url = data.get("config_url")
    if not url:
        return
    click.echo("Updating assignments...")
    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        config_path.write_text(resp.text)
        click.echo("  Done.")
    except Exception as e:
        click.echo(f"  Warning: could not fetch config ({e})")
        click.echo("  Continuing with cached config...")


@cli.command()
@click.argument("course_dir_or_url", default=".")
@click.option("-p", "--port", type=int, default=None, help="Port for marimo app")
@click.option("--headless", is_flag=True, help="Don't open browser")
@click.option("--no-token", is_flag=True, help="Disable marimo auth token")
def student(course_dir_or_url, port, headless, no_token):
    """Launch the student course browser for fetching and submitting assignments.

    COURSE_DIR_OR_URL can be a local directory (default: .) or an HTTPS URL
    to a mograder.toml config file for first-time setup.
    """
    import subprocess as sp
    from urllib.parse import urlparse

    import requests

    if course_dir_or_url.startswith("http"):
        url = course_dir_or_url
        click.echo(f"Fetching course config from {url}...")
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        # Derive directory name from URL path
        parts = urlparse(url).path.strip("/").split("/")
        # For raw.githubusercontent.com/<user>/<repo>/branch/file, repo is parts[1]
        # For other URLs, use parent dir name, falling back to filename stem
        if len(parts) > 2:
            dir_name = parts[1]
        elif len(parts) > 1:
            dir_name = parts[-2]
        else:
            dir_name = Path(parts[0]).stem
        course = Path(dir_name).resolve()
        course.mkdir(exist_ok=True)
        (course / "mograder.toml").write_text(resp.text)
        click.echo(f"  Created {course}/mograder.toml")
    else:
        course = Path(course_dir_or_url).resolve()
        if not course.is_dir():
            click.echo(f"Error: {course} is not a directory", err=True)
            sys.exit(1)
        _refresh_config(course)

    app_path = Path(__file__).parent / "student_app.py"
    os.environ["MOGRADER_COURSE_DIR"] = str(course)

    cmd = [sys.executable, "-m", "marimo", "run", str(app_path)]
    if port:
        cmd.extend(["--port", str(port)])
    if headless:
        cmd.append("--headless")
    if no_token:
        cmd.append("--no-token")

    click.echo(f"Launching student dashboard for: {course}")
    try:
        proc = sp.run(cmd)
        sys.exit(proc.returncode)
    except KeyboardInterrupt:
        pass


# ---------------------------------------------------------------------------
# HTTPS transport group
# ---------------------------------------------------------------------------


@cli.group()
@click.pass_context
def https_group(ctx):
    """HTTPS server transport: fetch, submit, upload grades."""
    pass


cli.add_command(https_group, "https")


def _resolve_https_token(config, token_opt: str | None) -> str:
    """Resolve HTTPS token: CLI flag > env var > cache > config > empty."""
    if token_opt:
        return token_opt
    env_tok = os.environ.get("MOGRADER_HTTPS_TOKEN", "")
    if env_tok:
        return env_tok
    from mograder.auth import load_cached_https_token

    url = config.https_url or ""
    if url:
        cached = load_cached_https_token(url)
        if cached:
            return cached["token"]
    return config.https_token or ""


def _user_from_token(token: str) -> str:
    """Extract username from a token string."""
    if ":" in token:
        return token.split(":", 1)[0]
    return ""


@https_group.command("login")
@click.option("--token", required=True, help="HTTPS auth token")
@click.option("--url", default=None, help="Server URL (overrides config)")
@click.pass_context
def https_login(ctx, token, url):
    """Cache an HTTPS authentication token."""
    from mograder.auth import save_cached_https_token

    config = ctx.obj["config"]
    url = url or config.https_url
    if not url:
        raise click.UsageError(
            "No HTTPS URL configured. Provide --url or set [https] url in mograder.toml"
        )
    user = _user_from_token(token)
    save_cached_https_token(url, token, user)
    click.echo(f"Token cached for {url} (user: {user})")


@https_group.command("fetch")
@click.argument("assignment", required=False, default=None)
@click.option(
    "--list", "list_assignments", is_flag=True, help="List available assignments"
)
@click.option("--url", default=None, help="Server URL (overrides config)")
@click.option("--token", default=None, help="Auth token (overrides cached token)")
@click.option(
    "-o",
    "--output-dir",
    type=click.Path(path_type=Path),
    default=".",
    help="Output directory (default: current dir)",
)
@click.pass_context
def https_fetch(ctx, assignment, list_assignments, url, token, output_dir):
    """Download assignment files from an HTTPS server."""
    from mograder.https_transport import HTTPSTransport
    from mograder.transport_commands import do_fetch

    config = ctx.obj["config"]
    url = url or config.https_url
    if not url:
        raise click.UsageError(
            "No HTTPS URL configured. Provide --url or set [https] url in mograder.toml"
        )
    token = _resolve_https_token(config, token)
    transport = HTTPSTransport(url, token=token)
    do_fetch(transport, assignment, Path(output_dir), list_only=list_assignments)


@https_group.command("submit")
@click.argument("assignment")
@click.argument("file", type=click.Path(exists=True, path_type=Path))
@click.option("--url", default=None, help="Server URL (overrides config)")
@click.option("--token", default=None, help="Auth token (overrides cached token)")
@click.option("--dry-run", is_flag=True, help="Show what would happen")
@click.pass_context
def https_submit(ctx, assignment, file, url, token, dry_run):
    """Submit a .py notebook to an HTTPS assignment server."""
    from mograder.https_transport import HTTPSTransport
    from mograder.transport_commands import do_submit

    config = ctx.obj["config"]
    url = url or config.https_url
    if not url:
        raise click.UsageError(
            "No HTTPS URL configured. Provide --url or set [https] url in mograder.toml"
        )
    token = _resolve_https_token(config, token)
    user = _user_from_token(token)
    if not user:
        raise click.UsageError("Cannot determine username from token. Provide --token.")
    transport = HTTPSTransport(url, user=user, token=token)
    do_submit(transport, file, assignment, dry_run=dry_run)


@https_group.command("fetch-submissions")
@click.argument("assignment")
@click.option("--url", default=None, help="Server URL (overrides config)")
@click.option("--token", default=None, help="Instructor auth token")
@click.option(
    "-o",
    "--output-dir",
    type=click.Path(path_type=Path),
    default=None,
    help="Output directory",
)
@click.option("--force", is_flag=True, help="Re-download even if file exists")
@click.pass_context
def https_fetch_submissions(ctx, assignment, url, token, output_dir, force):
    """Download all submissions from an HTTPS server (instructor)."""
    from mograder.https_transport import HTTPSTransport
    from mograder.transport_commands import do_fetch_submissions

    config = ctx.obj["config"]
    url = url or config.https_url
    if not url:
        raise click.UsageError(
            "No HTTPS URL configured. Provide --url or set [https] url in mograder.toml"
        )
    token = _resolve_https_token(config, token)
    transport = HTTPSTransport(url, token=token)
    if output_dir is None:
        output_dir = Path(config.submitted_dir) / assignment
    do_fetch_submissions(transport, assignment, Path(output_dir), force=force)


@https_group.command("upload-grades")
@click.argument("assignment")
@click.option("--url", default=None, help="Server URL (overrides config)")
@click.option("--token", default=None, help="Instructor auth token")
@click.option(
    "--grades-csv",
    type=click.Path(exists=True, path_type=Path),
    required=True,
    help="Grades CSV file",
)
@click.option("--dry-run", is_flag=True, help="Show what would happen")
@click.pass_context
def https_upload_grades(ctx, assignment, url, token, grades_csv, dry_run):
    """Upload grades to an HTTPS assignment server."""
    import csv

    from mograder.https_transport import HTTPSTransport
    from mograder.transport_commands import do_upload_feedback

    config = ctx.obj["config"]
    url = url or config.https_url
    if not url:
        raise click.UsageError(
            "No HTTPS URL configured. Provide --url or set [https] url in mograder.toml"
        )
    token = _resolve_https_token(config, token)
    transport = HTTPSTransport(url, token=token)

    # Read grades from CSV
    with open(grades_csv) as f:
        reader = csv.DictReader(f)
        grades = [dict(row) for row in reader]
    do_upload_feedback(transport, assignment, grades, dry_run=dry_run)


@https_group.command("feedback")
@click.argument("assignment")
@click.option("--url", default=None, help="Server URL (overrides config)")
@click.option("--token", default=None, help="Auth token (overrides cached token)")
@click.pass_context
def https_feedback(ctx, assignment, url, token):
    """Check submission status and view grade/feedback."""
    from mograder.https_transport import HTTPSTransport
    from mograder.transport_commands import do_status

    config = ctx.obj["config"]
    url = url or config.https_url
    if not url:
        raise click.UsageError(
            "No HTTPS URL configured. Provide --url or set [https] url in mograder.toml"
        )
    token = _resolve_https_token(config, token)
    user = _user_from_token(token)
    transport = HTTPSTransport(url, user=user, token=token)
    do_status(transport, assignment)


# ---------------------------------------------------------------------------
# Serve command
# ---------------------------------------------------------------------------


@cli.command()
@click.argument(
    "directory",
    type=click.Path(exists=True, path_type=Path),
    default=".",
)
@click.option(
    "-p",
    "--port",
    type=int,
    default=None,
    help="Port to listen on (default: $PORT or 8080)",
)
@click.option(
    "--host",
    default=None,
    help="Host to bind to (default: 0.0.0.0 if $PORT set, else 127.0.0.1)",
)
@click.option(
    "--no-auth",
    is_flag=True,
    help="Disable authentication (for local testing)",
)
@click.option(
    "--generate-tokens",
    type=click.Path(path_type=Path),
    default=None,
    help="Read usernames from FILE, print tokens, then exit",
)
@click.option(
    "--enrollment-code",
    envvar="MOGRADER_ENROLLMENT_CODE",
    default=None,
    help="Enrollment passphrase for student self-registration",
)
@click.option(
    "--enrollment-code-file",
    type=click.Path(exists=True, path_type=Path),
    default=None,
    help="Read enrollment code from FILE",
)
@click.option(
    "--release-dir",
    type=click.Path(exists=True, path_type=Path),
    default=None,
    help="Serve files from RELEASE_DIR/<assignment>/<file> (flat layout, no files/ subdir)",
)
def serve(
    directory,
    port,
    host,
    no_auth,
    generate_tokens,
    enrollment_code,
    enrollment_code_file,
    release_dir,
):
    """Start a lightweight assignment server.

    Serves assignments from DIRECTORY (default: current dir).
    """
    from mograder.auth import INSTRUCTOR_USER, load_or_create_secret, make_token
    from mograder.https_server import create_server

    secret = None
    if not no_auth:
        secret = load_or_create_secret(directory)

    if generate_tokens is not None:
        if secret is None:
            secret = load_or_create_secret(directory)
        usernames = [
            line.strip()
            for line in generate_tokens.read_text().splitlines()
            if line.strip()
        ]
        for username in usernames:
            click.echo(f"{username}: {make_token(secret, username)}")
        click.echo(f"\ninstructor: {make_token(secret, INSTRUCTOR_USER)}")
        return

    # Resolve enrollment code: explicit flag > file > env var (via Click envvar)
    if enrollment_code_file is not None:
        if enrollment_code is not None:
            raise click.UsageError(
                "Cannot use both --enrollment-code and --enrollment-code-file."
            )
        enrollment_code = enrollment_code_file.read_text().strip()

    env_port = os.environ.get("PORT")
    if port is None:
        port = int(env_port) if env_port else 8080
    if host is None:
        host = "0.0.0.0" if env_port else "127.0.0.1"

    # Auto-detect release_dir if not specified
    if release_dir is None and (directory / "release").is_dir():
        release_dir = directory / "release"

    server = create_server(
        directory,
        host=host,
        port=port,
        release_dir=release_dir,
        secret=secret,
        enrollment_code=enrollment_code,
    )
    actual_port = server.server_address[1]
    click.echo(f"Serving assignments from {directory.resolve()}")
    click.echo(f"  URL: http://{host}:{actual_port}")
    if secret:
        click.echo("  Authentication: enabled")
    else:
        click.echo("  Authentication: disabled (--no-auth)")
    if enrollment_code:
        click.echo("  Registration: enabled")
    click.echo("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        click.echo("\nShutting down.")
        server.shutdown()


@cli.command()
@click.argument("usernames", nargs=-1, required=True)
@click.option(
    "--secret-file",
    type=click.Path(exists=True, path_type=Path),
    help="Read secret from FILE",
)
@click.option("--secret-stdin", is_flag=True, help="Read secret from stdin")
@click.option(
    "--secret", "secret_value", help="Secret string (visible in process list)"
)
def token(usernames, secret_file, secret_stdin, secret_value):
    """Generate authentication tokens for the given usernames.

    Reads the HMAC secret via --secret-file, --secret-stdin, or --secret.
    With no flag, reads .mograder-secret from the current directory.
    Always appends an instructor token.
    """
    from mograder.auth import INSTRUCTOR_USER, SECRET_FILENAME, make_token

    sources = sum([secret_file is not None, secret_stdin, secret_value is not None])
    if sources > 1:
        raise click.UsageError(
            "Provide at most one of --secret-file, --secret-stdin, or --secret."
        )

    if sources == 0:
        # Default: read from CWD
        default = Path(SECRET_FILENAME)
        if not default.is_file():
            raise click.UsageError(
                f"No {SECRET_FILENAME} in current directory. "
                "Use --secret-file, --secret-stdin, or --secret."
            )
        secret_file = default

    if secret_file is not None:
        secret = secret_file.read_text().strip()
    elif secret_stdin:
        secret = click.get_text_stream("stdin").read().strip()
    else:
        secret = secret_value

    for username in usernames:
        click.echo(f"{username}: {make_token(secret, username)}")
    click.echo(f"\ninstructor: {make_token(secret, INSTRUCTOR_USER)}")


# ---------------------------------------------------------------------------
# Workshop group
# ---------------------------------------------------------------------------


@cli.group()
@click.pass_context
def workshop_group(ctx):
    """Workshop notebooks with encrypted solutions."""
    pass


cli.add_command(workshop_group, "workshop")


@workshop_group.command("encrypt")
@click.argument("sources", nargs=-1, required=True)
@click.option(
    "-o",
    "--output-dir",
    type=click.Path(path_type=Path),
    default=None,
    help="Output directory (default: inferred from source path)",
)
@click.option("--salt", default=None, help="Encryption salt (default: random)")
@click.option(
    "--keys-url", default="./keys.json", help="URL for keys.json (default: relative)"
)
def workshop_encrypt(sources, output_dir, salt, keys_url):
    """Encrypt solutions in workshop notebooks.

    Parses _exercises list, encrypts solution blocks, strips solutions,
    and injects solution-reveal cells. Output: workshop-ready marimo notebook.
    """
    import secrets as _secrets

    from mograder.workshop import process_workshop

    _salt = salt or _secrets.token_hex(8)
    for src in sources:
        source = Path(src)
        out = output_dir or _infer_output_dir(source, "source", "release", "release")
        dest = process_workshop(source, out, salt=_salt, keys_url=keys_url)
        click.echo(f"OK: {_rel(source)} → {_rel(dest)}")
    click.echo(f"Workshop key (share with students verbally): {_salt}")


@workshop_group.command("export")
@click.argument("sources", nargs=-1, required=True)
@click.option(
    "-o",
    "--output-dir",
    type=click.Path(path_type=Path),
    required=True,
    help="Output directory for WASM export",
)
@click.option("--salt", default=None, help="Encryption salt (default: random)")
@click.option(
    "--keys-url", default="./keys.json", help="URL for keys.json (default: relative)"
)
def workshop_export(sources, output_dir, salt, keys_url):
    """Encrypt solutions and export as WASM HTML.

    Same as encrypt, then runs marimo export html-wasm.
    Writes keys.json (empty) and keys_all.json.
    """
    import subprocess

    from mograder.workshop import parse_exercises_metadata, process_workshop, write_keys

    output_dir = Path(output_dir)
    for src in sources:
        source = Path(src)

        # Read exercises before processing
        source_lines = source.read_text().splitlines(keepends=True)
        exercise_keys = parse_exercises_metadata(source_lines)
        if not exercise_keys:
            click.echo(f"SKIP: {_rel(source)} (no exercises marker)", err=True)
            continue

        # Use a deterministic salt for export
        _salt = salt or "workshop"
        dest = process_workshop(source, output_dir, salt=_salt, keys_url=keys_url)
        click.echo(f"Encrypted: {_rel(source)} → {_rel(dest)}")

        # Write keys files
        write_keys(exercise_keys, _salt, output_dir / "keys.json", which="empty")
        write_keys(exercise_keys, _salt, output_dir / "keys_all.json", which="all")
        click.echo(
            f"Keys: {_rel(output_dir / 'keys.json')} (empty), keys_all.json (all)"
        )

        # Export WASM HTML
        html_name = dest.stem + ".html"
        html_out = output_dir / html_name
        cmd = [
            sys.executable,
            "-m",
            "marimo",
            "export",
            "html-wasm",
            str(dest),
            "-o",
            str(html_out),
            "--mode",
            "edit",
        ]
        subprocess.run(cmd, check=True)
        click.echo(f"WASM: {_rel(html_out)}")

        # Generate dashboard HTML
        from mograder.workshop import generate_dashboard_html

        dashboard_path = output_dir / "dashboard.html"
        dashboard_path.write_text(generate_dashboard_html(exercise_keys))
        click.echo(f"Dashboard: {_rel(dashboard_path)}")


@workshop_group.command("release-key")
@click.argument("keys_file", type=click.Path(path_type=Path))
@click.argument("exercise_id")
@click.option("--salt", required=True, help="The encryption salt used at generate time")
def workshop_release_key(keys_file, exercise_id, salt):
    """Add one key to a keys.json for incremental release during a live workshop."""
    from mograder.workshop import release_key

    release_key(keys_file, exercise_id, salt)
    click.echo(f"Released key for {exercise_id} in {_rel(keys_file)}")


@workshop_group.command("serve")
@click.argument("export_dir", type=click.Path(exists=True, path_type=Path))
@click.option("--port", default=8080, help="Port to listen on")
@click.option("--host", default="127.0.0.1", help="Host to bind to")
@click.option("--salt", required=True, help="The encryption salt used at export time")
def workshop_serve(export_dir, port, host, salt):
    """Serve a workshop export directory with an instructor dashboard.

    Students open the root URL to use the WASM notebook. The instructor opens
    /dashboard.html#token=<secret> (printed at startup) to release solutions.
    """
    import secrets as _secrets

    from mograder.workshop import generate_dashboard_html
    from mograder.workshop_server import create_workshop_server

    export_dir = Path(export_dir)
    keys_path = export_dir / "keys.json"
    keys_all_path = export_dir / "keys_all.json"

    if not keys_all_path.is_file():
        raise click.ClickException(f"keys_all.json not found in {export_dir}")

    keys_all = json.loads(keys_all_path.read_text())

    # Generate dashboard HTML
    exercise_keys = list(keys_all.keys())
    dashboard_path = export_dir / "dashboard.html"
    dashboard_path.write_text(generate_dashboard_html(exercise_keys))

    # Generate a secret token for instructor auth
    secret = _secrets.token_urlsafe(16)

    server = create_workshop_server(
        export_dir=export_dir,
        keys_path=keys_path,
        keys_all=keys_all,
        secret=secret,
        host=host,
        port=port,
    )

    url = f"http://{host}:{port}"
    click.echo(f"Student notebook:       {url}/")
    click.echo(f"Instructor dashboard:   {url}/dashboard.html#token={secret}")
    click.echo("Press Ctrl+C to stop.")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        click.echo("\nShutting down.")
        server.shutdown()


@cli.command("wasm-edit-links")
@click.argument("wasm_app", type=click.Path(exists=True, path_type=Path))
@click.argument(
    "notebooks", nargs=-1, required=True, type=click.Path(exists=True, path_type=Path)
)
@click.option(
    "-o",
    "--output",
    type=click.Path(path_type=Path),
    help="Output path for modified WASM app (default: overwrite in-place)",
)
@click.option(
    "--url-template",
    default="https://molab.marimo.io/new/#code/{content_lz}",
    help="URL template; {content_lz} is replaced with lzstring-compressed content",
)
def wasm_edit_links(wasm_app, notebooks, output, url_template):
    """Inject pre-computed 'Edit in Molab' links into a WASM app source.

    WASM_APP is the student_wasm_app.py file. NOTEBOOKS are the .py notebook
    files whose compressed content will be embedded as edit links. Each
    notebook's filename stem is used as the dict key (matching the server's
    assignment directory name convention).
    """
    import lzstring

    lz = lzstring.LZString()
    links = {}
    for nb_path in notebooks:
        nb_path = Path(nb_path)
        content = nb_path.read_text()
        compressed = lz.compressToEncodedURIComponent(content)
        url = url_template.replace("{content_lz}", compressed)
        key = nb_path.stem
        links[key] = url
        click.echo(f"  {key}: {len(compressed)} chars compressed")

    source = Path(wasm_app).read_text()

    # Replace the empty dict in the precomputed_edit_links assignment
    old = "precomputed_edit_links = {}"
    if old not in source:
        raise click.ClickException(
            f"Could not find '{old}' in {wasm_app}. "
            "Make sure student_wasm_app.py has the precomputed_edit_links cell."
        )

    # Build the replacement dict literal
    dict_lines = ["precomputed_edit_links = {"]
    for k, v in links.items():
        dict_lines.append(f"        {k!r}: {v!r},")
    dict_lines.append("    }")
    replacement = "\n".join(dict_lines)

    source = source.replace(old, replacement)

    dest = output or wasm_app
    Path(dest).write_text(source)
    click.echo(f"Wrote {len(links)} edit link(s) to {_rel(Path(dest))}")
