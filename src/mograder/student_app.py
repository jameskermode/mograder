import marimo

__generated_with = "0.20.0"
app = marimo.App(width="medium")


@app.cell
def _():
    import os
    import re
    import subprocess as sp
    import sys
    from datetime import datetime, timezone
    from pathlib import Path

    import marimo as mo

    from mograder.check_cache import (
        format_check_summary,
        get_submission_status,
        is_cache_stale,
        load_cached_results,
        save_cached_results,
        save_submission_record,
    )
    from mograder.config import load_config
    from mograder.auth import (
        load_cached_https_token,
        save_cached_https_token,
    )
    from mograder.moodle_api import (
        MoodleAPIClient,
        MoodleAPIError,
        load_cached_token,
        save_cached_token,
    )
    from mograder.runner import create_shared_sandbox, run_notebook
    from mograder.transport import build_transport

    COURSE_DIR = Path(os.environ.get("MOGRADER_COURSE_DIR", ".")).resolve()
    CONFIG = load_config(COURSE_DIR)
    IS_HTTPS = CONFIG.transport == "https"

    return (
        COURSE_DIR,
        CONFIG,
        IS_HTTPS,
        MoodleAPIClient,
        MoodleAPIError,
        Path,
        build_transport,
        create_shared_sandbox,
        datetime,
        format_check_summary,
        get_submission_status,
        is_cache_stale,
        load_cached_results,
        load_cached_https_token,
        load_cached_token,
        mo,
        re,
        run_notebook,
        save_cached_results,
        save_cached_https_token,
        save_cached_token,
        save_submission_record,
        sp,
        sys,
        timezone,
    )


# --- State ---
@app.cell
def _(CONFIG, IS_HTTPS, load_cached_https_token, load_cached_token, mo):
    get_action_log, set_action_log = mo.state("")
    get_report_path, set_report_path = mo.state("")
    get_refresh, set_refresh = mo.state(0)
    get_pending, set_pending = mo.state(None)

    # Initialize token from cache if available
    _initial_token = ""
    if IS_HTTPS:
        _url = CONFIG.https_url
        if _url:
            _cached_tok = load_cached_https_token(_url)
            if _cached_tok:
                _initial_token = _cached_tok["token"]
    else:
        _url = CONFIG.moodle_url
        if _url:
            _cached_tok = load_cached_token(_url)
            if _cached_tok:
                _initial_token = _cached_tok["token"]
    get_token, set_token = mo.state(_initial_token)

    return (
        get_action_log,
        get_pending,
        get_refresh,
        get_report_path,
        get_token,
        set_action_log,
        set_pending,
        set_refresh,
        set_report_path,
        set_token,
    )


