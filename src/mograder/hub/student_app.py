import marimo

__generated_with = "0.20.0"
app = marimo.App(width="medium", app_title="mograder hub", html_head_file="head.html")


@app.cell
def _():
    from pathlib import Path

    import marimo as mo

    from mograder._brand import logo_html as brand_logo_html, version_html
    from mograder.student.common import (
        hub_download,
        hub_start_edit,
        hub_submit,
        hub_validate,
        load_student_config,
    )

    CONFIG, COURSE_DIR = load_student_config()

    def _hub_username():
        """Read username from request scope (set by RemoteUserMiddleware)."""
        req = mo.app_meta().request
        user = req.user if req else None
        if user is None:
            return ""
        if isinstance(user, dict):
            return user.get("username", "")
        return getattr(user, "username", "")

    HUB_USER = _hub_username()

    return (
        COURSE_DIR,
        CONFIG,
        HUB_USER,
        Path,
        brand_logo_html,
        hub_download,
        hub_start_edit,
        hub_submit,
        hub_validate,
        mo,
        version_html,
    )


# --- State ---
@app.cell
def _(mo):
    get_action_log, set_action_log = mo.state("")
    get_report_path, set_report_path = mo.state("")
    get_refresh, set_refresh = mo.state(0)
    get_pending, set_pending = mo.state(None)

    return (
        get_action_log,
        get_pending,
        get_refresh,
        get_report_path,
        set_action_log,
        set_pending,
        set_refresh,
        set_report_path,
    )


# --- Header ---
@app.cell
def _(
    COURSE_DIR,
    CONFIG,
    HUB_USER,
    brand_logo_html,
    version_html,
    mo,
):
    _app_title = CONFIG.title or "mograder hub"
    _version = version_html()
    _heading = mo.Html(
        f'<div style="display:flex;align-items:center;gap:0.3em">{brand_logo_html()} <span style="font-size:2em;font-weight:bold">{_app_title}</span> {_version}</div>'
    )

    _rel_dir = COURSE_DIR / CONFIG.hub_release_dir
    https_assignments = ()
    hub_lectures = ()
    if _rel_dir.is_dir():
        import json as _json

        for d in sorted(_rel_dir.iterdir()):
            if not d.is_dir() or not (d / f"{d.name}.py").is_file():
                continue
            _manifest = d / "files.json"
            _type = "assignment"
            if _manifest.is_file():
                try:
                    _type = _json.loads(_manifest.read_text()).get("type", "assignment")
                except Exception:
                    pass
            if _type == "lecture":
                hub_lectures += ({"name": d.name},)
            else:
                https_assignments += (
                    {
                        "name": d.name,
                        "id": d.name,
                        "files": [
                            {"name": f.name, "url": ""} for f in sorted(d.glob("*.py"))
                        ],
                    },
                )
    mo.output.replace(
        mo.hstack(
            [_heading, mo.md(f"Logged in as **{HUB_USER}**")],
            justify="space-between",
            align="center",
        )
    )
    return (https_assignments, hub_lectures)


