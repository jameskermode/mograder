import marimo

__generated_with = "0.20.0"
app = marimo.App(width="medium")


@app.cell
def _():
    import os
    import subprocess as sp
    import sys
    import zipfile
    from pathlib import Path

    import marimo as mo

    from mograder.check_cache import (
        format_check_summary,
        is_cache_stale,
        load_cached_results,
        save_cached_results,
    )
    from mograder.config import load_config
    from mograder.moodle_api import (
        MoodleAPIClient,
        MoodleAPIError,
        clear_cached_token,
        load_cached_token,
        request_token,
        save_cached_token,
    )
    from mograder.runner import create_shared_sandbox, run_notebook

    COURSE_DIR = Path(os.environ.get("MOGRADER_COURSE_DIR", ".")).resolve()
    CONFIG = load_config(COURSE_DIR)

    return (
        COURSE_DIR,
        CONFIG,
        MoodleAPIClient,
        MoodleAPIError,
        Path,
        clear_cached_token,
        create_shared_sandbox,
        format_check_summary,
        is_cache_stale,
        load_cached_results,
        load_cached_token,
        mo,
        os,
        request_token,
        run_notebook,
        save_cached_results,
        save_cached_token,
        sp,
        sys,
        zipfile,
    )


@app.cell
def _(mo):
    get_client, set_client = mo.state(None)
    get_user_info, set_user_info = mo.state(None)
    get_action_log, set_action_log = mo.state("")
    get_refresh, set_refresh = mo.state(0)
    get_login_error, set_login_error = mo.state("")
    get_validating, set_validating = mo.state("")
    get_feedback_display, set_feedback_display = mo.state("")
    return (
        get_action_log,
        get_client,
        get_feedback_display,
        get_login_error,
        get_refresh,
        get_user_info,
        get_validating,
        set_action_log,
        set_client,
        set_feedback_display,
        set_login_error,
        set_refresh,
        set_user_info,
        set_validating,
    )


@app.cell
def _(
    CONFIG,
    MoodleAPIClient,
    MoodleAPIError,
    clear_cached_token,
    get_client,
    get_login_error,
    get_user_info,
    load_cached_token,
    mo,
    os,
    request_token,
    save_cached_token,
    set_client,
    set_login_error,
    set_user_info,
):
    # --- Auto-login from cached token or env var on first load ---
    _client = get_client()
    _user = get_user_info()

    if _client is None and _user is None:
        _moodle_url = CONFIG.moodle_url or ""
        _env_token = os.environ.get("MOGRADER_MOODLE_TOKEN")

        if _env_token and _moodle_url:
            try:
                _c = MoodleAPIClient(_moodle_url, _env_token)
                _info = _c.get_site_info()
                set_client(_c)
                set_user_info(_info)
            except Exception:
                pass
        elif _moodle_url:
            _cached = load_cached_token(_moodle_url)
            if _cached:
                try:
                    _c = MoodleAPIClient(_moodle_url, _cached["token"])
                    _info = _c.get_site_info()
                    set_client(_c)
                    set_user_info(_info)
                except Exception:
                    clear_cached_token()

    # --- Build the login UI ---
    _client = get_client()
    _user = get_user_info()
    _login_err = get_login_error()

    if _client is not None and _user is not None:
        _logout_btn = mo.ui.button(
            label="Logout",
            on_change=lambda _: (
                set_client(None),
                set_user_info(None),
                clear_cached_token(),
            ),
        )
        login_ui = mo.callout(
            mo.hstack(
                [
                    mo.md(
                        f"Logged in as **{_user['fullname']}** "
                        f"({_user['username']}) on {_user.get('sitename', '')}"
                    ),
                    _logout_btn,
                ],
                justify="space-between",
                align="center",
            ),
            kind="success",
        )
    else:
        _url_input = mo.ui.text(
            value=CONFIG.moodle_url or "",
            label="Moodle URL",
            full_width=True,
        )
        _user_input = mo.ui.text(value="", label="Username")
        _pass_input = mo.ui.text(value="", label="Password", kind="password")

        def _do_login(_):
            _url = _url_input.value.strip()
            _uname = _user_input.value.strip()
            _pwd = _pass_input.value
            if not _url or not _uname or not _pwd:
                set_login_error("Please fill in all fields")
                return
            try:
                _tok = request_token(_url, _uname, _pwd)
                _c = MoodleAPIClient(_url, _tok)
                _info = _c.get_site_info()
                save_cached_token(_url, _tok, _info["fullname"])
                set_client(_c)
                set_user_info(_info)
                set_login_error("")
            except MoodleAPIError as e:
                set_login_error(f"Login failed: {e}")
            except Exception as e:
                set_login_error(f"Connection error: {e}")

        _login_btn = mo.ui.button(label="Login", on_change=_do_login)

        _err_display = (
            mo.callout(mo.md(_login_err), kind="danger") if _login_err else mo.md("")
        )

        login_ui = mo.vstack(
            [
                mo.md("### Moodle Login"),
                _url_input,
                mo.hstack([_user_input, _pass_input, _login_btn], align="end", gap=1),
                _err_display,
            ]
        )

    mo.output.replace(login_ui)
    return (login_ui,)


