import marimo

__generated_with = "0.20.0"
app = marimo.App(
    width="medium", app_title="mograder student", html_head_file="head.html"
)


@app.cell
def _():
    import os
    import re
    import subprocess as sp
    import sys
    from datetime import datetime, timezone
    from pathlib import Path

    import marimo as mo

    from mograder._brand import logo_html as brand_logo_html, version_html
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
        clear_cached_https_token,
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
    HUB_MODE = os.environ.get("MOGRADER_HUB_MODE") == "1"

    def _hub_username():
        """Read username from request scope (set by RemoteUserMiddleware)."""
        req = mo.app_meta().request
        user = req.user if req else None
        if user is None:
            return ""
        if isinstance(user, dict):
            return user.get("username", "")
        return getattr(user, "username", "")

    HUB_USER = _hub_username() if HUB_MODE else ""

    return (
        COURSE_DIR,
        CONFIG,
        HUB_MODE,
        HUB_USER,
        IS_HTTPS,
        MoodleAPIClient,
        MoodleAPIError,
        Path,
        brand_logo_html,
        version_html,
        build_transport,
        clear_cached_https_token,
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
    HUB_MODE,
    HUB_USER,
    IS_HTTPS,
    MoodleAPIClient,
    MoodleAPIError,
    brand_logo_html,
    version_html,
    build_transport,
    clear_cached_https_token,
    get_token,
    mo,
    save_cached_https_token,
    save_cached_token,
    set_action_log,
    set_token,
):
    moodle_url = CONFIG.moodle_url
    token_input = mo.ui.text(label="", value="")
    _app_title = CONFIG.title or "mograder student"
    _version = version_html()
    _heading = mo.Html(
        f'<div style="display:flex;align-items:center;gap:0.3em">{brand_logo_html()} <span style="font-size:2em;font-weight:bold">{_app_title}</span> {_version}</div>'
    )

    # Hub mode: user is already authenticated via SSO — skip login
    if HUB_MODE:
        _rel_dir = COURSE_DIR / CONFIG.hub_release_dir
        https_assignments = ()
        if _rel_dir.is_dir():
            https_assignments = tuple(
                {
                    "name": d.name,
                    "id": d.name,
                    "files": [
                        {"name": f.name, "url": ""} for f in sorted(d.glob("*.py"))
                    ],
                }
                for d in sorted(_rel_dir.iterdir())
                if d.is_dir() and (d / f"{d.name}.py").is_file()
            )
        mo.output.replace(
            mo.hstack(
                [_heading, mo.md(f"Logged in as **{HUB_USER}**")],
                justify="space-between",
                align="center",
            )
        )
    else:
        # Auto-sync assignments from Moodle when a token is available
        _assignments_cfg = CONFIG.assignments or CONFIG.moodle_assignments
        if not IS_HTTPS and moodle_url and CONFIG.moodle_course_id and get_token():
            try:
                from mograder.moodle_api import sync_assignments as _sync_assignments

                _sync_client = MoodleAPIClient(moodle_url, get_token())
                _synced = _sync_assignments(_sync_client, CONFIG.moodle_course_id)
                if _synced:
                    # Update config in memory for this session
                    _assignments_cfg = tuple(_synced)
                    # Persist to mograder.toml
                    import tomllib as _tomllib

                    from mograder.config import write_toml as _write_toml

                    _toml_path = COURSE_DIR / "mograder.toml"
                    if _toml_path.is_file():
                        with open(_toml_path, "rb") as _f:
                            _toml_data = _tomllib.load(_f)
                    else:
                        _toml_data = {}
                    _moodle_section = _toml_data.get("moodle", {})
                    _moodle_section["assignments"] = list(_synced)
                    _toml_data["moodle"] = _moodle_section
                    _toml_data["assignments"] = list(_synced)
                    _write_toml(_toml_path, _toml_data)
            except Exception:
                pass  # Sync is best-effort; stale config still works

        https_assignments = ()
        _https_needs_login = False
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
                import requests as _requests

                _is_auth_error = (
                    isinstance(_exc, _requests.HTTPError)
                    and _exc.response is not None
                    and _exc.response.status_code in (401, 403)
                )
                if _is_auth_error:
                    # Auth required — clear stale token and show login UI
                    clear_cached_https_token()
                    set_token("")
                    _https_needs_login = True
                    if get_token():
                        set_action_log("Session expired — please log in again.")
                else:
                    mo.output.replace(
                        mo.callout(
                            mo.md(f"Failed to fetch assignments from server: {_exc}"),
                            kind="danger",
                        )
                    )

        _has_assignments = bool(_assignments_cfg or https_assignments)

        if IS_HTTPS:
            if not _https_needs_login:
                _server_info = mo.Html(
                    f'<div style="font-size:0.85em"><b>Local:</b> <code>{COURSE_DIR}</code>'
                    f"<br><b>Remote:</b> <code>{CONFIG.https_url}</code></div>"
                )
                mo.output.replace(
                    mo.hstack(
                        [_heading, _server_info],
                        justify="space-between",
                        align="center",
                    )
                )
            else:
                import os as _os

                detected_user = _os.environ.get("GITHUB_USER") or _os.environ.get(
                    "USER", ""
                )
                username_input = mo.ui.text(
                    label="Username",
                    value=detected_user,
                    disabled=bool(detected_user),
                    full_width=True,
                )
                enrollment_input = mo.ui.text(
                    label="Enrollment code", kind="password", full_width=True
                )

                def handle_https_register(_):
                    user = detected_user or username_input.value.strip()
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
                            _heading,
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
            _moodle_info = mo.Html(
                f'<div style="font-size:0.85em"><b>Local:</b> <code>{COURSE_DIR}</code>'
                + (
                    f"<br><b>Remote:</b> <code>{moodle_url}</code>"
                    if moodle_url
                    else ""
                )
                + "</div>"
            )
            mo.output.replace(
                mo.hstack(
                    [_heading, _moodle_info],
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
                        _heading,
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
    HUB_MODE,
    HUB_USER,
    IS_HTTPS,
    Path,
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

    if HUB_MODE:
        _ready = bool(assignments_cfg)
    else:
        _ready = bool(assignments_cfg) and (IS_HTTPS or (moodle_url and token))
    if not _ready:
        mo.output.replace(mo.md(""))
    elif HUB_MODE:
        # Hub mode: status from hub notebooks dir, hub-specific actions
        _nb_dir = Path(COURSE_DIR / CONFIG.hub_notebooks_dir)

        all_buttons = {}
        rows = []

        for i, a in enumerate(assignments_cfg):
            _slug = a.get("dir") or a["name"]
            _display = a.get("name", _slug)
            _nb_path = _nb_dir / HUB_USER / _slug / f"{_slug}.py"
            _has_file = _nb_path.exists()

            status = "uploaded" if _has_file else "not started"
            check_summary = "---"

            btn_keys = []

            if not _has_file:
                key = f"{i}_download"
                all_buttons[key] = mo.ui.button(
                    label="Download",
                    on_change=lambda _, n=_slug: set_pending(
                        {"action": "hub_download", "assignment": n}
                    ),
                )
                btn_keys.append(key)

            if _has_file:
                key = f"{i}_edit"
                all_buttons[key] = mo.ui.button(
                    label="Edit",
                    on_change=lambda _, n=_slug: set_pending(
                        {"action": "hub_edit", "assignment": n}
                    ),
                )
                btn_keys.append(key)

                key = f"{i}_validate"
                all_buttons[key] = mo.ui.button(
                    label="Validate",
                    on_change=lambda _, n=_slug: set_pending(
                        {"action": "hub_validate", "assignment": n}
                    ),
                )
                btn_keys.append(key)

                key = f"{i}_export"
                all_buttons[key] = mo.ui.button(
                    label="Export",
                    on_change=lambda _, n=_slug: set_pending(
                        {"action": "hub_export", "assignment": n}
                    ),
                )
                btn_keys.append(key)

                key = f"{i}_reset"
                all_buttons[key] = mo.ui.button(
                    label="Reset",
                    on_change=lambda _, n=_slug: set_pending(
                        {"action": "hub_reset", "assignment": n}
                    ),
                )
                btn_keys.append(key)

            rows.append(
                {
                    "Assignment": _display,
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
    HUB_MODE,
    HUB_USER,
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

        # Hub-mode actions: call hub API via httpx on localhost
        if HUB_MODE and _act.startswith("hub_"):
            import httpx as _httpx

            _hub_base = f"http://127.0.0.1:{CONFIG.hub_port}"
            _hub_headers = {"X-Remote-User": HUB_USER}

            if _act == "hub_download":
                _name = pending["assignment"]
                try:
                    _resp = _httpx.get(
                        f"{_hub_base}/release/{_name}/{_name}.py",
                        headers=_hub_headers,
                        timeout=30,
                    )
                    if _resp.status_code == 200:
                        _up = _httpx.post(
                            f"{_hub_base}/upload/{HUB_USER}/{_name}",
                            headers=_hub_headers,
                            files={
                                "file": (f"{_name}.py", _resp.content, "text/x-python")
                            },
                            timeout=30,
                        )
                        if _up.status_code == 200:
                            set_action_log(f"Downloaded **{_name}**")
                        else:
                            set_action_log(f"Upload failed: {_up.text}")
                    else:
                        set_action_log(f"Download failed: {_resp.text}")
                except Exception as _exc:
                    set_action_log(f"Download failed: {_exc}")

            elif _act == "hub_edit":
                _name = pending["assignment"]
                with mo.status.spinner(
                    title=f"Starting editor for {_name}...",
                    remove_on_exit=True,
                ):
                    try:
                        _resp = _httpx.post(
                            f"{_hub_base}/start-edit/{HUB_USER}/{_name}",
                            headers=_hub_headers,
                            timeout=120,
                        )
                        if _resp.status_code == 200:
                            _data = _resp.json()
                            # Strip leading / so browser resolves relative to
                            # the current page (works behind reverse proxies)
                            _url = _data["url"].lstrip("/")
                            set_action_log(
                                f"Editing **{_name}** — "
                                f'<a href="{_url}" target="_blank">open editor</a>'
                            )
                        else:
                            set_action_log(f"Failed to start editor: {_resp.text}")
                    except Exception as _exc:
                        set_action_log(f"Failed to start editor: {_exc}")

            elif _act == "hub_validate":
                _name = pending["assignment"]
                with mo.status.spinner(
                    title=f"Validating {_name}...",
                    remove_on_exit=True,
                ):
                    try:
                        _resp = _httpx.post(
                            f"{_hub_base}/validate/{HUB_USER}/{_name}",
                            headers=_hub_headers,
                            timeout=300,
                        )
                        if _resp.status_code == 200:
                            _data = _resp.json()
                            _checks = _data["checks"]
                            _passed = sum(
                                1 for c in _checks if c["status"] == "success"
                            )
                            set_action_log(
                                f"Validation of **{_name}**: "
                                f"{_passed}/{len(_checks)} passed"
                            )
                        else:
                            set_action_log(f"Validation failed: {_resp.text}")
                    except Exception as _exc:
                        set_action_log(f"Validation failed: {_exc}")

            elif _act == "hub_export":
                _name = pending["assignment"]
                _url = f"export/{HUB_USER}/{_name}"
                set_action_log(
                    f'Export **{_name}**: <a href="{_url}" target="_blank">download</a>'
                )

            elif _act == "hub_reset":
                _name = pending["assignment"]
                try:
                    _resp = _httpx.post(
                        f"{_hub_base}/reset/{HUB_USER}/{_name}",
                        headers=_hub_headers,
                        timeout=30,
                    )
                    if _resp.status_code == 200:
                        set_action_log(f"Reset **{_name}**")
                    else:
                        set_action_log(f"Reset failed: {_resp.text}")
                except Exception as _exc:
                    set_action_log(f"Reset failed: {_exc}")

            elif _act == "hub_stop_edit":
                _name = pending["assignment"]
                try:
                    _httpx.post(
                        f"{_hub_base}/stop-edit/{HUB_USER}/{_name}",
                        headers=_hub_headers,
                        timeout=10,
                    )
                except Exception:
                    pass
                set_action_log(f"Stopped editor for **{_name}**")

            set_pending(None)
            set_refresh(lambda v: v + 1)
        else:
            # Non-hub mode: Moodle/HTTPS transport
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
                _name = _assign["name"]
                _all_files = _assign.get("files", [])
                if not _all_files:
                    set_action_log(f"No files attached to **{_name}**")
                else:
                    try:
                        from mograder.transport_commands import (
                            download_assignment_files,
                        )

                        # Remap {"name": ..} to {"filename": ..} for shared helper
                        _files = [
                            {
                                "filename": f.get("filename", f.get("name")),
                                "url": f["url"],
                            }
                            for f in _all_files
                        ]
                        _dl_transport = _transport or _client
                        download_assignment_files(_dl_transport, _files, _adir, _name)
                        set_action_log(f"Downloaded **{_name}** to `{_slug}/`")
                    except Exception as _exc:
                        set_action_log(f"Download failed for **{_name}**: {_exc}")
                set_refresh(lambda v: v + 1)

            elif _act == "edit":
                _path = pending["path"]
                _name = pending["name"]
                import os as _os

                _is_remote = bool(
                    _os.environ.get("CODESPACES")
                    or _os.environ.get("SSH_CONNECTION")
                    or CONFIG.headless_edit
                )
                if _is_remote:
                    from mograder.edit_sessions import (
                        spawn_headless_edit,
                        rewrite_codespaces_url,
                    )

                    with mo.status.spinner(
                        title=f"Starting editor for {_name}...",
                        remove_on_exit=True,
                    ):
                        try:
                            _hs = spawn_headless_edit(
                                _path,
                                host="0.0.0.0"
                                if _os.environ.get("CODESPACES")
                                else "127.0.0.1",
                            )
                            if _os.environ.get("CODESPACES"):
                                _url = rewrite_codespaces_url(_hs.url)
                            else:
                                _url = _hs.url
                                if _os.environ.get("TAURI"):
                                    # Open in system browser — Tauri webview
                                    # silently blocks target=_blank links
                                    import webbrowser as _wb

                                    _wb.open(_url)
                            set_action_log(
                                f"Opened **{_name}** for editing: [{_url}]({_url})"
                            )
                        except TimeoutError:
                            set_action_log(
                                f"Opened **{_name}** for editing (could not detect URL)"
                            )
                else:
                    from mograder.edit_sessions import spawn_headless_edit

                    with mo.status.spinner(
                        title=f"Starting editor for {_name}...",
                        remove_on_exit=True,
                    ):
                        try:
                            _hs = spawn_headless_edit(
                                _path, token=False, spawn_timeout=120
                            )
                            import webbrowser as _wb

                            _wb.open(_hs.url)
                            set_action_log(
                                f"Opened **{_name}** for editing: [{_hs.url}]({_hs.url})"
                            )
                        except TimeoutError:
                            set_action_log(
                                f"Failed to start editor for **{_name}** (timed out)"
                            )

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
                        _passed = sum(
                            1 for c in _result.checks if c.status == "success"
                        )
                        _total = len(_result.checks)
                        if not _result.export_ok:
                            _msg = f"Validation of **{_name}** failed: {_result.export_error}"
                        elif _total == 0:
                            _msg = (
                                f"Validation of **{_name}** complete (no checks found)"
                            )
                        else:
                            _msg = (
                                f"Validation of **{_name}** complete: "
                                f"{_passed}/{_total} checks passed"
                            )
                        if _result.cell_errors > 0:
                            _msg += f" ({_result.cell_errors} cell error(s))"
                        # Check cell hash integrity
                        from mograder.integrity import validate_cell_hashes

                        _hw = validate_cell_hashes(_path.read_text())
                        if _hw:
                            _msg += (
                                "\n\n**Warning:** modified non-solution cells detected:"
                            )
                            for _w in _hw:
                                _msg += f"\n- Cell {_w.index + 1}: `{_w.snippet}`"
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
                    save_submission_record(
                        COURSE_DIR, _path.name, _path.stat().st_mtime
                    )
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


# --- Active editors panel (hub mode) ---
@app.cell
def _(
    CONFIG,
    HUB_MODE,
    HUB_USER,
    get_refresh,
    mo,
    set_action_log,
    set_pending,
    set_refresh,
):
    _ = get_refresh()
    active_editors_content = None

    if HUB_MODE:
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
                _url = _s["url"]
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
                                f"**{_name}** — "
                                f'<a href="{_url}" target="_blank">open</a>'
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
