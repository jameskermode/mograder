# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "marimo",
#     "mograder",
# ]
# ///

import marimo

__generated_with = "0.20.0"
app = marimo.App(width="medium")


@app.cell
def _():
    import os
    import subprocess as sp
    import sys
    import webbrowser
    from datetime import datetime, timezone
    from pathlib import Path

    import marimo as mo

    from mograder.check_cache import (
        format_check_summary,
        is_cache_stale,
        load_cached_results,
        save_cached_results,
    )
    from mograder.config import load_config
    from mograder.runner import create_shared_sandbox, run_notebook

    COURSE_DIR = Path(os.environ.get("MOGRADER_COURSE_DIR", ".")).resolve()
    CONFIG = load_config(COURSE_DIR)

    return (
        COURSE_DIR,
        CONFIG,
        Path,
        create_shared_sandbox,
        datetime,
        format_check_summary,
        is_cache_stale,
        load_cached_results,
        mo,
        run_notebook,
        save_cached_results,
        sp,
        sys,
        timezone,
        webbrowser,
    )


@app.cell
def _(mo):
    get_action_log, set_action_log = mo.state("")
    get_refresh, set_refresh = mo.state(0)
    get_validating, set_validating = mo.state("")
    return (
        get_action_log,
        get_refresh,
        get_validating,
        set_action_log,
        set_refresh,
        set_validating,
    )


@app.cell
def _(CONFIG, mo):
    _url = CONFIG.moodle_url
    _assignments = CONFIG.moodle_assignments

    if not _url or not _assignments:
        mo.output.replace(
            mo.callout(
                mo.md(
                    "No Moodle assignments configured. "
                    "Ask your instructor to run `mograder moodle sync` and "
                    "share the updated `mograder.toml`."
                ),
                kind="warn",
            )
        )
    else:
        mo.output.replace(
            mo.callout(
                mo.md(
                    f"Connected to **{_url}**. "
                    "Open assignment pages in your browser (log in via SSO if prompted)."
                ),
                kind="info",
            )
        )
    return ()