# --- Assignments table ---
# Buttons only call set_pending({...}) — actual work is in the execution cell.
@app.cell
def _(
    COURSE_DIR,
    CONFIG,
    HUB_USER,
    Path,
    get_refresh,
    https_assignments,
    mo,
    set_pending,
):
    assignments_cfg = (
        CONFIG.assignments or CONFIG.moodle_assignments or https_assignments
    )
    _ = get_refresh()

    buttons = mo.ui.dictionary({})

    _ready = bool(assignments_cfg)
    if not _ready:
        mo.output.replace(mo.md(""))
    else:
        # Hub mode: status from hub notebooks dir, hub-specific actions
        _nb_dir = Path(COURSE_DIR / CONFIG.hub_notebooks_dir)

        _all_buttons = {}
        _rows = []

        for _i, _a in enumerate(assignments_cfg):
            _slug = _a.get("dir") or _a["name"]
            _display = _a.get("name", _slug)
            _nb_path = _nb_dir / HUB_USER / _slug / f"{_slug}.py"
            _has_file = _nb_path.exists()

            if not _has_file:
                _status = "not started"
            else:
                _uploaded_marker = _nb_path.parent / ".uploaded"
                _submitted_marker = _nb_path.parent / ".submitted"
                _nb_mtime = _nb_path.stat().st_mtime
                if (
                    _submitted_marker.exists()
                    and _submitted_marker.stat().st_mtime >= _nb_mtime
                ):
                    _status = "submitted"
                elif _uploaded_marker.exists():
                    if _nb_mtime > _uploaded_marker.stat().st_mtime:
                        _status = "edited"
                    else:
                        _status = "downloaded"
                else:
                    _status = "downloaded"
            _check_summary = "---"

            _btn_keys = []

            if not _has_file:
                _key = f"{_i}_download"
                _all_buttons[_key] = mo.ui.button(
                    label="Download",
                    on_change=lambda _, n=_slug: set_pending(
                        {"action": "hub_download", "assignment": n}
                    ),
                )
                _btn_keys.append(_key)

            if _has_file:
                _key = f"{_i}_edit"
                _all_buttons[_key] = mo.ui.button(
                    label="Edit",
                    on_change=lambda _, n=_slug: set_pending(
                        {"action": "hub_edit", "assignment": n}
                    ),
                )
                _btn_keys.append(_key)

                _key = f"{_i}_validate"
                _all_buttons[_key] = mo.ui.button(
                    label="Validate",
                    on_change=lambda _, n=_slug: set_pending(
                        {"action": "hub_validate", "assignment": n}
                    ),
                )
                _btn_keys.append(_key)

                _key = f"{_i}_export"
                _all_buttons[_key] = mo.ui.button(
                    label="Export",
                    on_change=lambda _, n=_slug: set_pending(
                        {"action": "hub_export", "assignment": n}
                    ),
                )
                _btn_keys.append(_key)

                _key = f"{_i}_submit"
                _all_buttons[_key] = mo.ui.button(
                    label="Submit",
                    on_change=lambda _, n=_slug: set_pending(
                        {"action": "hub_submit", "assignment": n}
                    ),
                )
                _btn_keys.append(_key)

            _rows.append(
                {
                    "Assignment": _display,
                    "Status": _status,
                    "Checks": _check_summary,
                    "btn_keys": _btn_keys,
                }
            )

        buttons = mo.ui.dictionary(_all_buttons)

        _display_rows = []
        for _row in _rows:
            _keys = _row.pop("btn_keys")
            _btns = [buttons[k] for k in _keys]
            _row["Actions"] = (
                mo.hstack(_btns, gap=0.5, justify="center") if _btns else mo.md("")
            )
            _display_rows.append(_row)

        if _display_rows:
            _table = mo.ui.table(_display_rows, selection=None)
            mo.output.replace(mo.vstack([mo.md("### Assignments"), _table]))

    return (buttons,)


# --- Lectures table ---
@app.cell
def _(
    hub_lectures,
    mo,
    set_pending,
):
    if not hub_lectures:
        mo.output.replace(mo.md(""))
    else:
        _all_buttons = {}
        _rows = []
        for _i, _lec in enumerate(hub_lectures):
            _name = _lec["name"]
            _key = f"lec_{_i}_run"
            _all_buttons[_key] = mo.ui.button(
                label="Run",
                on_change=lambda _, n=_name: set_pending(
                    {"action": "hub_run_lecture", "lecture": n}
                ),
            )
            _rows.append({"Lecture": _name, "Actions": _all_buttons[_key]})

        _lec_buttons = mo.ui.dictionary(_all_buttons)
        _table = mo.ui.table(_rows, selection=None)
        mo.output.replace(mo.vstack([mo.md("### Lectures"), _table]))
    return ()


# --- Execution cell: reads get_pending() and does the actual work ---
@app.cell
def _(
    CONFIG,
    HUB_USER,
    get_pending,
    hub_download,
    hub_start_edit,
    hub_submit,
    hub_validate,
    mo,
    set_action_log,
    set_pending,
    set_refresh,
    set_report_path,
):
    pending = get_pending()
    if pending is not None:
        _act = pending["action"]

        import httpx as _httpx

        _client = _httpx.Client(base_url=f"http://127.0.0.1:{CONFIG.hub_port}")
        _hub_headers = {"X-Remote-User": HUB_USER}

        if _act == "hub_download":
            _name = pending["assignment"]
            _result = hub_download(_client, HUB_USER, _name, _hub_headers)
            set_action_log(_result.message)
            set_refresh(lambda v: v + 1)

        elif _act == "hub_edit":
            _name = pending["assignment"]
            with mo.status.spinner(
                title=f"Starting editor for {_name}...",
                remove_on_exit=True,
            ):
                _result = hub_start_edit(_client, HUB_USER, _name, _hub_headers)
                if _result.success:
                    # Use deep link URL — works behind reverse proxies
                    set_action_log(
                        f"Editing **{_name}** — "
                        f'<a href="edit/{_name}" target="_blank">open editor</a>'
                    )
                else:
                    set_action_log(_result.message)

        elif _act == "hub_validate":
            _name = pending["assignment"]
            with mo.status.spinner(
                title=f"Validating {_name}...",
                remove_on_exit=True,
            ):
                _result = hub_validate(_client, HUB_USER, _name, _hub_headers)
                set_action_log(_result.message)
                if _result.url:
                    set_report_path(_result.url)

        elif _act == "hub_export":
            _name = pending["assignment"]
            _url = f"export/{HUB_USER}/{_name}"
            set_action_log(
                f'Export **{_name}**: <a href="{_url}" target="_blank">download</a>'
            )

        elif _act == "hub_submit":
            _name = pending["assignment"]
            with mo.status.spinner(
                title=f"Submitting {_name}...",
                remove_on_exit=True,
            ):
                _result = hub_submit(_client, HUB_USER, _name, _hub_headers)
                set_action_log(_result.message)

        elif _act == "hub_run_lecture":
            _name = pending["lecture"]
            with mo.status.spinner(
                title=f"Starting {_name}...",
                remove_on_exit=True,
            ):
                try:
                    _resp = _client.post(
                        f"/start-run/{_name}",
                        headers=_hub_headers,
                        timeout=120,
                    )
                    if _resp.status_code == 200:
                        # Use deep link URL — works behind reverse proxies
                        set_action_log(
                            f"Viewing **{_name}** — "
                            f'<a href="run/{_name}" target="_blank">open lecture</a>'
                        )
                    else:
                        set_action_log(f"Failed to start lecture: {_resp.text}")
                except Exception as _exc:
                    set_action_log(f"Failed to start lecture: {_exc}")

        elif _act == "hub_stop_edit":
            _name = pending["assignment"]
            try:
                _client.post(
                    f"/stop-edit/{HUB_USER}/{_name}",
                    headers=_hub_headers,
                    timeout=10,
                )
            except Exception:
                pass
            set_action_log(f"Stopped editor for **{_name}**")

        _client.close()
        set_pending(None)
        set_refresh(lambda v: v + 1)
    return ()