# --- Login cell ---
@app.cell
def _(
    CONFIG,
    COURSE_DIR,
    IS_HTTPS,
    MoodleAPIClient,
    MoodleAPIError,
    build_transport,
    get_token,
    mo,
    save_cached_https_token,
    save_cached_token,
    set_action_log,
    set_refresh,
    set_token,
):
    moodle_url = CONFIG.moodle_url
    token_input = mo.ui.text(label="", value="")

    # For HTTPS transport, fetch assignments from the server if not in config
    _assignments_cfg = CONFIG.assignments or CONFIG.moodle_assignments
    https_assignments = ()
    if IS_HTTPS and not _assignments_cfg:
        try:
            _transport = build_transport(CONFIG)
            _remote = _transport.list_assignments()
            https_assignments = tuple(
                {
                    "name": a.name,
                    "id": a.id,
                    "duedate": a.duedate,
                    "files": [
                        {"name": f["filename"], "url": f["url"]} for f in a.files
                    ],
                }
                for a in _remote
            )
        except Exception as _exc:
            mo.output.replace(
                mo.callout(
                    mo.md(f"Failed to fetch assignments from server: {_exc}"),
                    kind="danger",
                )
            )

    _has_assignments = bool(_assignments_cfg or https_assignments)

    if IS_HTTPS:
        if get_token():
            mo.output.replace(
                mo.hstack(
                    [mo.md("# mograder student"), mo.md(f"`{COURSE_DIR}`")],
                    justify="space-between",
                    align="center",
                )
            )
        else:
            username_input = mo.ui.text(label="Username", full_width=True)
            enrollment_input = mo.ui.text(
                label="Enrollment code", kind="password", full_width=True
            )

            def handle_https_register(_):
                user = username_input.value.strip()
                code = enrollment_input.value.strip()
                if not user or not code:
                    set_action_log("Enter both username and enrollment code")
                    return
                try:
                    from mograder.https_transport import register

                    result = register(CONFIG.https_url, user, code)
                    tok = result["token"]
                    save_cached_https_token(CONFIG.https_url, tok, user)
                    set_token(tok)
                    set_refresh(lambda v: v + 1)
                    set_action_log(f"Registered and logged in as **{user}**")
                except Exception as exc:
                    set_action_log(f"Registration failed: {exc}")

            register_btn = mo.ui.button(
                label="Register", on_change=handle_https_register
            )

            def handle_https_login(token_str):
                token_str = token_str.strip()
                if not token_str:
                    return
                _user = token_str.split(":", 1)[0] if ":" in token_str else ""
                _url = CONFIG.https_url or ""
                if _url:
                    save_cached_https_token(_url, token_str, _user)
                set_token(token_str)
                set_refresh(lambda v: v + 1)
                set_action_log(f"Logged in as **{_user}**")

            token_input = mo.ui.text(
                label="HTTPS token",
                kind="password",
                full_width=True,
                on_change=handle_https_login,
            )
            mo.output.replace(
                mo.vstack(
                    [
                        mo.md("# mograder student"),
                        mo.md(
                            "Enter your username and the enrollment code "
                            "provided by your instructor."
                        ),
                        username_input,
                        enrollment_input,
                        register_btn,
                        mo.md("---"),
                        mo.md("*Or paste a token directly:*"),
                        token_input,
                    ]
                )
            )
    elif not moodle_url or not _has_assignments:
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
    elif get_token():
        mo.output.replace(
            mo.hstack(
                [mo.md("# mograder student"), mo.md(f"`{COURSE_DIR}`")],
                justify="space-between",
                align="center",
            )
        )
    else:

        def handle_login(token_str):
            token_str = token_str.strip()
            if not token_str:
                return
            try:
                _client = MoodleAPIClient(moodle_url, token_str)
                _info = _client.get_site_info()
                save_cached_token(moodle_url, token_str, _info["fullname"])
                set_token(token_str)
                set_action_log(
                    f"Logged in as **{_info['fullname']}** ({_info['username']})"
                )
            except (MoodleAPIError, Exception) as exc:
                set_action_log(f"Login failed: {exc}")

        token_input = mo.ui.text(
            label="Moodle token",
            kind="password",
            full_width=True,
            on_change=handle_login,
        )

        _token_page = f"{moodle_url.rstrip('/')}/user/managetoken.php"
        mo.output.replace(
            mo.vstack(
                [
                    mo.md("# mograder student"),
                    mo.md(
                        f"Paste your token from "
                        f"[Moodle Security Keys]({_token_page}) "
                        f"(look for **Moodle mobile web service**)."
                    ),
                    token_input,
                ]
            )
        )
    return (https_assignments, moodle_url, token_input)


# --- Assignments table ---
# Buttons only call set_pending({...}) — actual work is in the execution cell.
@app.cell
def _(
    COURSE_DIR,
    CONFIG,
    IS_HTTPS,
    datetime,
    format_check_summary,
    get_refresh,
    get_submission_status,
    get_token,
    https_assignments,
    is_cache_stale,
    load_cached_results,
    mo,
    moodle_url,
    re,
    set_pending,
    timezone,
):
    assignments_cfg = (
        CONFIG.assignments or CONFIG.moodle_assignments or https_assignments
    )
    token = get_token()
    _ = get_refresh()

    buttons = mo.ui.dictionary({})

    _ready = bool(assignments_cfg) and (IS_HTTPS or (moodle_url and token))
    if not _ready:
        mo.output.replace(mo.md(""))
    else:

        def assignment_slug(name):
            m = re.match(r"(A\d+)", name)
            if m:
                return m.group(1)
            return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:30]

        def find_local_notebook(adir):
            pys = list(adir.glob("*.py"))
            return pys[0] if pys else None

        all_buttons = {}
        rows = []

        for i, a in enumerate(assignments_cfg):
            slug = assignment_slug(a["name"])
            adir = COURSE_DIR / slug
            local_nb = find_local_notebook(adir) if adir.is_dir() else None

            due = (
                datetime.fromtimestamp(a["duedate"], tz=timezone.utc).strftime(
                    "%Y-%m-%d %H:%M"
                )
                if a.get("duedate")
                else "No deadline"
            )

            if local_nb:
                status = get_submission_status(COURSE_DIR, local_nb)
            else:
                status = "\u2014"

            if local_nb is not None:
                cached = load_cached_results(COURSE_DIR, local_nb.name)
                stale = is_cache_stale(cached, local_nb) if cached else False
                check_summary = format_check_summary(cached, stale)
            else:
                check_summary = "---"

            btn_keys = []

            if local_nb is None:
                key = f"{i}_download"
                all_buttons[key] = mo.ui.button(
                    label="Download",
                    on_change=lambda _, a=a, s=slug: set_pending(
                        {"action": "download", "assign": a, "slug": s}
                    ),
                )
                btn_keys.append(key)

            if local_nb is not None:
                key = f"{i}_edit"
                all_buttons[key] = mo.ui.button(
                    label="Edit",
                    on_change=lambda _, p=str(local_nb), n=a["name"]: set_pending(
                        {"action": "edit", "path": p, "name": n}
                    ),
                )
                btn_keys.append(key)

                key = f"{i}_validate"
                all_buttons[key] = mo.ui.button(
                    label="Validate",
                    on_change=lambda _, p=str(local_nb), n=a["name"]: set_pending(
                        {"action": "validate", "path": p, "name": n}
                    ),
                )
                btn_keys.append(key)

                key = f"{i}_submit"
                all_buttons[key] = mo.ui.button(
                    label="Submit",
                    on_change=lambda _, p=str(local_nb), a=a, n=a["name"]: set_pending(
                        {"action": "submit", "path": p, "assign": a, "name": n}
                    ),
                )
                btn_keys.append(key)

            rows.append(
                {
                    "Assignment": a["name"],
                    "Due date": due,
                    "Status": status,
                    "Checks": check_summary,
                    "btn_keys": btn_keys,
                }
            )

        buttons = mo.ui.dictionary(all_buttons)

        display_rows = []
        for row in rows:
            keys = row.pop("btn_keys")
            btns = [buttons[k] for k in keys]
            row["Actions"] = (
                mo.hstack(btns, gap=0.5, justify="center") if btns else mo.md("")
            )
            display_rows.append(row)

        if display_rows:
            table = mo.ui.table(display_rows, selection=None)
            mo.output.replace(mo.vstack([mo.md("### Assignments"), table]))

    return (buttons,)