@app.cell
def _(
    COURSE_DIR,
    CONFIG,
    Path,
    create_shared_sandbox,
    datetime,
    format_check_summary,
    get_refresh,
    get_validating,
    is_cache_stale,
    load_cached_results,
    mo,
    run_notebook,
    save_cached_results,
    set_action_log,
    set_refresh,
    set_validating,
    sp,
    sys,
    timezone,
    webbrowser,
):
    _url = CONFIG.moodle_url
    _assignments = CONFIG.moodle_assignments
    _ = get_refresh()  # reactive dependency

    if not _url or not _assignments:
        mo.output.replace(mo.md(""))
    else:

        def _open_in_browser(_, page_url=None):
            webbrowser.open(page_url)

        def _edit_assignment(_, path=None, name=None):
            sp.Popen([sys.executable, "-m", "marimo", "edit", "--sandbox", str(path)])
            set_action_log(f"Opened **{name}** for editing")

        def _validate_assignment(_, path=None, name=None):
            set_validating(name)
            set_action_log(f"Validating **{name}**... this may take a few minutes")
            try:
                _sandbox = create_shared_sandbox(path)
                _result = run_notebook(path, sandbox_dir=_sandbox)
                _mtime = path.stat().st_mtime
                save_cached_results(COURSE_DIR, path.name, _result, _mtime)
                _passed = sum(1 for c in _result.checks if c.status == "success")
                _total = len(_result.checks)
                if not _result.export_ok:
                    _msg = f"Validation of **{name}** failed: {_result.export_error}"
                elif _total == 0:
                    _msg = f"Validation of **{name}** complete (no checks found)"
                else:
                    _msg = (
                        f"Validation of **{name}** complete: "
                        f"{_passed}/{_total} checks passed"
                    )
                if _result.cell_errors > 0:
                    _msg += f" ({_result.cell_errors} cell error(s))"
                set_action_log(_msg)
            except Exception as e:
                set_action_log(f"Validation failed for **{name}**: {e}")
            finally:
                set_validating("")
                set_refresh(lambda v: v + 1)

        _base = _url.rstrip("/")
        _rows = []
        _is_validating = get_validating()

        for _a in _assignments:
            _cmid = _a.get("cmid")
            _due = (
                datetime.fromtimestamp(_a["duedate"], tz=timezone.utc).strftime(
                    "%Y-%m-%d %H:%M"
                )
                if _a.get("duedate")
                else "No deadline"
            )

            # Check for local .py files from this assignment
            _local_path = None
            for _f in _a.get("files", []):
                if _f["name"].endswith(".py"):
                    _candidate = COURSE_DIR / _f["name"]
                    if _candidate.exists():
                        _local_path = _candidate
                        break

            # Status based on local files
            _status = "Fetched" if _local_path else "\u2014"

            # Check validation cache
            if _local_path is not None:
                _cached = load_cached_results(COURSE_DIR, _local_path.name)
                _stale = is_cache_stale(_cached, _local_path) if _cached else False
                _check_summary = format_check_summary(_cached, _stale)
            else:
                _check_summary = "---"

            # Build action buttons
            _btns = []

            if _local_path is not None:
                _btns.append(
                    mo.ui.button(
                        label="Edit",
                        on_change=lambda _btn, p=_local_path, n=_a["name"]: (
                            _edit_assignment(_btn, path=p, name=n)
                        ),
                    )
                )
                _btns.append(
                    mo.ui.button(
                        label=(
                            "Validating..."
                            if _is_validating == _a["name"]
                            else "Validate"
                        ),
                        on_change=lambda _btn, p=_local_path, n=_a["name"]: (
                            _validate_assignment(_btn, path=p, name=n)
                        ),
                        disabled=bool(_is_validating),
                    )
                )

            # Moodle page buttons (always available if cmid is set)
            if _cmid:
                _assign_url = f"{_base}/mod/assign/view.php?id={_cmid}"

                if _local_path is None:
                    # Not fetched yet — show download button
                    _btns.append(
                        mo.ui.button(
                            label="Download",
                            on_change=lambda _btn, u=_assign_url: _open_in_browser(
                                _btn, page_url=u
                            ),
                        )
                    )
                else:
                    # Already fetched — show submit button
                    _submit_url = f"{_assign_url}&action=editsubmission"
                    _btns.append(
                        mo.ui.button(
                            label="Submit",
                            on_change=lambda _btn, u=_submit_url: _open_in_browser(
                                _btn, page_url=u
                            ),
                        )
                    )

                # Feedback — always available
                _btns.append(
                    mo.ui.button(
                        label="Feedback",
                        on_change=lambda _btn, u=_assign_url: _open_in_browser(
                            _btn, page_url=u
                        ),
                    )
                )

            _actions = mo.hstack(_btns, gap=0.5) if _btns else mo.md("")

            _rows.append(
                {
                    "Assignment": _a["name"],
                    "Due date": _due,
                    "Status": _status,
                    "Checks": _check_summary,
                    "Actions": _actions,
                }
            )

        if _rows:
            _table = mo.ui.table(_rows, selection=None)
            mo.output.replace(mo.vstack([mo.md("### Assignments"), _table]))
    return ()


@app.cell
def _(get_action_log, mo, set_action_log):
    _log = get_action_log()

    if _log:
        _kind = (
            "danger" if "failed" in _log.lower() or "error" in _log.lower() else "info"
        )
        _clear_btn = mo.ui.button(
            label="Dismiss", on_change=lambda _: set_action_log("")
        )
        activity_log = mo.vstack([mo.callout(mo.md(_log), kind=_kind), _clear_btn])
    else:
        activity_log = mo.md("")

    mo.output.replace(activity_log)
    return (activity_log,)


if __name__ == "__main__":
    app.run()