@app.cell
def _(
    COURSE_DIR,
    CONFIG,
    MoodleAPIError,
    Path,
    create_shared_sandbox,
    format_check_summary,
    get_client,
    get_refresh,
    get_validating,
    is_cache_stale,
    load_cached_results,
    mo,
    run_notebook,
    save_cached_results,
    set_action_log,
    set_feedback_display,
    set_refresh,
    set_validating,
    sp,
    sys,
    zipfile,
):
    _client = get_client()
    _ = get_refresh()  # reactive dependency for re-scan

    if _client is None:
        mo.output.replace(
            mo.callout(
                mo.md("Log in to Moodle above to view assignments."), kind="warn"
            )
        )
    else:
        _course_id = CONFIG.moodle_course_id
        if not _course_id:
            mo.output.replace(
                mo.callout(
                    mo.md(
                        "No `course_id` set in `[moodle]` section of `mograder.toml`. "
                        "Add it to see your assignments."
                    ),
                    kind="danger",
                )
            )
        else:
            try:
                _assignments = _client.get_assignments(_course_id)
            except MoodleAPIError as e:
                mo.output.replace(
                    mo.callout(
                        mo.md(f"Failed to fetch assignments: {e}"), kind="danger"
                    )
                )
                _assignments = []

            # Fetch submission status for all assignments
            _statuses = {}
            for _a in _assignments:
                try:
                    _statuses[_a["id"]] = _client.get_submission_status(_a["id"])
                except Exception:
                    _statuses[_a["id"]] = None

            if _assignments:
                from datetime import datetime, timezone

                # --- Build action callbacks ---
                def _fetch_assignment(_, a=None):
                    _files = a.get("introattachments", [])
                    if not _files:
                        set_action_log(f"No files attached to '{a['name']}'")
                        return
                    _out = COURSE_DIR
                    _out.mkdir(parents=True, exist_ok=True)
                    _downloaded = []
                    for _f in _files:
                        _dest = _out / _f["filename"]
                        _client.download_file(_f["fileurl"], _dest)
                        _downloaded.append(_dest)
                    for _d in _downloaded:
                        if _d.suffix.lower() == ".zip":
                            with zipfile.ZipFile(_d) as _zf:
                                _zf.extractall(_out)
                    set_action_log(
                        f"Fetched **{a['name']}** ({len(_downloaded)} file(s))"
                    )
                    set_refresh(lambda v: v + 1)

                def _edit_assignment(_, path=None, name=None):
                    sp.Popen(
                        [sys.executable, "-m", "marimo", "edit", "--sandbox", str(path)]
                    )
                    set_action_log(f"Opened **{name}** for editing")

                def _submit_assignment(_, a=None, path=None):
                    try:
                        _item_id = _client.upload_file(path)
                        _client.save_submission(a["id"], _item_id)
                        _client.submit_for_grading(a["id"])
                        set_action_log(f"Submitted **{a['name']}** for grading")
                        set_refresh(lambda v: v + 1)
                    except MoodleAPIError as e:
                        set_action_log(f"Submit failed for **{a['name']}**: {e}")

                def _validate_assignment(_, path=None, name=None):
                    set_validating(name)
                    set_action_log(
                        f"Validating **{name}**... this may take a few minutes"
                    )
                    try:
                        _sandbox = create_shared_sandbox(path)
                        _result = run_notebook(path, sandbox_dir=_sandbox)
                        _mtime = path.stat().st_mtime
                        save_cached_results(COURSE_DIR, path.name, _result, _mtime)
                        _passed = sum(
                            1 for c in _result.checks if c.status == "success"
                        )
                        _total = len(_result.checks)
                        if not _result.export_ok:
                            _msg = (
                                f"Validation of **{name}** failed: "
                                f"{_result.export_error}"
                            )
                        elif _total == 0:
                            _msg = (
                                f"Validation of **{name}** complete (no checks found)"
                            )
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

                def _view_feedback(_, a=None, status=None):
                    if status and status.get("graded"):
                        _text = f"**Grade:** {status['grade']}"
                        if status["feedback"]:
                            _text += f"\n\n**Feedback:**\n\n{status['feedback']}"
                        set_feedback_display(f"### {a['name']}\n\n{_text}")
                    else:
                        set_feedback_display(
                            f"### {a['name']}\n\nNo feedback available yet."
                        )

                # --- Build table rows ---
                _rows = []
                _is_validating = get_validating()
                for _a in _assignments:
                    _due = (
                        datetime.fromtimestamp(_a["duedate"], tz=timezone.utc).strftime(
                            "%Y-%m-%d %H:%M"
                        )
                        if _a["duedate"]
                        else "No deadline"
                    )

                    # Determine local status by checking for .py files from
                    # this assignment's introattachments
                    _py_files = [
                        f
                        for f in _a.get("introattachments", [])
                        if f["filename"].endswith(".py")
                    ]
                    _local_path = None
                    for _pf in _py_files:
                        _candidate = COURSE_DIR / _pf["filename"]
                        if _candidate.exists():
                            _local_path = _candidate
                            break

                    # Determine status from Moodle
                    _sub_status = _statuses.get(_a["id"])
                    if _sub_status and _sub_status.get("graded"):
                        _status = f"Graded ({_sub_status['grade']})"
                    elif _sub_status and _sub_status["status"] == "submitted":
                        _status = "Submitted"
                    elif _sub_status and _sub_status["status"] == "draft":
                        _status = "Draft"
                    elif _local_path is not None:
                        _status = "Fetched"
                    else:
                        _status = "\u2014"

                    # Check validation cache
                    if _local_path is not None:
                        _cached = load_cached_results(COURSE_DIR, _local_path.name)
                        _stale = (
                            is_cache_stale(_cached, _local_path) if _cached else False
                        )
                        _check_summary = format_check_summary(_cached, _stale)
                    else:
                        _check_summary = "---"

                    # Build action buttons
                    if _local_path is not None:
                        _btns = [
                            mo.ui.button(
                                label="Edit",
                                on_change=lambda _btn, p=_local_path, n=_a["name"]: (
                                    _edit_assignment(_btn, path=p, name=n)
                                ),
                            ),
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
                            ),
                            mo.ui.button(
                                label="Submit",
                                on_change=lambda _btn, a=_a, p=_local_path: (
                                    _submit_assignment(_btn, a=a, path=p)
                                ),
                            ),
                        ]
                        # Add feedback button if graded
                        if _sub_status and _sub_status.get("graded"):
                            _btns.append(
                                mo.ui.button(
                                    label="Feedback",
                                    on_change=lambda _btn, a=_a, s=_sub_status: (
                                        _view_feedback(_btn, a=a, status=s)
                                    ),
                                )
                            )
                        _actions = mo.hstack(_btns, gap=0.5)
                    else:
                        _actions = mo.ui.button(
                            label="Fetch",
                            on_change=lambda _btn, a=_a: _fetch_assignment(_btn, a=a),
                        )

                    _rows.append(
                        {
                            "Assignment": _a["name"],
                            "Due date": _due,
                            "Status": _status,
                            "Checks": _check_summary,
                            "Actions": _actions,
                        }
                    )

                _table = mo.ui.table(_rows, selection=None)
                mo.output.replace(mo.vstack([mo.md("### Assignments"), _table]))
    return ()


@app.cell
def _(get_feedback_display, mo, set_feedback_display):
    _feedback = get_feedback_display()
    if _feedback:
        _clear_btn = mo.ui.button(
            label="Close", on_change=lambda _: set_feedback_display("")
        )
        feedback_ui = mo.vstack([mo.callout(mo.md(_feedback), kind="info"), _clear_btn])
    else:
        feedback_ui = mo.md("")
    mo.output.replace(feedback_ui)
    return (feedback_ui,)


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