# --- Execution cell: reads get_pending() and does the actual work ---
@app.cell
def _(
    CONFIG,
    COURSE_DIR,
    IS_HTTPS,
    MoodleAPIClient,
    Path,
    build_transport,
    create_shared_sandbox,
    get_pending,
    get_token,
    mo,
    moodle_url,
    run_notebook,
    save_cached_results,
    save_submission_record,
    set_action_log,
    set_pending,
    set_refresh,
    set_report_path,
    sp,
    sys,
):
    pending = get_pending()
    if pending is not None:
        _act = pending["action"]
        _token = get_token()
        if IS_HTTPS:
            _transport = build_transport(CONFIG)
            # Override with the token from the UI if present
            if _token:
                _transport.token = _token
                _transport.user = _token.split(":", 1)[0] if ":" in _token else ""
            _client = None
        else:
            _transport = None
            _client = MoodleAPIClient(moodle_url, _token) if _token else None

        if _act == "download" and (_client or _transport):
            _assign = pending["assign"]
            _slug = pending["slug"]
            _adir = COURSE_DIR / _slug
            _adir.mkdir(exist_ok=True)
            _name = _assign["name"]
            _py_files = [
                f for f in _assign.get("files", []) if f["name"].endswith(".py")
            ]
            if not _py_files:
                set_action_log(f"No `.py` file attached to **{_name}**")
            else:
                try:
                    for _finfo in _py_files:
                        _dest = _adir / _finfo["name"]
                        if _transport:
                            _transport.download_file(_finfo["url"], _dest)
                        else:
                            _file_url = _finfo["url"].replace(
                                "/pluginfile.php/", "/webservice/pluginfile.php/"
                            )
                            _client.download_file(_file_url, _dest)
                    set_action_log(f"Downloaded **{_name}** to `{_slug}/`")
                except Exception as _exc:
                    set_action_log(f"Download failed for **{_name}**: {_exc}")
            set_refresh(lambda v: v + 1)

        elif _act == "edit":
            _path = pending["path"]
            _name = pending["name"]
            _cmd = [sys.executable, "-m", "marimo", "edit", "--sandbox", _path]
            if CONFIG.headless_edit:
                import os as _os
                import re as _re
                import threading as _threading
                from urllib.parse import urlparse as _urlparse

                _cmd.extend(["--headless", "--host", "0.0.0.0"])
                _proc = sp.Popen(_cmd, stdout=sp.PIPE, stderr=sp.STDOUT, text=True)
                _url_box = []
                _found = _threading.Event()

                def _drain_output():
                    for _line in _proc.stdout:
                        if not _url_box:
                            _m = _re.search(r"https?://\S+", _line)
                            if _m:
                                _url_box.append(_m.group(0))
                                _found.set()

                _threading.Thread(target=_drain_output, daemon=True).start()
                _found.wait(timeout=30)
                if _url_box:
                    _raw_url = _url_box[0]
                    if _os.environ.get("CODESPACES"):
                        _parsed = _urlparse(_raw_url)
                        _port = _parsed.port or 2718
                        _cs_name = _os.environ["CODESPACE_NAME"]
                        _cs_domain = _os.environ.get(
                            "GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN",
                            "app.github.dev",
                        )
                        _url = f"https://{_cs_name}-{_port}.{_cs_domain}"
                        if _parsed.query:
                            _url += f"?{_parsed.query}"
                    else:
                        _url = _raw_url
                    set_action_log(f"Opened **{_name}** for editing: [{_url}]({_url})")
                else:
                    set_action_log(
                        f"Opened **{_name}** for editing (could not detect URL)"
                    )
            else:
                sp.Popen(_cmd)
                set_action_log(f"Opened **{_name}** for editing")

        elif _act == "validate":
            _path = Path(pending["path"])
            _name = pending["name"]
            with mo.status.spinner(
                title=f"Validating {_name}", remove_on_exit=True
            ) as _spinner:
                _spinner.update(subtitle="Installing dependencies...")
                _sandbox = create_shared_sandbox(_path)
                _spinner.update(subtitle="Running notebook...")
                try:
                    _result = run_notebook(
                        _path, sandbox_dir=_sandbox, html_dir=_path.parent
                    )
                    _mtime = _path.stat().st_mtime
                    save_cached_results(COURSE_DIR, _path.name, _result, _mtime)
                    _passed = sum(1 for c in _result.checks if c.status == "success")
                    _total = len(_result.checks)
                    if not _result.export_ok:
                        _msg = (
                            f"Validation of **{_name}** failed: {_result.export_error}"
                        )
                    elif _total == 0:
                        _msg = f"Validation of **{_name}** complete (no checks found)"
                    else:
                        _msg = (
                            f"Validation of **{_name}** complete: "
                            f"{_passed}/{_total} checks passed"
                        )
                    if _result.cell_errors > 0:
                        _msg += f" ({_result.cell_errors} cell error(s))"
                    set_action_log(_msg)
                    if _result.html_path:
                        set_report_path(str(_result.html_path.resolve()))
                except Exception as _exc:
                    set_action_log(f"Validation failed for **{_name}**: {_exc}")
            set_refresh(lambda v: v + 1)

        elif _act == "submit" and (_client or _transport):
            _path = Path(pending["path"])
            _assign = pending["assign"]
            _name = pending["name"]
            try:
                if _transport:
                    _transport.submit_file(_assign["id"], _path)
                else:
                    _item_id = _client.upload_file(_path)
                    _client.save_submission(_assign["id"], _item_id)
                save_submission_record(COURSE_DIR, _path.name, _path.stat().st_mtime)
                set_action_log(f"Submitted **{_name}** (`{_path.name}`)")
            except Exception as _exc:
                set_action_log(f"Submit failed for **{_name}**: {_exc}")
            set_refresh(lambda v: v + 1)

        set_pending(None)
    return ()


