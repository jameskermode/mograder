import marimo

__generated_with = "0.20.0"
app = marimo.App(
    width="medium",
    app_title="mograder hub",
    html_head_file="../head.html",
    css_file="dashboard.css",
)


@app.cell
def _():
    from pathlib import Path

    import marimo as mo

    from mograder._brand import logo_html as brand_logo_html, version_html
    from mograder.student.common import (
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

    def _hub_user_attr(attr, default=None):
        req = mo.app_meta().request
        user = req.user if req else None
        if isinstance(user, dict):
            return user.get(attr, default)
        return getattr(user, attr, default) if user is not None else default

    from mograder.core.auth import is_instructor as _is_token_instructor
    from mograder.core.view_as import as_of_timestamp as _as_of_ts

    # Role as the hub's auth middleware set it (SSO instructors included); an
    # instructor "viewing as student" has is_instructor False, view_as set and
    # optionally as_of (scheduled visibility evaluated at that moment)
    HUB_IS_INSTRUCTOR = bool(
        _hub_user_attr("is_instructor", _is_token_instructor(HUB_USER))
    )
    HUB_REAL_INSTRUCTOR = bool(_hub_user_attr("real_is_instructor", HUB_IS_INSTRUCTOR))
    HUB_VIEW_AS = _hub_user_attr("view_as", "") or ""
    HUB_AS_OF = _hub_user_attr("as_of", None)
    HUB_AS_OF_TS = _as_of_ts({"as_of": HUB_AS_OF})

    def actions_cell_style(_row_id, column, _value):
        """Table cell style: the Actions column is as wide as its widest row
        (by default the table squeezes it, clipping or wrapping the buttons)."""
        if column == "Actions":
            return {
                "minWidth": "max-content",
                "maxWidth": "none",
                "whiteSpace": "nowrap",
            }
        return {}

    def link_button(label, href, tooltip=""):
        """A link styled as a button, opening a new tab.

        Opening a notebook is a plain link to the hub's deep link (/run/<name>,
        /edit/<name>), whose page starts the session and redirects: a tab
        opened by the user's own click is not stopped by pop-up blockers,
        unlike one opened by code after a server round trip.
        """
        import html as _html

        # styled in dashboard.css, shared with the real buttons
        return mo.Html(
            f'<a class="mograder-btn" href="{_html.escape(href)}" target="_blank" '
            f'rel="noopener" title="{_html.escape(tooltip)}">{_html.escape(label)}</a>'
        )

    return (
        COURSE_DIR,
        CONFIG,
        HUB_AS_OF,
        HUB_AS_OF_TS,
        HUB_IS_INSTRUCTOR,
        HUB_REAL_INSTRUCTOR,
        HUB_USER,
        HUB_VIEW_AS,
        Path,
        actions_cell_style,
        brand_logo_html,
        hub_submit,
        hub_validate,
        link_button,
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
    # assignment awaiting confirmation of "Get latest" (replaces the copy)
    get_confirm, set_confirm = mo.state(None)
    # sessions seen at the last poll: tables are rebuilt only when this changes
    get_sessions_seen, set_sessions_seen = mo.state(None)

    return (
        get_action_log,
        get_confirm,
        get_pending,
        get_sessions_seen,
        get_refresh,
        get_report_path,
        set_action_log,
        set_confirm,
        set_pending,
        set_refresh,
        set_report_path,
        set_sessions_seen,
    )


# --- Header ---
@app.cell
def _(
    COURSE_DIR,
    CONFIG,
    HUB_AS_OF_TS,
    HUB_IS_INSTRUCTOR,
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

    from mograder.hub.storage import StorageManager as _StorageManager

    hub_storage = _StorageManager(COURSE_DIR / CONFIG.hub_notebooks_dir, _rel_dir)
    _instructor = HUB_IS_INSTRUCTOR

    def hub_item_open(name, started=False):
        """Scheduled visibility: students don't see hidden or not-yet-open
        items, except an assignment they already have a copy of."""
        if _instructor or started:
            return True
        return hub_storage.visibility(name, now=HUB_AS_OF_TS)[0]

    if _rel_dir.is_dir():
        import json as _json

        _storage = hub_storage

        for d in sorted(_rel_dir.iterdir()):
            if not d.is_dir() or not (d / f"{d.name}.py").is_file():
                continue
            _manifest = d / "files.json"
            _type = "assignment"
            if _manifest.is_file():
                try:
                    _type = _json.loads(_manifest.read_text(encoding="utf-8")).get(
                        "type", "assignment"
                    )
                except Exception:
                    pass
            # Scheduled visibility: students do not see hidden or not-yet-open
            # items (an assignment they already have a copy of stays listed)
            _open, _ = _storage.visibility(d.name, now=HUB_AS_OF_TS)
            if not _open and not _instructor:
                try:
                    _started = _storage.assignment_path(HUB_USER, d.name).exists()
                except ValueError:
                    _started = False
                if _type == "lecture" or not _started:
                    continue
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
    return (https_assignments, hub_item_open, hub_lectures, hub_storage)


# --- View as student (instructors): test what students see, optionally as of
# a date, so the release schedule can be checked before term ---
@app.cell
def _(mo):
    import datetime as _dt

    # shown in the view-as bar below (instructors only)
    view_as_date = mo.ui.date(value=_dt.date.today().isoformat(), label="as of")
    return (view_as_date,)


@app.cell
def _(HUB_AS_OF, HUB_REAL_INSTRUCTOR, HUB_VIEW_AS, mo, view_as_date):
    import html as _html_va
    from datetime import datetime as _datetime

    def _switch_link(label, href):
        # same tab (target _top): the switch reloads the dashboard
        return mo.Html(
            f'<a class="mograder-btn" href="{_html_va.escape(href)}" '
            f'target="_top">{_html_va.escape(label)}</a>'
        )

    if HUB_VIEW_AS:
        _when = (
            _datetime.fromisoformat(HUB_AS_OF).strftime("%a %d %b %Y, %H:%M")
            if HUB_AS_OF
            else "now"
        )
        _bar = mo.callout(
            mo.hstack(
                [
                    mo.md(
                        f"**Viewing as {HUB_VIEW_AS}**, schedule as of **{_when}**: "
                        "you see and can open only what a student could then."
                    ),
                    _switch_link("Back to instructor view", "view-as?role="),
                ],
                justify="space-between",
                align="center",
            ),
            kind="warn",
        )
    elif HUB_REAL_INSTRUCTOR:
        _d = view_as_date.value
        _bar = mo.hstack(
            [
                mo.md("**Instructor**: check what students see:"),
                _switch_link("View as student now", "view-as?role=student"),
                view_as_date,
                _switch_link(
                    "View as student then",
                    f"view-as?role=student&as_of={_d.isoformat()}T09:00",
                ),
            ],
            justify="start",
            align="center",
            gap=0.5,
        )
    else:
        _bar = None
    _bar
    return


# The activity panel (active sessions, messages, report) sits at the top,
# above the tables, so it is visible without scrolling.
# --- Dismiss button (own cell so it's stable across log changes) ---
@app.cell
def _(mo, set_action_log, set_report_path):
    def _dismiss(_):
        set_action_log("")
        set_report_path("")

    dismiss_btn = mo.ui.button(label="Dismiss", on_change=_dismiss)
    return (dismiss_btn,)


# --- Auto-refresh: notebooks open in new tabs (plain links), so the dashboard
# polls for sessions instead of learning about them from a button click ---
@app.cell
def _(mo):
    editors_ticker = mo.ui.refresh(
        options=["5s", "15s", "1m"], default_interval="5s", label="Auto-refresh"
    )
    return (editors_ticker,)


# --- Active editors panel ---
@app.cell
def _(
    CONFIG,
    HUB_USER,
    editors_ticker,
    get_refresh,
    get_sessions_seen,
    mo,
    set_pending,
    set_refresh,
    set_sessions_seen,
):
    _ = get_refresh(), editors_ticker.value
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

    # A session opened or closed since the last poll (e.g. a notebook opened
    # from a link): rebuild the tables so status and "Your copy" are current
    _seen = tuple(
        sorted((_s["assignment"], _s.get("mode", "edit")) for _s in _sessions)
    )
    if _seen != get_sessions_seen():
        if get_sessions_seen() is not None:
            set_refresh(lambda v: v + 1)
        set_sessions_seen(_seen)

    if _sessions:
        _items = []
        for _s in _sessions:
            _name = _s["assignment"]
            _mode = _s.get("mode", "edit")
            _deep_url = f"{_mode}/{_name}"
            _stop_btn = mo.ui.button(
                label="Stop",
                kind="danger",
                on_change=lambda _, n=_name, m=_mode: set_pending(
                    {"action": "hub_stop_edit", "assignment": n, "mode": m}
                ),
                tooltip=f"Stop this session of {_name}",
            )
            _what = "viewing" if _mode == "run" else "editing your copy"
            _items.append(
                mo.hstack(
                    [
                        mo.md(
                            f"**{_name}** ({_what}) — "
                            f'<a href="{_deep_url}" target="_blank">open</a>'
                        ),
                        _stop_btn,
                    ],
                    justify="start",
                    align="center",
                    gap=0.5,
                )
            )
        active_editors_content = mo.callout(
            mo.vstack([mo.md("**Active sessions**")] + _items), kind="info"
        )
    return (active_editors_content,)


# --- Confirmation for "Get latest" on an assignment ---
@app.cell
def _(get_confirm, mo, set_action_log, set_confirm, set_pending):
    _name = get_confirm()
    confirm_content = None
    if _name:

        def _cancel(_):
            set_confirm(None)
            set_action_log("")

        confirm_content = mo.hstack(
            [
                mo.ui.button(
                    label="Replace my copy",
                    kind="danger",
                    on_change=lambda _, n=_name: set_pending(
                        {"action": "hub_latest", "name": n}
                    ),
                ),
                mo.ui.button(label="Cancel", on_change=_cancel),
            ],
            justify="start",
            gap=0.5,
        )
    return (confirm_content,)


# --- Activity log ---
@app.cell
def _(
    active_editors_content,
    confirm_content,
    dismiss_btn,
    editors_ticker,
    get_action_log,
    get_report_path,
    mo,
):
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
        _parts.append(confirm_content if confirm_content else dismiss_btn)
    _parts.append(mo.hstack([editors_ticker], justify="end"))
    mo.output.replace(mo.vstack(_parts))
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


# --- Assignments table ---
# Buttons only call set_pending({...}) — actual work is in the execution cell.
@app.cell
def _(
    COURSE_DIR,
    CONFIG,
    HUB_USER,
    Path,
    get_refresh,
    hub_item_open,
    hub_storage,
    actions_cell_style,
    https_assignments,
    link_button,
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
            if not hub_item_open(_slug, started=_has_file):
                continue

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
                if hub_storage.release_updated(HUB_USER, _slug):
                    _status += " · update available"
            _check_summary = "---"

            _btn_keys = []
            # Open: the deep link fetches the student's copy on first use and
            # reopens it afterwards (never overwriting it)
            _open = link_button(
                "Open",
                f"edit/{_slug}",
                "Open your copy in a new tab"
                + ("" if _has_file else " (fetched the first time)"),
            )

            if _has_file:
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

                # Replaces the copy (archived first): asks for confirmation
                _key = f"{_i}_latest"
                _all_buttons[_key] = mo.ui.button(
                    label="Get latest",
                    tooltip="Replace your copy with the latest version "
                    "(your current copy is kept as a backup)",
                    on_change=lambda _, n=_slug: set_pending(
                        {"action": "hub_latest_ask", "name": n}
                    ),
                )
                _btn_keys.append(_key)

            _rows.append(
                {
                    "Assignment": _display,
                    "Status": _status,
                    "Checks": _check_summary,
                    "btn_keys": _btn_keys,
                    "open": _open,
                }
            )

        buttons = mo.ui.dictionary(_all_buttons)

        _display_rows = []
        for _row in _rows:
            _keys = _row.pop("btn_keys")
            _btns = [_row.pop("open")] + [buttons[k] for k in _keys]
            _row["Actions"] = mo.hstack(_btns, gap=0.5, justify="start", align="center")
            _display_rows.append(_row)

        if _display_rows:
            _table = mo.ui.table(
                _display_rows, selection=None, style_cell=actions_cell_style
            )
            mo.output.replace(mo.vstack([mo.md("### Assignments"), _table]))

    return (buttons,)


# --- Lectures table ---
@app.cell
def _(
    HUB_USER,
    actions_cell_style,
    get_refresh,
    hub_lectures,
    hub_storage,
    link_button,
    mo,
    set_pending,
):
    _ = get_refresh()
    if not hub_lectures:
        mo.output.replace(mo.md(""))
    else:
        _all_buttons = {}
        for _i, _lec in enumerate(hub_lectures):
            _name = _lec["name"]
            if hub_storage.assignment_path(HUB_USER, _name).exists():
                _all_buttons[f"lec_{_i}_latest"] = mo.ui.button(
                    label="Get latest",
                    tooltip="Replace your copy with the latest version "
                    "(your current copy is kept as a backup)",
                    on_change=lambda _, n=_name: set_pending(
                        {"action": "hub_latest", "name": n}
                    ),
                )
        _lec_buttons = mo.ui.dictionary(_all_buttons)
        _rows = []
        for _i, _lec in enumerate(hub_lectures):
            _name = _lec["name"]
            _links = [
                link_button("Run", f"run/{_name}", "View the lecture in a new tab"),
                # the student's own copy, to change settings and explore
                link_button("Edit", f"edit/{_name}", "Edit your own copy in a new tab"),
            ]
            _keys = [f"lec_{_i}_latest"]
            if not hub_storage.assignment_path(HUB_USER, _name).exists():
                _copy = "—"
            elif hub_storage.release_updated(HUB_USER, _name):
                _copy = "update available"
            else:
                _copy = "up to date"
            _rows.append(
                {
                    "Lecture": _name,
                    "Your copy": _copy,
                    "Actions": mo.hstack(
                        _links + [_lec_buttons[k] for k in _keys if k in _lec_buttons],
                        gap=0.5,
                        justify="start",
                        align="center",
                    ),
                }
            )
        _table = mo.ui.table(_rows, selection=None, style_cell=actions_cell_style)
        mo.output.replace(mo.vstack([mo.md("### Lectures"), _table]))
    return ()


# --- Execution cell: reads get_pending() and does the actual work ---
@app.cell
def _(
    CONFIG,
    HUB_USER,
    get_pending,
    hub_submit,
    hub_validate,
    mo,
    set_action_log,
    set_confirm,
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

        if _act == "hub_validate":
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

        elif _act == "hub_latest_ask":
            # assignments: confirm first (the copy may be submitted work)
            set_confirm(pending["name"])
            set_action_log(
                f"Replace your copy of **{pending['name']}** with the latest "
                "version? Your current copy will be kept as a backup in the "
                "same folder."
            )

        elif _act == "hub_latest":
            _name = pending["name"]
            set_confirm(None)
            try:
                _resp = _client.post(
                    f"/reset/{HUB_USER}/{_name}",
                    headers=_hub_headers,
                    timeout=60,
                )
                if _resp.status_code == 200:
                    _archive = _resp.json().get("archive")
                    _kept = (
                        f" Your previous copy is saved as `{_archive}`."
                        if _archive
                        else ""
                    )
                    set_action_log(f"Fetched the latest **{_name}**.{_kept}")
                else:
                    set_action_log(f"Failed to fetch {_name}: {_resp.text}")
            except Exception as _exc:
                set_action_log(f"Failed to fetch {_name}: {_exc}")

        elif _act == "hub_stop_edit":
            _name = pending["assignment"]
            try:
                _client.post(
                    f"/stop-edit/{HUB_USER}/{_name}",
                    params={"mode": pending.get("mode", "edit")},
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


if __name__ == "__main__":
    app.run()