# --- Dismiss button (own cell so it's stable across log changes) ---
@app.cell
def _(mo, set_action_log, set_report_path):
    def _dismiss(_):
        set_action_log("")
        set_report_path("")

    dismiss_btn = mo.ui.button(label="Dismiss", on_change=_dismiss)
    return (dismiss_btn,)


# --- Active editors panel ---
@app.cell
def _(
    CONFIG,
    HUB_USER,
    get_refresh,
    mo,
    set_pending,
):
    _ = get_refresh()
    active_editors_content = None

    import httpx as _httpx

    _hub_base = f"http://127.0.0.1:{CONFIG.hub_port}"
    _hub_headers = {"X-Remote-User": HUB_USER}

    try:
        _resp = _httpx.get(
            f"{_hub_base}/sessions",
            headers=_hub_headers,
            timeout=5,
        )
        _sessions = _resp.json() if _resp.status_code == 200 else []
    except Exception:
        _sessions = []

    if _sessions:
        _items = []
        for _s in _sessions:
            _name = _s["assignment"]
            _stype = _s.get("type", "assignment")
            _deep_url = f"run/{_name}" if _stype == "lecture" else f"edit/{_name}"
            _stop_btn = mo.ui.button(
                label="Stop",
                kind="danger",
                on_change=lambda _, n=_name: set_pending(
                    {"action": "hub_stop_edit", "assignment": n}
                ),
                tooltip=f"Stop editor for {_name}",
            )
            _items.append(
                mo.hstack(
                    [
                        mo.md(
                            f'**{_name}** — <a href="{_deep_url}" target="_blank">open</a>'
                        ),
                        _stop_btn,
                    ],
                    justify="start",
                    align="center",
                    gap=0.5,
                )
            )
        active_editors_content = mo.callout(
            mo.vstack([mo.md("**Active editors**")] + _items), kind="info"
        )
    return (active_editors_content,)


# --- Activity log ---
@app.cell
def _(active_editors_content, dismiss_btn, get_action_log, get_report_path, mo):
    log_text = get_action_log()
    report_path = get_report_path()

    _parts = []
    if active_editors_content:
        _parts.append(active_editors_content)
    if log_text:
        kind = (
            "danger"
            if "failed" in log_text.lower() or "error" in log_text.lower()
            else "info"
        )
        _parts.append(mo.callout(mo.md(log_text), kind=kind))
        if report_path:
            _parts.append(mo.md("*See report below.*"))
        _parts.append(dismiss_btn)
    if _parts:
        mo.output.replace(mo.vstack(_parts))
    else:
        mo.output.replace(mo.md(""))
    return ()


# --- Report preview (iframe, like grader grading tab) ---
@app.cell
def _(Path, get_report_path, mo):
    import base64 as _b64

    _report = get_report_path()
    if _report:
        if _report.startswith("/"):
            # URL path — use directly as iframe src
            mo.output.replace(
                mo.Html(
                    f'<iframe src="{_report}" '
                    f'style="width:100%; height:80vh; border:1px solid #ccc;"></iframe>'
                )
            )
        else:
            # Local file path — base64 encode
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