# --- Dismiss button (own cell so it's stable across log changes) ---
@app.cell
def _(mo, set_action_log, set_report_path):
    def _dismiss(_):
        set_action_log("")
        set_report_path("")

    dismiss_btn = mo.ui.button(label="Dismiss", on_change=_dismiss)
    return (dismiss_btn,)


# --- Activity log ---
@app.cell
def _(dismiss_btn, get_action_log, get_report_path, mo):
    log_text = get_action_log()
    report_path = get_report_path()

    if log_text:
        kind = (
            "danger"
            if "failed" in log_text.lower() or "error" in log_text.lower()
            else "info"
        )
        _parts = [mo.callout(mo.md(log_text), kind=kind)]
        if report_path:
            _parts.append(mo.md("*See report below.*"))
        _parts.append(dismiss_btn)
        mo.output.replace(mo.vstack(_parts))
    else:
        mo.output.replace(mo.md(""))
    return ()


# --- Report preview (iframe, like formgrader grading tab) ---
@app.cell
def _(Path, get_report_path, mo):
    import base64 as _b64

    _report = get_report_path()
    if _report:
        _html_path = Path(_report)
        if _html_path.exists():
            _encoded = _b64.b64encode(_html_path.read_bytes()).decode("ascii")
            mo.output.replace(
                mo.Html(
                    f'<iframe src="data:text/html;base64,{_encoded}" '
                    f'style="width:100%; height:80vh; border:1px solid #ccc;"></iframe>'
                )
            )
        else:
            mo.output.replace(mo.md(""))
    else:
        mo.output.replace(mo.md(""))
    return ()


if __name__ == "__main__":
    app.run()
