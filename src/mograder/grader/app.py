import marimo

__generated_with = "0.20.0"
app = marimo.App(width="medium", app_title="mograder", html_head_file="head.html")


@app.cell
def _():
    import io
    import os
    import subprocess as sp
    import sys
    import zipfile
    from pathlib import Path

    import marimo as mo

    import altair as alt

    from mograder._brand import logo_html as brand_logo_html, version_html
    from mograder.core.config import load_config
    from mograder.grader.scanner import DirNames
    from mograder.grading.gradebook import Gradebook
    from mograder.transport.moodle_api import load_cached_token

    import socket

    COURSE_DIR = Path(os.environ.get("MOGRADER_COURSE_DIR", ".")).resolve()
    # Resolve mograder binary from same venv as running Python
    MOGRADER_BIN = str(Path(sys.executable).parent / "mograder")
    MOGRADER_CONFIG = load_config(COURSE_DIR)
    DIR_NAMES = DirNames(
        source=MOGRADER_CONFIG.source_dir,
        release=MOGRADER_CONFIG.release_dir,
        submitted=MOGRADER_CONFIG.submitted_dir,
        autograded=MOGRADER_CONFIG.autograded_dir,
        feedback=MOGRADER_CONFIG.feedback_dir,
        import_dir=MOGRADER_CONFIG.import_dir,
    )

    _gb_path = COURSE_DIR / MOGRADER_CONFIG.gradebook
    GRADEBOOK = Gradebook(_gb_path) if _gb_path.is_file() else None

    TRANSPORT_TYPE = MOGRADER_CONFIG.transport  # "moodle" or "https"
    TRANSPORT_READY = False
    if TRANSPORT_TYPE == "moodle":
        if MOGRADER_CONFIG.moodle_url and MOGRADER_CONFIG.moodle_course_id:
            _cached = load_cached_token(MOGRADER_CONFIG.moodle_url)
            if _cached:
                TRANSPORT_READY = True
    elif TRANSPORT_TYPE == "https":
        if MOGRADER_CONFIG.https_url:
            TRANSPORT_READY = True  # HTTPS transport doesn't require pre-auth

    # Map local directory names to transport assignment names.
    # Each [[assignments]] entry can have a "dir" key (e.g. "A1") used for
    # substring matching against local directory names (e.g. "ES98E-A1-Intro-to-SciML").
    def match_transport_assignment(
        local_name: str,
        _assignments=MOGRADER_CONFIG.assignments or MOGRADER_CONFIG.moodle_assignments,
    ) -> str | None:
        """Return the transport assignment name for a local dir name, or None."""
        for a in _assignments:
            d = a.get("dir")
            if d and d in local_name:
                return a["name"]
            if a["name"] == local_name:
                return a["name"]
        return None

    def moodle_grading_url(local_name: str) -> str | None:
        """Return the Moodle grading page URL for a local assignment, or None."""
        _assignments = MOGRADER_CONFIG.assignments or MOGRADER_CONFIG.moodle_assignments
        _base = MOGRADER_CONFIG.moodle_url
        if not _base:
            return None
        for a in _assignments:
            d = a.get("dir")
            cmid = a.get("cmid")
            if cmid and ((d and d in local_name) or a["name"] == local_name):
                return (
                    f"{_base.rstrip('/')}/mod/assign/view.php?id={cmid}&action=grading"
                )
        return None

    def moodle_upload_url(local_name: str) -> str | None:
        """Return the Moodle assignment edit page URL (for uploading files)."""
        _assignments = MOGRADER_CONFIG.assignments or MOGRADER_CONFIG.moodle_assignments
        _base = MOGRADER_CONFIG.moodle_url
        if not _base:
            return None
        for a in _assignments:
            d = a.get("dir")
            cmid = a.get("cmid")
            if cmid and ((d and d in local_name) or a["name"] == local_name):
                return f"{_base.rstrip('/')}/course/modedit.php?update={cmid}"
        return None

    def _get_user_attr(attr: str, default=None):
        """Read an attribute from the request user (dict or object)."""
        req = mo.app_meta().request
        user = req.user if req else None
        if user is None:
            return default
        if isinstance(user, dict):
            return user.get(attr, default)
        return getattr(user, attr, default)

    def is_instructor() -> bool:
        """Check if the current user is an instructor.

        Reads user identity from mo.app_meta().request.user, which is
        populated by TrustedProxyAuth middleware in ASGI mode.
        Defaults to True for local/non-ASGI use (no middleware).
        """
        return _get_user_attr("is_instructor", True)

    def get_user_display() -> str:
        """Return 'username@host' for display in the navbar."""
        username = _get_user_attr("username", "")
        if not username or username == "user":
            username = os.environ.get("USER", "local")
        hostname = socket.gethostname().split(".")[0]
        # Skip ugly serial-number hostnames (e.g. "20-G3-033585-24")
        if hostname.isalpha():
            return f"{username}@{hostname}"
        return username

    return (
        COURSE_DIR,
        DIR_NAMES,
        GRADEBOOK,
        Gradebook,
        MOGRADER_BIN,
        MOGRADER_CONFIG,
        TRANSPORT_READY,
        TRANSPORT_TYPE,
        Path,
        brand_logo_html,
        version_html,
        match_transport_assignment,
        moodle_grading_url,
        moodle_upload_url,
        get_user_display,
        is_instructor,
        alt,
        io,
        mo,
        os,
        sp,
        sys,
        zipfile,
    )


@app.cell
def _(mo):
    get_selected, set_selected = mo.state("")
    get_action_log, set_action_log = mo.state("")
    get_pending_action, set_pending_action = mo.state(None)
    get_grading_index, set_grading_index = mo.state(0)
    get_data_version, set_data_version = mo.state(0)
    get_grading_inputs, set_grading_inputs = mo.state(None)
    # Track active headless edit sessions: {path_str: {session_id, url}}
    get_active_editors, set_active_editors = mo.state({})
    return (
        get_action_log,
        get_active_editors,
        get_data_version,
        get_grading_index,
        get_grading_inputs,
        get_pending_action,
        get_selected,
        set_action_log,
        set_active_editors,
        set_data_version,
        set_grading_index,
        set_grading_inputs,
        set_pending_action,
        set_selected,
    )


@app.cell
def _(mo):
    refresh_btn = mo.ui.button(label="Refresh")
    return (refresh_btn,)


@app.cell
def _(COURSE_DIR, DIR_NAMES, GRADEBOOK, get_data_version, refresh_btn):
    from mograder.grader.scanner import scan_course

    _refresh = refresh_btn.value, get_data_version()
    assignments = scan_course(COURSE_DIR, dir_names=DIR_NAMES, gradebook=GRADEBOOK)
    return assignments, scan_course


@app.cell
def _(assignments, get_selected, mo, set_grading_index, set_selected):
    _options = {a.name: a.name for a in assignments}
    _current = get_selected()
    # Clear stale state if the previously selected assignment is no longer available
    if _current and _current not in _options:
        set_selected("")
        _current = ""

    def _on_assignment_change(val):
        set_selected(val or "")
        set_grading_index(0)

    assignment_dropdown = mo.ui.dropdown(
        options=_options,
        value=_current if _current else None,
        label="Assignment",
        on_change=_on_assignment_change,
    )
    # Second independent dropdown bound to the same state for the Grading tab
    assignment_dropdown_grading = mo.ui.dropdown(
        options=_options,
        value=_current if _current else None,
        label="Assignment",
        on_change=_on_assignment_change,
    )
    return assignment_dropdown, assignment_dropdown_grading


@app.cell
def _(
    COURSE_DIR,
    DIR_NAMES,
    MOGRADER_CONFIG,
    TRANSPORT_READY,
    TRANSPORT_TYPE,
    match_transport_assignment,
    moodle_grading_url,
    moodle_upload_url,
    assignments,
    io,
    is_instructor,
    mo,
    set_action_log,
    set_pending_action,
    sp,
    sys,
    zipfile,
):
    def _open_marimo(mode, path, label):
        if MOGRADER_CONFIG.headless_edit:
            set_pending_action({"action": "edit", "path": str(path), "label": label})
        else:
            sp.Popen([sys.executable, "-m", "marimo", mode, "--sandbox", str(path)])
            set_action_log(f"Opened **{mode}** for `{label}`")

    # --- build per-assignment buttons ---
    _src_btns_list = []
    _MOODLE_ICON_B64 = "iVBORw0KGgoAAAANSUhEUgAAADAAAAAwCAYAAABXAvmHAAAACXBIWXMAAAsTAAALEwEAmpwYAAACaUlEQVR4nO2WP2gTURzHL0N1EYQOKorgv9ElEVpwee/94iVWkAxakBB6v5fTA4coiG3WDsW6KIoulboIdniHo38mNf4ZdNBFp47aOumkoULNTw4STdK7486cDQfvA7/lcr+X7+f94wxDo9FoNBpNyrAsa5eUUkkpKWZ9QcTJYWbPSCmnEPFrzOAtKeU927ZHh5bctu1DiPg07qwj4nK1WhVDC+44zggi1hFxLWbwlmVZt2q12tahhUfEo4j4Me6sl8tlKhaLBADLpmnu2PTgjuNsR8SbiPgrTnDLstZKpZIXvLsebmp4RDxZqVS+xZ31C2fPNE3T7A9Pp06IG/3/QQr2kMvrpPgLUnyVXPaTXLZCijVI8RlaOrZ7UI/ZdvUghDjXHzCsrp4HIpc3yeVXaOHICKnJLeTy+fYz7zf/UuwHuWzOez9RAQCYjxq+NAH0/X5PqFek2OvQ4O4GkQapwmiSKzAXVeD2RRE9qBtaL/9lJYJWYCKqwNvriQmQt50SEaAHbK+3f5tLnD4tcnpzTdDCJUHV0xsFVhf5swjhHpOCMVJsG7l8nBR7EngmYh5sfwHv5ggIUiiACQCNtsAHIiMTGKgTnoxMz/hhPYpNDy7gXXu+g8NY5x3G2GEA2NkWHg8+oH97ugnuYc+NwVeArfgO/ui47+eC9zxQIHYP+5yEwLrf4GEDBQnE72HrkdPncrn32Wz23f8Lk3zPH4QQB9sHsWWa5v40Ckx1XYeV1AkAQL0jIISYTqPATJfA5dQIi7VsoX88f6BxixNj+1Al4AcBdALhj9JEaASC0gKsFNBqNRqPRaIwE+Q3s1bniQ173EAAAAAASUVORK5CYII="
    _rel_btns_list = []
    _rel_dl_list = []
    _rel_moodle_list = []
    _imp_list = []
    _gen = []
    _auto = []
    _fb = []
    _fb_csv_dl_list = []
    _fb_zip_dl_list = []
    _auto_upload_list = []
    _fetch_sub_list = []
    _upload_fb_list = []

    # Show Import column only if any assignment lacks transport sync
    _show_import = not TRANSPORT_READY or any(
        match_transport_assignment(_a.name) is None for _a in assignments
    )

    for _a in assignments:
        # Source — edit source notebook
        if _a.source_path:
            if MOGRADER_CONFIG.no_edit:
                _src_btns_list.append(mo.md(""))
            else:
                _p = _a.source_path
                _n = _a.name
                _src_btns_list.append(
                    mo.ui.button(
                        label="\u270e",
                        on_change=lambda _, p=_p, n=_n: _open_marimo("edit", p, n),
                        tooltip=f"Edit {_a.source_path.relative_to(COURSE_DIR)}",
                    )
                )
        else:
            _src_btns_list.append(mo.md("\u2013"))

        # Release — preview release notebook
        if _a.release_path:
            if MOGRADER_CONFIG.no_edit:
                _rel_btns_list.append(mo.md(""))
            else:
                _p2 = _a.release_path
                _n2 = _a.name
                _rel_btns_list.append(
                    mo.ui.button(
                        label="\u270e",
                        on_change=lambda _, p=_p2, n=_n2: _open_marimo("edit", p, n),
                        tooltip=f"Edit {_a.release_path.relative_to(COURSE_DIR)}",
                    )
                )
            _rel_dir = _a.release_path.parent
            _zip_name = f"{_a.name}.zip"

            def _make_zip(d=_rel_dir):
                buf = io.BytesIO()
                with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
                    for f in sorted(d.iterdir()):
                        if not f.is_dir():
                            zf.write(f, f.name)
                return buf.getvalue()

            _rel_dl_list.append(
                mo.download(data=_make_zip, filename=_zip_name, label=" ")
            )
            _moodle_url = moodle_upload_url(_a.name)
            if _moodle_url:
                _rel_moodle_list.append(
                    mo.Html(
                        f'<a href="{_moodle_url}" target="_blank" title="Upload to Moodle">'
                        f'<img src="data:image/png;base64,{_MOODLE_ICON_B64}" '
                        f'style="height:18px;vertical-align:middle;display:block" /></a>'
                    )
                )
            else:
                _rel_moodle_list.append(None)
        else:
            _rel_btns_list.append(mo.md("\u2013"))
            _rel_dl_list.append(None)
            _rel_moodle_list.append(None)

        # Per-assignment: can this assignment sync via transport?
        _transport_name = (
            match_transport_assignment(_a.name) if TRANSPORT_READY else None
        )
        _has_sync = _transport_name is not None

        # Import — file upload for CSV + ZIP (hidden when sync available for this assignment)
        if not _has_sync:
            _imp_list.append(
                mo.ui.file(
                    filetypes=[".csv", ".zip"],
                    multiple=True,
                    label="\u2191",
                    kind="button",
                )
            )
        else:
            _imp_list.append(mo.md(""))

        # Generate
        if _a.source_path:
            _src = str(_a.source_path)
            _out = str(COURSE_DIR / DIR_NAMES.release)
            _n3 = _a.name
            _gen_cmd = ["generate", _src, "-o", _out]
            if MOGRADER_CONFIG.no_actions:
                _gen_cmd.append("--no-validate")
            _gen.append(
                mo.ui.button(
                    label="\u00bb",
                    on_change=lambda _, cmd=_gen_cmd, n=_n3: set_pending_action(
                        {"cmd": cmd, "label": f"generate {n}"}
                    ),
                    tooltip="Generate",
                )
            )
        else:
            _gen.append(mo.ui.button(label="\u00bb", disabled=True, tooltip="Generate"))

        # Autograde
        _sub_dir = COURSE_DIR / DIR_NAMES.submitted / _a.name
        if (
            not MOGRADER_CONFIG.no_actions
            and _sub_dir.is_dir()
            and any(_sub_dir.glob("*.py"))
        ):
            import re as _re2

            _TS = _re2.compile(r"_\d{8}T\d{6}$")
            _files = [
                str(f) for f in sorted(_sub_dir.glob("*.py")) if not _TS.search(f.stem)
            ]
            _src_flag = ["--source", str(_a.source_path)] if _a.source_path else []
            _cmd = ["autograde"] + _files + _src_flag
            _n4 = _a.name
            _auto.append(
                mo.ui.button(
                    label="\u00bb",
                    on_change=lambda _, c=_cmd, n=_n4: set_pending_action(
                        {"cmd": c, "label": f"autograde {n}"}
                    ),
                    tooltip="Autograde",
                )
            )
        else:
            _auto.append(
                mo.ui.button(label="\u00bb", disabled=True, tooltip="Autograde")
            )

        # Export Moodle (feedback + optional moodle merge)
        _auto_dir = COURSE_DIR / DIR_NAMES.autograded / _a.name
        _worksheet_path = COURSE_DIR / DIR_NAMES.import_dir / f"{_a.name}.csv"
        _export_dir = COURSE_DIR / "export"
        if _auto_dir.is_dir() and any(_auto_dir.glob("*.py")):
            _ffiles = [str(f) for f in sorted(_auto_dir.glob("*.py"))]
            _fb_dir = str(COURSE_DIR / DIR_NAMES.feedback / _a.name)
            _cmd_fb = ["feedback"] + _ffiles
            _sub_cmds = [_cmd_fb]
            if _worksheet_path.is_file():
                _sub_cmds.append(
                    [
                        "moodle",
                        str(_worksheet_path),
                        "--feedback-dir",
                        _fb_dir,
                        "-o",
                        str(_export_dir),
                    ]
                )
            _n5 = _a.name
            _tooltip = (
                "Export Moodle" if _worksheet_path.is_file() else "Export feedback"
            )
            _fb.append(
                mo.ui.button(
                    label="\u00bb",
                    on_change=lambda _, c=_sub_cmds, n=_n5: set_pending_action(
                        {"cmd": c, "label": f"export {n}"}
                    ),
                    tooltip=_tooltip,
                )
            )
        else:
            _fb.append(
                mo.ui.button(label="\u00bb", disabled=True, tooltip="Export Moodle")
            )

        # Feedback downloads — CSV and ZIP if they exist
        _export_csv = _export_dir / f"{_a.name}.csv"
        if _export_csv.is_file():
            _cp = _export_csv
            _cn = _export_csv.name

            def _read_fb_csv(p=_cp):
                return p.read_bytes()

            _fb_csv_dl_list.append(
                mo.download(data=_read_fb_csv, filename=_cn, label=" ")
            )
        else:
            _fb_csv_dl_list.append(None)

        _export_zip = _export_dir / f"feedback_{_a.name}.zip"
        if _export_zip.is_file():
            _zp = _export_zip
            _zn = _export_zip.name

            def _read_fb_zip(p=_zp):
                return p.read_bytes()

            _fb_zip_dl_list.append(
                mo.download(data=_read_fb_zip, filename=_zn, label=" ")
            )
        else:
            _fb_zip_dl_list.append(None)

        # Autograded upload — ZIP file upload per assignment (hidden when sync available)
        if not _has_sync:
            _auto_upload_list.append(
                mo.ui.file(
                    filetypes=[".zip"],
                    multiple=False,
                    label="\u2191",
                    kind="button",
                )
            )
        else:
            _auto_upload_list.append(mo.md(""))

        # Fetch submissions via transport
        _sub_out = str(COURSE_DIR / DIR_NAMES.submitted / _a.name)
        if _has_sync:
            _n_fetch = _transport_name
            _n_label = _a.name
            _fetch_sub_list.append(
                mo.ui.button(
                    label="\u2193",
                    on_change=lambda _, n=_n_fetch, o=_sub_out, nl=_n_label: (
                        set_pending_action(
                            {
                                "cmd": [
                                    TRANSPORT_TYPE,
                                    "fetch-submissions",
                                    n,
                                    "-o",
                                    o,
                                ],
                                "label": f"fetch submissions {nl}",
                            }
                        )
                    ),
                    tooltip="Fetch submissions",
                )
            )
        else:
            _fetch_sub_list.append(
                mo.ui.button(label="\u2193", disabled=True, tooltip="Fetch submissions")
            )

        # Upload grades & feedback via transport (instructor only)
        _fb_dir_path = COURSE_DIR / DIR_NAMES.feedback / _a.name
        _has_feedback = _fb_dir_path.is_dir() and any(_fb_dir_path.glob("*.html"))
        if _has_sync and _has_feedback:
            _n_up = _transport_name
            _fb_d = str(_fb_dir_path)
            _moodle_link = moodle_grading_url(_a.name)
            _upload_fb_list.append(
                mo.ui.button(
                    label="\u2191",
                    on_change=lambda _, n=_n_up, d=_fb_d, ml=_moodle_link: (
                        set_pending_action(
                            {
                                "cmd": [
                                    TRANSPORT_TYPE,
                                    "upload-feedback",
                                    n,
                                    "--feedback-dir",
                                    d,
                                ],
                                "label": f"upload feedback {n}",
                                "review_url": ml,
                            }
                        )
                    ),
                    tooltip="Upload grades & feedback",
                )
            )
        else:
            _upload_fb_list.append(
                mo.ui.button(
                    label="\u2191",
                    disabled=True,
                    tooltip="Upload grades & feedback",
                )
            )

    # Wrap interactive buttons in mo.ui.array for marimo state tracking
    _src_ui = [e for e in _src_btns_list if not isinstance(e, mo.Html)]
    _rel_ui = [e for e in _rel_btns_list if not isinstance(e, mo.Html)]
    src_btns = mo.ui.array(_src_ui) if _src_ui else None
    rel_btns = mo.ui.array(_rel_ui) if _rel_ui else None
    rel_downloads = (
        mo.ui.array([e for e in _rel_dl_list if e is not None])
        if any(e is not None for e in _rel_dl_list)
        else None
    )
    fb_csv_downloads = (
        mo.ui.array([e for e in _fb_csv_dl_list if e is not None])
        if any(e is not None for e in _fb_csv_dl_list)
        else None
    )
    fb_zip_downloads = (
        mo.ui.array([e for e in _fb_zip_dl_list if e is not None])
        if any(e is not None for e in _fb_zip_dl_list)
        else None
    )
    _imp_ui = [e for e in _imp_list if not isinstance(e, mo.Html)]
    imp_uploads = mo.ui.array(_imp_ui) if _imp_ui else mo.ui.array([])
    gen_btns = mo.ui.array(_gen)
    auto_btns = mo.ui.array(_auto)
    fb_btns = mo.ui.array(_fb)
    _auto_upload_ui = [e for e in _auto_upload_list if not isinstance(e, mo.Html)]
    auto_uploads = mo.ui.array(_auto_upload_ui) if _auto_upload_ui else mo.ui.array([])
    fetch_sub_btns = mo.ui.array(_fetch_sub_list)
    upload_fb_btns = mo.ui.array(_upload_fb_list)

    # Map array indices back to row positions for mixed button/md lists
    _src_idx = 0
    _rel_idx = 0
    _rel_dl_idx = 0
    _fb_csv_dl_idx = 0
    _fb_zip_dl_idx = 0

    # --- build merged assignments + grades table ---
    _rows = []
    for _i, _a in enumerate(assignments):
        # Source column: ✅ + edit button only
        if isinstance(_src_btns_list[_i], mo.Html):
            _src_cell = _src_btns_list[_i]
        else:
            _src_cell = mo.hstack(
                [mo.md("\u2705"), src_btns[_src_idx]],
                justify="start",
                gap=0.25,
            )
            _src_idx += 1

        # Release column: ✅ + edit button, or –
        if isinstance(_rel_btns_list[_i], mo.Html):
            _rel_cell = _rel_btns_list[_i]
        else:
            _rel_cell = mo.hstack(
                [mo.md("\u2705"), rel_btns[_rel_idx]],
                justify="start",
                gap=0.25,
            )
            _rel_idx += 1

        # Submitted column: count + fetch button (sync), or count only (file mode)
        if _has_sync:
            _sub_cell = mo.hstack(
                [mo.md(str(_a.num_submitted)), fetch_sub_btns[_i]],
                justify="start",
                gap=0.25,
            )
        else:
            _sub_cell = mo.md(str(_a.num_submitted))

        # Feedback column: text only
        _fb_text = (
            f"{_a.num_feedback}/{_a.num_autograded}" if _a.num_autograded else "\u2013"
        )

        # Release column: combine edit + download + moodle upload link
        _rel_items = [_rel_cell]
        if _rel_dl_list[_i] is not None and rel_downloads is not None:
            _rel_items.append(rel_downloads[_rel_dl_idx])
            _rel_dl_idx += 1
        if _rel_moodle_list[_i] is not None:
            _rel_items.append(_rel_moodle_list[_i])
        _rel_combined = (
            mo.hstack(_rel_items, justify="start", gap=0.25)
            if len(_rel_items) > 1
            else _rel_items[0]
        )

        # Export column: combine arrow + download buttons
        _export_items = [fb_btns[_i]]
        if _fb_csv_dl_list[_i] is not None and fb_csv_downloads is not None:
            _export_items.append(fb_csv_downloads[_fb_csv_dl_idx])
            _fb_csv_dl_idx += 1
        if _fb_zip_dl_list[_i] is not None and fb_zip_downloads is not None:
            _export_items.append(fb_zip_downloads[_fb_zip_dl_idx])
            _fb_zip_dl_idx += 1
        _export_items.append(upload_fb_btns[_i])
        _export_cell = (
            mo.hstack(_export_items, justify="start", gap=0.25)
            if len(_export_items) > 1
            else _export_items[0]
        )

        _name = _a.name

        _graded_text = (
            f"{_a.num_graded}/{_a.num_autograded}" if _a.num_autograded else "\u2013"
        )

        # Import: file widget or empty (per-assignment sync availability)
        _import_cell = _imp_list[_i]

        # Graded: count + upload widget, or count only
        if isinstance(_auto_upload_list[_i], mo.Html):
            _graded_cell = mo.md(_graded_text)
        else:
            _graded_cell = mo.hstack(
                [mo.md(_graded_text), _auto_upload_list[_i]],
                justify="start",
                gap=0.25,
            )

        _row = {
            "Assignment": mo.md(_name),
            "Source": _src_cell,
            "\u00bb": gen_btns[_i],
            "Release": _rel_combined,
        }
        if _show_import:
            _row["Import"] = _import_cell
        _row.update(
            {
                "Submitted": _sub_cell,
                "\u00bb ": auto_btns[_i],
                "Graded": _graded_cell,
                "Export": _export_cell,
                "Feedback": mo.md(_fb_text),
            }
        )
        _rows.append(_row)

    assignments_content = (
        mo.ui.table(_rows, selection=None)
        if _rows
        else mo.md(
            "_No assignments found. Check that the course directory contains "
            "`source/`, `submitted/`, etc._"
        )
    )
    return (
        assignments_content,
        auto_uploads,
        fetch_sub_btns,
        upload_fb_btns,
        src_btns,
        rel_btns,
        rel_downloads,
        fb_csv_downloads,
        fb_zip_downloads,
        imp_uploads,
        gen_btns,
        auto_btns,
        fb_btns,
    )


@app.cell
def _(
    imp_uploads,
    assignments,
    COURSE_DIR,
    DIR_NAMES,
    MOGRADER_CONFIG,
    Gradebook,
    mo,
    set_action_log,
    set_data_version,
):
    from mograder.transport.moodle import extract_submissions, read_moodle_worksheet

    for _i, _a in enumerate(assignments):
        if _i >= len(imp_uploads):
            break
        _files = imp_uploads[_i].value
        if not _files:
            continue

        _import_dir = COURSE_DIR / DIR_NAMES.import_dir
        _import_dir.mkdir(parents=True, exist_ok=True)

        _csv_file = None
        _zip_file = None
        for _f in _files:
            if _f.name.endswith(".csv"):
                _csv_file = _f
            elif _f.name.endswith(".zip"):
                _zip_file = _f

        _msgs = []

        # Save CSV to import/assignment.csv
        if _csv_file:
            _csv_dest = _import_dir / f"{_a.name}.csv"
            _csv_dest.write_bytes(_csv_file.contents)
            _msgs.append(f"Saved `{_csv_dest.name}`")

            # Upsert students into gradebook
            _db_path = COURSE_DIR / MOGRADER_CONFIG.gradebook
            _fieldnames, _rows = read_moodle_worksheet(_csv_dest)
            _match_col = MOGRADER_CONFIG.moodle_match_column
            _name_col = MOGRADER_CONFIG.moodle_name_column
            if _match_col in _fieldnames and _name_col in _fieldnames:
                _mapping = {
                    r[_match_col]: r[_name_col]
                    for r in _rows
                    if r.get(_match_col) and r.get(_name_col)
                }
                if _mapping:
                    with Gradebook(_db_path) as _gb:
                        _gb.upsert_students(_mapping)
                    _msgs.append(f"Imported {len(_mapping)} students")

        # Extract ZIP to submitted/assignment/
        if _zip_file and _csv_file:
            _zip_tmp = _import_dir / f"{_a.name}.zip"
            _zip_tmp.write_bytes(_zip_file.contents)
            _sub_dir = COURSE_DIR / DIR_NAMES.submitted / _a.name
            _sub_dir.mkdir(parents=True, exist_ok=True)
            _existing = set(f.name for f in _sub_dir.glob("*.py"))
            _result = extract_submissions(
                _zip_tmp,
                _csv_dest,
                _sub_dir,
                match_column=MOGRADER_CONFIG.moodle_match_column,
            )
            _msgs.append(f"Extracted {_result.extracted} submissions")
            if _existing and _result.extracted:
                _overwritten = _existing & set(f.name for f in _sub_dir.glob("*.py"))
                if _overwritten:
                    _msgs.append(f"⚠️ Overwrote {len(_overwritten)} existing file(s)")
            if _result.warnings:
                _msgs.extend(_result.warnings)
        elif _zip_file and not _csv_file:
            _msgs.append("⚠️ ZIP provided without CSV — cannot map student names")

        if _msgs:
            set_action_log(f"**Import {_a.name}:** " + "; ".join(_msgs))
            set_data_version(lambda v: v + 1)
    return


@app.cell
def _(
    auto_uploads,
    assignments,
    COURSE_DIR,
    DIR_NAMES,
    MOGRADER_CONFIG,
    Gradebook,
    set_action_log,
    set_data_version,
    zipfile,
):
    for _i, _a in enumerate(assignments):
        if _i >= len(auto_uploads):
            break
        _files = auto_uploads[_i].value
        if not _files:
            continue

        _file = _files[0] if isinstance(_files, list) else _files
        if not _file.name.endswith(".zip"):
            continue

        _auto_dir = COURSE_DIR / DIR_NAMES.autograded / _a.name
        _auto_dir.mkdir(parents=True, exist_ok=True)

        _msgs = []
        _count = 0
        with zipfile.ZipFile(__import__("io").BytesIO(_file.contents)) as _zf:
            for _entry in _zf.namelist():
                if _entry.endswith(".py") or _entry.endswith(".html"):
                    _data = _zf.read(_entry)
                    # Use just the filename (strip any directory prefix)
                    _fname = _entry.split("/")[-1]
                    (_auto_dir / _fname).write_bytes(_data)
                    _count += 1

        _msgs.append(f"Extracted {_count} files to `{DIR_NAMES.autograded}/{_a.name}/`")

        # Import into gradebook
        _db_path = COURSE_DIR / MOGRADER_CONFIG.gradebook
        try:
            with Gradebook(_db_path) as _gb:
                _gb.upsert_assignment(_a.name)
                _imported = _gb.import_from_py(_a.name, _auto_dir)
                _msgs.append(f"Imported {_imported} grades into gradebook")
        except Exception as _e:
            _msgs.append(f"⚠️ Gradebook import failed: {_e}")

        set_action_log(f"**Upload autograded {_a.name}:** " + "; ".join(_msgs))
        set_data_version(lambda v: v + 1)
    return


@app.cell
def _(
    COURSE_DIR,
    DIR_NAMES,
    GRADEBOOK,
    MOGRADER_CONFIG,
    alt,
    assignment_dropdown,
    get_data_version,
    get_selected,
    mo,
    refresh_btn,
    set_action_log,
    set_pending_action,
    sp,
    sys,
):
    from mograder.grader.scanner import scan_submissions

    _refresh = refresh_btn.value, get_data_version()
    _selected = get_selected()

    if _selected:
        _subs = scan_submissions(
            COURSE_DIR, _selected, dir_names=DIR_NAMES, gradebook=GRADEBOOK
        )

        def _open_editor(path):
            if MOGRADER_CONFIG.headless_edit:
                set_pending_action(
                    {"action": "edit", "path": str(path), "label": path.name}
                )
            else:
                sp.Popen(
                    [sys.executable, "-m", "marimo", "edit", "--sandbox", str(path)]
                )
                set_action_log(f"Opened editor for **{path.name}**")

        _edit_list = []
        for _s in _subs:
            if MOGRADER_CONFIG.no_edit:
                _edit_list.append(mo.ui.button(label="\u270e", disabled=True))
            elif _s.autograded_path:
                _p = _s.autograded_path
                _edit_list.append(
                    mo.ui.button(
                        label="\u270e",
                        on_change=lambda _, p=_p: _open_editor(p),
                    )
                )
            else:
                _edit_list.append(mo.ui.button(label="\u270e", disabled=True))

        edit_btns = mo.ui.array(_edit_list)

        _rows = []
        for _i, _s in enumerate(_subs):
            _manual = "—"
            if _s.mark is not None and _s.auto_mark is not None:
                _manual = _s.mark - _s.auto_mark
            elif _s.auto_mark is None and _s.mark is not None:
                _manual = _s.mark
            _rows.append(
                {
                    "Student": _s.student,
                    "Status": "Graded"
                    if _s.graded
                    else ("Autograded" if _s.has_grading_cells else "Submitted"),
                    "Auto Mark": _s.auto_mark if _s.auto_mark is not None else "—",
                    "Manual Mark": _manual,
                    "Total": _s.mark if _s.mark is not None else "—",
                    "Feedback": "Yes" if _s.feedback_exported else "—",
                    "Edit": edit_btns[_i],
                }
            )

        # Three histograms: Auto Mark, Manual Mark, Total
        _auto_marks = [_s.auto_mark for _s in _subs if _s.auto_mark is not None]
        _manual_marks = [
            _s.mark - _s.auto_mark
            for _s in _subs
            if _s.mark is not None and _s.auto_mark is not None
        ]
        _total_marks = [_s.mark for _s in _subs if _s.mark is not None]
        _histogram = mo.md("")
        _any_data = _auto_marks or _manual_marks or _total_marks
        if _any_data:
            _charts = []
            for _data, _label in zip(
                [_auto_marks, _manual_marks, _total_marks],
                ["Auto Mark", "Manual Mark", "Total"],
            ):
                if _data:
                    _charts.append(
                        alt.Chart(alt.Data(values=[{"value": v} for v in _data]))
                        .mark_bar(color="#4C78A8")
                        .encode(
                            alt.X("value:Q", bin=alt.Bin(maxbins=8), title=_label),
                            alt.Y("count()", title="Count"),
                        )
                        .properties(width=250, height=150)
                    )
            if _charts:
                _histogram = mo.hstack(_charts)

        submissions_content = mo.vstack(
            [
                assignment_dropdown,
                mo.ui.table(_rows, selection=None)
                if _rows
                else mo.md("_No submissions found._"),
                _histogram,
            ]
        )
    else:
        edit_btns = mo.ui.array([])
        submissions_content = mo.vstack(
            [
                assignment_dropdown,
                mo.md("_Select an assignment above._"),
            ]
        )
    return edit_btns, scan_submissions, submissions_content


@app.cell
def _(mo):
    show_names = mo.ui.switch(label="Show names")
    students_controls = mo.hstack([show_names], justify="start", gap=1)
    return show_names, students_controls


@app.cell
def _(name_lookup, show_names):
    students_name_lookup = name_lookup if show_names.value else {}
    return (students_name_lookup,)


@app.cell
def _(COURSE_DIR, GRADEBOOK, MOGRADER_CONFIG, get_data_version, refresh_btn):
    from mograder.transport.moodle import read_moodle_worksheet as _read_ws

    _ = refresh_btn.value, get_data_version()

    # Priority 1: gradebook students table
    if GRADEBOOK is not None:
        name_lookup = GRADEBOOK.get_name_lookup()
    # Priority 2: config moodle_csv
    elif MOGRADER_CONFIG.moodle_csv:
        _match_col = MOGRADER_CONFIG.moodle_match_column
        _name_col = MOGRADER_CONFIG.moodle_name_column
        _csv_path = COURSE_DIR / MOGRADER_CONFIG.moodle_csv
        if _csv_path.is_file():
            _, _rows = _read_ws(_csv_path)
            name_lookup = {
                r[_match_col]: r[_name_col]
                for r in _rows
                if _match_col in r and _name_col in r
            }
        else:
            name_lookup = {}
    else:
        name_lookup = {}
    return (name_lookup,)


@app.cell
def _(
    COURSE_DIR,
    DIR_NAMES,
    GRADEBOOK,
    alt,
    assignments,
    mo,
    refresh_btn,
    students_controls,
    students_name_lookup,
):
    from mograder.grader.scanner import collect_student_marks, get_max_marks

    _ = refresh_btn.value
    _student_marks = collect_student_marks(
        COURSE_DIR, assignments, dir_names=DIR_NAMES, gradebook=GRADEBOOK
    )
    _max_marks = get_max_marks(COURSE_DIR, assignments, dir_names=DIR_NAMES)
    _assignment_names = [a.name for a in assignments]

    _rows = []
    _averages = []
    for _sid in sorted(_student_marks):
        _display = students_name_lookup.get(_sid, _sid)
        _row = {"Student": _display}
        _total = 0
        _max_total = 0
        for _aname in _assignment_names:
            _m = _student_marks[_sid].get(_aname)
            _row[_aname] = _m if _m is not None else "–"
            if _m is not None:
                _total += _m
                _max_total += _max_marks.get(_aname, 100)
        _row["Total"] = f"{_total}/{_max_total}" if _max_total else "–"
        _avg = round(_total / _max_total * 100, 1) if _max_total else None
        _row["Avg %"] = f"{_avg}" if _avg is not None else "–"
        if _avg is not None:
            _averages.append(_avg)
        _rows.append(_row)

    _table = (
        mo.ui.table(_rows, selection=None)
        if _rows
        else mo.md("_No autograded submissions found._")
    )

    _histogram = mo.md("")
    if len(_averages) >= 2:
        _mean = sum(_averages) / len(_averages)
        _var = sum((a - _mean) ** 2 for a in _averages) / len(_averages)
        _std = _var**0.5
        _chart = (
            alt.Chart(alt.Data(values=[{"value": v} for v in _averages]))
            .mark_bar(color="#4C78A8")
            .encode(
                alt.X("value:Q", bin=alt.Bin(maxbins=8), title="Average %"),
                alt.Y("count()", title="Count"),
            )
            .properties(width=300, height=150)
        )
        _histogram = mo.vstack(
            [
                _chart,
                mo.md(
                    f"**Mean:** {_mean:.1f}% | **Std:** {_std:.1f} "
                    f"| **Min:** {min(_averages)}% | **Max:** {max(_averages)}%"
                ),
            ]
        )

    students_content = mo.vstack([students_controls, _table, _histogram])
    return collect_student_marks, get_max_marks, students_content


@app.cell
def _(
    COURSE_DIR,
    DIR_NAMES,
    GRADEBOOK,
    get_data_version,
    get_selected,
    refresh_btn,
    set_grading_index,
):
    from mograder.grader.scanner import scan_submissions as _scan_subs

    _ = refresh_btn.value, get_data_version()

    # Use the assignment selected in the Assignments tab
    _sel = get_selected()
    if _sel:
        grading_subs = _scan_subs(
            COURSE_DIR, _sel, dir_names=DIR_NAMES, gradebook=GRADEBOOK
        )
        grading_subs = [s for s in grading_subs if s.autograded_path]
    else:
        grading_subs = []
    grading_assignment_name = _sel
    return grading_assignment_name, grading_subs


@app.cell
def _(get_grading_index, grading_subs):
    # Pure data cell: compute current submission from index
    _idx = get_grading_index()
    if grading_subs:
        _idx = max(0, min(_idx, len(grading_subs) - 1))
        grading_current_sub = grading_subs[_idx]
    else:
        grading_current_sub = None
    return (grading_current_sub,)


@app.cell
def _(
    COURSE_DIR,
    DIR_NAMES,
    GRADEBOOK,
    assignments,
    grading_assignment_name,
    grading_current_sub,
    mo,
    set_grading_inputs,
):
    import re as _re
    from mograder.grading.cells import extract_marking_scale as _extract_scale
    from mograder.grading.cells import parse_auto_marks as _parse_auto
    from mograder.grading.cells import parse_marker_feedback as _parse_fb

    def _count_sentences(text: str) -> int:
        """Count sentences (sequences ending with .!? followed by space or end)."""
        if not text.strip():
            return 0
        sentences = _re.split(r"[.!?]+(?:\s|$)", text.strip())
        return len([s for s in sentences if s.strip()])

    # Extract marking scale from source notebook via AssignmentInfo.source_path.
    # Assignment names may differ between source/ and autograded/ dirs
    # (e.g. source/ES98E-A1-Intro-to-SciML vs autograded/A1), so try:
    # 1. Exact name match, 2. Name contained in source name, 3. Direct path
    _scale_text = None
    _source_path = None
    if grading_assignment_name:
        for _a in assignments:
            if _a.source_path and (
                _a.name == grading_assignment_name or grading_assignment_name in _a.name
            ):
                _source_path = _a.source_path
                break
        # Fall back to direct directory lookup
        if _source_path is None:
            _src_dir = COURSE_DIR / DIR_NAMES.source / grading_assignment_name
            if _src_dir.is_dir():
                _src_files = list(_src_dir.glob("*.py"))
                if _src_files:
                    _source_path = _src_files[0]
    if _source_path and _source_path.is_file():
        _scale_text = _extract_scale(_source_path.read_text().splitlines(keepends=True))

    # Create mark + feedback inputs, re-reading from DB or .py file for fresh data
    _marks_meta = None
    _auto_max = 0
    if grading_current_sub is not None and grading_current_sub.autograded_path:
        _mark = None
        _feedback_text = ""
        _auto_mark = None
        _db_sub = None

        # Try DB first
        if GRADEBOOK is not None and grading_assignment_name:
            _db_sub = GRADEBOOK.get_submission(
                grading_assignment_name, grading_current_sub.student
            )
            if _db_sub is not None:
                _mark = (
                    int(_db_sub["manual_mark"])
                    if _db_sub["manual_mark"] is not None
                    else None
                )
                _feedback_text = _db_sub["feedback"] or ""
                _auto_mark = (
                    int(_db_sub["auto_mark"])
                    if _db_sub["auto_mark"] is not None
                    else None
                )

        # Fall back to .py parsing if no DB data
        if GRADEBOOK is None or not grading_assignment_name:
            _lines = grading_current_sub.autograded_path.read_text().splitlines(
                keepends=True
            )
            _mark, _feedback_text = _parse_fb(_lines)
            _auto_mark = _parse_auto(_lines)

        _max_mark = 100
        if GRADEBOOK is not None and grading_assignment_name:
            _assign = GRADEBOOK.get_assignment(grading_assignment_name)
            if _assign:
                _max_mark = int(_assign["max_mark"])
                _marks_meta = _assign.get("marks_metadata")

        # Compute auto_max (marks available for auto-graded questions).
        # Use auto_check_keys from the assignment record (derived from the
        # source notebook's check() calls at autograde time) — NOT the
        # student's check_results, which may be incomplete when mo.stop
        # guards prevent checks from running.
        if _marks_meta and _auto_mark is not None:
            _auto_keys = set(_assign.get("auto_check_keys") or []) if _assign else set()
            if _auto_keys:
                _auto_max = sum(v for k, v in _marks_meta.items() if k in _auto_keys)
            else:
                # Fallback for DBs created before auto_check_keys was stored:
                # treat all marks-dict keys as auto-graded (conservative).
                _auto_max = sum(_marks_meta.values())
        else:
            _auto_max = 0

        _manual_available = _max_mark - _auto_max
        _current_mark = int(_mark or 0)

        grading_mark_input = mo.ui.slider(
            start=0,
            stop=100,
            step=1,
            value=min(_current_mark, 100),
            label="Manual mark (/100)",
            show_value=True,
        )
        grading_feedback_input = mo.ui.text_area(
            value=_feedback_text or "",
            label="Feedback",
            rows=8,
            full_width=True,
            debounce=300,
        )

        # Total mark display
        if _auto_mark is not None and _manual_available > 0:
            _manual_contribution = round(_current_mark / 100 * _manual_available)
            _total_display = _auto_mark + _manual_contribution
            grading_auto_info = (
                f"**Auto:** {_auto_mark}/{_auto_max} | "
                f"**Manual:** {_current_mark}/100 "
                f"(\u2192{_manual_contribution}/{_manual_available}) | "
                f"**Total:** {_total_display}/{_max_mark}"
            )
        elif _auto_mark is not None:
            grading_auto_info = (
                f"**Auto marks:** {_auto_mark} | **Manual:** {_current_mark}/100"
            )
        else:
            grading_auto_info = f"**Manual:** {_current_mark}/100"

        # Store scaling info for _save_current (includes updated_at for
        # optimistic locking — detects concurrent edits by another grader)
        grading_scale_info = {
            "auto_mark": _auto_mark,
            "auto_max": _auto_max,
            "manual_available": _manual_available,
            "max_mark": _max_mark,
            "updated_at": _db_sub.get("updated_at") if _db_sub is not None else None,
        }
    else:
        grading_mark_input = mo.ui.slider(
            start=0, stop=100, step=1, value=0, label="Mark", show_value=True
        )
        grading_feedback_input = mo.ui.text_area(value="", label="Feedback")
        grading_auto_info = ""
        grading_scale_info = {
            "auto_mark": None,
            "auto_max": 0,
            "manual_available": 100,
            "max_mark": 100,
            "updated_at": None,
        }
    set_grading_inputs({"mark": grading_mark_input, "feedback": grading_feedback_input})

    # Marking scale accordion
    if _scale_text:
        grading_scheme = mo.accordion({"Marking Scale": mo.md(_scale_text)})
    else:
        grading_scheme = mo.md("")

    # Feedback validation — use the initial text directly, not
    # grading_feedback_input.value (reading .value in the cell that
    # created the element is forbidden in ASGI mode)
    _fb_text = (_feedback_text or "") if grading_current_sub is not None else ""
    _sentence_count = _count_sentences(_fb_text)
    if _fb_text and _sentence_count < 3:
        grading_validation = mo.callout(
            mo.md(f"Feedback needs at least 3 sentences (currently {_sentence_count})"),
            kind="warn",
        )
    else:
        grading_validation = mo.md("")

    # Build form layout in the same cell that creates the inputs.
    # The creating cell does NOT re-run when the user interacts with the inputs,
    # so downstream cells (grading_content with the iframe) stay stable.
    if grading_current_sub is not None:
        grading_form = mo.vstack(
            [
                grading_scheme,
                mo.md(grading_auto_info) if grading_auto_info else mo.md(""),
                mo.hstack([grading_mark_input]),
                grading_feedback_input,
                grading_validation,
            ]
        )
    else:
        grading_form = mo.md("_No submission selected._")
    return grading_form, grading_scale_info


@app.cell
def _(mo):
    grading_show_names = mo.ui.switch(label="Show names")
    return (grading_show_names,)


@app.cell
def _(
    COURSE_DIR,
    GRADEBOOK,
    Gradebook,
    MOGRADER_CONFIG,
    get_grading_index,
    get_grading_inputs,
    grading_assignment_name,
    grading_current_sub,
    grading_scale_info,
    grading_show_names,
    grading_subs,
    mo,
    name_lookup,
    set_action_log,
    set_data_version,
    set_grading_index,
):
    import re as _re
    from mograder.grading.cells import write_marker_feedback as _write_fb

    def _count_sentences(text: str) -> int:
        if not text.strip():
            return 0
        sentences = _re.split(r"[.!?]+(?:\s|$)", text.strip())
        return len([s for s in sentences if s.strip()])

    def _save_current():
        _inputs = get_grading_inputs()
        if (
            grading_current_sub is not None
            and grading_current_sub.autograded_path
            and _inputs is not None
        ):
            _slider_val = _inputs["mark"].value
            _feedback = _inputs["feedback"].value or ""

            # Enforce minimum 3-sentence feedback when mark is set
            if _slider_val > 0 and _count_sentences(_feedback) < 3:
                _n = _count_sentences(_feedback)
                set_action_log(
                    f"**Cannot save:** feedback must be at least 3 sentences "
                    f"(currently {_n}). Please expand your feedback before "
                    f"saving or navigating."
                )
                return

            # Scale slider (0-100) to manual contribution
            _manual_available = grading_scale_info["manual_available"]
            _auto_mark = grading_scale_info["auto_mark"]
            if _manual_available > 0 and _auto_mark is not None:
                _manual_contribution = round(_slider_val / 100 * _manual_available)
                _total = _auto_mark + _manual_contribution
            else:
                _total = _slider_val

            # Write to DB if available (store raw slider as manual_mark,
            # pass computed total).  Use optimistic locking: if another
            # grader saved since we loaded, warn instead of overwriting.
            _expected_ts = grading_scale_info.get("updated_at")
            if GRADEBOOK is not None and grading_assignment_name:
                _saved = GRADEBOOK.save_manual_grade(
                    grading_assignment_name,
                    grading_current_sub.student,
                    _slider_val,
                    _feedback,
                    total_mark=_total,
                    expected_updated_at=_expected_ts,
                )
                if not _saved:
                    set_action_log(
                        "**Conflict:** this submission was updated by another "
                        "grader since you opened it. Navigate away and back "
                        "to reload, or click Save again to overwrite."
                    )
                    # Clear the stale timestamp so a second save succeeds
                    grading_scale_info["updated_at"] = None
                    return
            elif grading_assignment_name:
                _gb_path = COURSE_DIR / MOGRADER_CONFIG.gradebook
                if _gb_path.is_file():
                    with Gradebook(_gb_path) as _gb:
                        _gb.save_manual_grade(
                            grading_assignment_name,
                            grading_current_sub.student,
                            _slider_val,
                            _feedback,
                            total_mark=_total,
                        )
                else:
                    _write_fb(
                        grading_current_sub.autograded_path, _slider_val, _feedback
                    )
            else:
                _write_fb(grading_current_sub.autograded_path, _slider_val, _feedback)
        set_data_version(lambda v: v + 1)

    def _save_and_navigate(new_idx):
        _save_current()
        set_grading_index(new_idx)

    _idx = get_grading_index()
    _total = len(grading_subs)
    _idx = max(0, min(_idx, _total - 1)) if _total else 0

    if grading_current_sub is not None:
        _student = grading_current_sub.student
        if grading_show_names.value:
            _display = name_lookup.get(_student, _student)
            _student_info = (
                f"**{_student}** ({_display})"
                if _display != _student
                else f"**{_student}**"
            )
        else:
            _student_info = f"**{_student}**"

        _prev_idx = max(0, _idx - 1)
        _next_idx = min(_total - 1, _idx + 1) if _total else 0
        _last_idx = _total - 1 if _total else 0

        _first_btn = mo.ui.button(
            label="<< First",
            on_change=lambda _: _save_and_navigate(0),
            disabled=_idx == 0,
        )
        _prev_btn = mo.ui.button(
            label="< Prev",
            on_change=lambda _, i=_prev_idx: _save_and_navigate(i),
            disabled=_idx == 0,
        )
        _next_btn = mo.ui.button(
            label="Next >",
            on_change=lambda _, i=_next_idx: _save_and_navigate(i),
            disabled=_idx >= _total - 1,
        )
        _last_btn = mo.ui.button(
            label="Last >>",
            on_change=lambda _, i=_last_idx: _save_and_navigate(i),
            disabled=_idx >= _total - 1,
        )
        _save_btn = mo.ui.button(
            label="Save",
            on_change=lambda _: _save_current(),
        )

        grading_nav = mo.hstack(
            [
                _first_btn,
                _prev_btn,
                mo.md(_student_info),
                _next_btn,
                _last_btn,
                _save_btn,
                mo.md(f"{_idx + 1}/{_total}"),
                grading_show_names,
            ],
            justify="start",
            gap=1,
        )
    else:
        grading_nav = mo.md(
            "_Select an assignment from the Assignment dropdown above._"
        )
    return (grading_nav,)


@app.cell
def _(grading_current_sub, mo):
    import base64 as _b64

    if grading_current_sub is not None and grading_current_sub.autograded_path:
        _html_path = grading_current_sub.autograded_path.with_suffix(".html")
        if _html_path.exists() and _html_path.stat().st_size > 0:
            _html_bytes = _html_path.read_bytes()
            _encoded = _b64.b64encode(_html_bytes).decode("ascii")
            grading_preview = mo.Html(
                f'<iframe src="data:text/html;base64,{_encoded}" '
                f'style="width:100%; height:50vh; border:1px solid #ccc;"></iframe>'
            )
        else:
            grading_preview = mo.callout(
                mo.md("No HTML export found. Re-run autograde to generate previews."),
                kind="warn",
            )
    else:
        grading_preview = mo.md("")
    return (grading_preview,)


@app.cell
def _(
    assignment_dropdown_grading,
    grading_form,
    grading_nav,
    grading_preview,
    grading_subs,
    mo,
):
    grading_content = (
        mo.vstack(
            [
                assignment_dropdown_grading,
                grading_nav,
                grading_form,
                grading_preview,
            ]
        )
        if grading_subs
        else mo.vstack(
            [
                assignment_dropdown_grading,
                mo.md("_Select an assignment with autograded submissions above._"),
            ]
        )
    )
    return (grading_content,)


@app.cell
def _(mo, set_action_log):
    clear_btn = mo.ui.button(
        label="Dismiss",
        on_change=lambda _: set_action_log(""),
    )
    return (clear_btn,)


@app.cell
def _(clear_btn, get_action_log, mo):
    _log = get_action_log()
    if _log:
        if "Cannot save" in _log:
            _kind = "warn"
        elif "exited with code" in _log or "timed out" in _log:
            _kind = "danger"
        else:
            _kind = "info"
        action_log_content = mo.vstack([mo.callout(mo.md(_log), kind=_kind), clear_btn])
    else:
        action_log_content = mo.md("")
    return (action_log_content,)


@app.cell
def _(
    MOGRADER_CONFIG, get_active_editors, mo, os, set_active_editors, set_pending_action
):
    import json as _json
    import urllib.request as _urllib_request
    from pathlib import Path as _Path

    # Sync UI state with server-side sessions (survives page reloads)
    _editors = get_active_editors()
    if MOGRADER_CONFIG.headless_edit:
        _api_url = (
            f"http://127.0.0.1:{os.environ.get('MOGRADER_PORT', '2718')}"
            f"{os.environ.get('MOGRADER_BASE_URL', '')}/_api/edit"
        )
        try:
            _server_sessions = _json.loads(
                _urllib_request.urlopen(_api_url, timeout=5).read()
            )
        except Exception:
            _server_sessions = []

        # Merge server sessions into UI state
        _server_map = {
            s["path"]: {"session_id": s["session_id"], "url": s["url"]}
            for s in _server_sessions
        }
        if _server_map != _editors:
            set_active_editors(lambda _: _server_map)
            _editors = _server_map

    if _editors and MOGRADER_CONFIG.headless_edit:
        _items = []
        for _path_str, _info in _editors.items():
            _url = _info["url"]
            _name = _Path(_path_str).name
            _sid = _info["session_id"]
            _stop_btn = mo.ui.button(
                label="Stop",
                kind="danger",
                on_change=lambda _, p=_path_str, s=_sid: set_pending_action(
                    {"action": "stop_edit", "path": p, "session_id": s}
                ),
                tooltip=f"Stop editor for {_name}",
            )
            _items.append(
                mo.hstack(
                    [
                        mo.md(
                            f'**{_name}** — <a href="{_url}" target="_blank">open</a>'
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
    else:
        active_editors_content = mo.md("")
    return (active_editors_content,)


@app.cell
def _(COURSE_DIR, DIR_NAMES, mo, set_pending_action):
    new_name_input = mo.ui.text(placeholder="new-assignment-name")
    new_btn = mo.ui.button(
        label="+ New",
        on_change=lambda _: set_pending_action(
            {
                "action": "new_assignment",
                "name": new_name_input.value,
                "source_dir": str(COURSE_DIR / DIR_NAMES.source),
            }
        ),
        tooltip="Create new assignment from template",
    )
    return new_btn, new_name_input


@app.cell
def _(
    COURSE_DIR,
    action_log_content,
    active_editors_content,
    assignments_content,
    brand_logo_html,
    version_html,
    get_user_display,
    grading_content,
    mo,
    new_btn,
    new_name_input,
    refresh_btn,
    students_content,
    submissions_content,
):
    _version = version_html()
    _style = mo.Html("""<style>
        /* Normalize download links to match mo.ui.button sizing */
        marimo-download a {
            padding: 3px 8px !important;
            min-height: unset !important;
            font-size: 0.85em !important;
            line-height: 1.4 !important;
        }
        marimo-download a svg { margin-right: 0 !important; }
    </style>""")
    _assignments_tab = mo.vstack(
        [
            assignments_content,
            mo.hstack(
                [mo.md("**New Assignment**"), new_name_input, new_btn],
                justify="start",
                align="center",
                gap=0.5,
            ),
        ]
    )
    mo.vstack(
        [
            _style,
            mo.hstack(
                [
                    mo.Html(
                        f'<div style="display:flex;align-items:center;gap:0.3em">{brand_logo_html()} <span style="font-size:2em;font-weight:bold">mograder</span> {_version}</div>'
                    ),
                    refresh_btn,
                    mo.md(f"`{get_user_display()}:{COURSE_DIR}`"),
                ],
                justify="space-between",
                align="center",
            ),
            mo.ui.tabs(
                {
                    "Assignments": _assignments_tab,
                    "Submissions": submissions_content,
                    "Grading": grading_content,
                    "Students": students_content,
                }
            ),
            active_editors_content,
            action_log_content,
        ]
    )
    return


@app.cell
def _(
    COURSE_DIR,
    MOGRADER_BIN,
    get_pending_action,
    mo,
    os,
    set_action_log,
    set_active_editors,
    set_data_version,
    set_pending_action,
    sp,
):
    import json as _json
    import traceback as _tb
    import urllib.request as _urllib_request

    _action = get_pending_action()
    if _action is not None and _action.get("action") == "edit":
        _path = _action["path"]
        _label = _action["label"]
        _base = os.environ.get("MOGRADER_BASE_URL", "")
        _port = os.environ.get("MOGRADER_PORT", "2718")
        with mo.status.spinner(
            title=f"Starting editor for {_label}...", remove_on_exit=True
        ):
            _req = _urllib_request.Request(
                f"http://127.0.0.1:{_port}{_base}/_api/edit",
                data=_json.dumps({"path": _path}).encode(),
                headers={"Content-Type": "application/json"},
            )
            try:
                _resp = _json.loads(_urllib_request.urlopen(_req, timeout=60).read())
                _url = _resp["url"]
                _session_id = _resp["session_id"]
                set_active_editors(
                    lambda d: {
                        **d,
                        _path: {"session_id": _session_id, "url": _url},
                    }
                )
                set_action_log(
                    f'Editing **{_label}**: <a href="{_url}" target="_blank">{_url}</a>'
                )
            except Exception as _exc:
                set_action_log(f"Failed to start editor for **{_label}**: {_exc}")
        set_pending_action(None)
    elif _action is not None and _action.get("action") == "stop_edit":
        from pathlib import Path as _PathSE

        _sid = _action["session_id"]
        _path = _action["path"]
        _base = os.environ.get("MOGRADER_BASE_URL", "")
        _port = os.environ.get("MOGRADER_PORT", "2718")
        _req = _urllib_request.Request(
            f"http://127.0.0.1:{_port}{_base}/_api/edit",
            data=_json.dumps({"session_id": _sid}).encode(),
            headers={"Content-Type": "application/json"},
            method="DELETE",
        )
        try:
            _urllib_request.urlopen(_req, timeout=10)
        except Exception:
            pass
        set_active_editors(lambda d: {k: v for k, v in d.items() if k != _path})
        set_action_log(f"Stopped editor for **{_PathSE(_path).name}**")
        set_pending_action(None)
    elif _action is not None and _action.get("action") == "new_assignment":
        import re as _re2
        from pathlib import Path as _Path

        _name = (_action.get("name") or "").strip()
        _source_dir = _Path(_action["source_dir"])
        if not _name:
            set_action_log("**New assignment** — name cannot be empty.")
        elif not _re2.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", _name):
            set_action_log(
                f"**New assignment** — invalid name `{_name}`. "
                "Use only letters, digits, hyphens, and underscores."
            )
        elif (_source_dir / _name).exists():
            set_action_log(
                f"**New assignment** — `{_name}` already exists in source directory."
            )
        else:
            import mograder as _mograder_pkg

            _template = (
                _Path(_mograder_pkg.__file__).parent / "templates" / "assignment.py"
            )
            _dest_dir = _source_dir / _name
            _dest_dir.mkdir(parents=True, exist_ok=True)
            _content = _template.read_text()
            _content = _content.replace("{assignment_name}", _name)
            (_dest_dir / f"{_name}.py").write_text(_content)
            set_action_log(f"**New assignment** — created `{_name}`.")
        set_data_version(lambda v: v + 1)
        set_pending_action(None)
    elif _action is not None:
        _cmd, _label = _action["cmd"], _action["label"]
        _review_url = _action.get("review_url")
        _review_link = (
            f' <a href="{_review_url}" target="_blank">Review on Moodle</a>'
            if _review_url
            else ""
        )
        # Compound action: list of sub-commands to run sequentially
        _is_compound = _cmd and isinstance(_cmd[0], list)
        # Commands that support --progress with JSON events on stderr
        _PROGRESS_CMDS = {"autograde", "generate"}
        _has_progress = not _is_compound and _cmd and _cmd[0] in _PROGRESS_CMDS

        try:
            if _is_compound:
                _combined_output = []
                _overall_ok = True
                with mo.status.spinner(title=_label, remove_on_exit=True):
                    for _sub_cmd in _cmd:
                        _sub_has_progress = _sub_cmd and _sub_cmd[0] in _PROGRESS_CMDS
                        if _sub_has_progress:
                            _full = [MOGRADER_BIN] + _sub_cmd + ["--progress"]
                            _p = sp.Popen(
                                _full,
                                stdout=sp.PIPE,
                                stderr=sp.PIPE,
                                text=True,
                                bufsize=1,
                                cwd=COURSE_DIR,
                            )
                            _p.wait()
                            _out = (
                                (_p.stdout.read() if _p.stdout else "")
                                + (_p.stderr.read() if _p.stderr else "")
                            ).strip()
                        else:
                            _p = sp.run(
                                [MOGRADER_BIN] + _sub_cmd,
                                capture_output=True,
                                text=True,
                                timeout=600,
                                cwd=COURSE_DIR,
                            )
                            _out = (_p.stdout + _p.stderr).strip()
                        if _out:
                            _combined_output.append(_out)
                        if _p.returncode != 0:
                            _overall_ok = False
                            break
                _combined = "\n".join(_combined_output)
                _code = f"\n```\n{_combined}\n```" if _combined else ""
                if _overall_ok:
                    set_action_log(f"**{_label}** — done.{_review_link}{_code}")
                else:
                    set_action_log(f"**{_label}** — failed.{_code}")
            elif _has_progress:
                _full_cmd = [MOGRADER_BIN] + _cmd + ["--progress"]
                _proc = sp.Popen(
                    _full_cmd,
                    stdout=sp.PIPE,
                    stderr=sp.PIPE,
                    text=True,
                    bufsize=1,
                    cwd=COURSE_DIR,
                )
                _bar_ctx = None
                _bar_inner = None
                _results_data = None
                for _line in iter(_proc.stderr.readline, ""):
                    _line = _line.strip()
                    if not _line.startswith("{"):
                        continue
                    try:
                        _msg = _json.loads(_line)
                    except _json.JSONDecodeError:
                        continue
                    if _msg.get("event") == "start":
                        _bar_ctx = mo.status.progress_bar(
                            total=_msg["total"], title=_label, remove_on_exit=True
                        )
                        _bar_inner = _bar_ctx.__enter__()
                    elif _msg.get("event") == "sandbox_start":
                        if _bar_inner is not None:
                            _bar_inner.update(
                                increment=0, subtitle="installing dependencies…"
                            )
                    elif _msg.get("event") == "sandbox_done":
                        if _bar_inner is not None:
                            _bar_inner.update(
                                increment=0, subtitle="running source notebook…"
                            )
                    elif _msg.get("event") == "check" and _bar_inner is not None:
                        _icon = "\u2705" if _msg.get("status") == "PASS" else "\u274c"
                        _bar_inner.update(
                            increment=0,
                            subtitle=f"{_icon} {_msg['label']}",
                        )
                    elif _msg.get("event") == "progress" and _bar_inner is not None:
                        _bar_inner.update(subtitle=f"{_msg['notebook']}")
                    elif _msg.get("event") == "results":
                        _results_data = _msg
                if _bar_ctx is not None:
                    _bar_ctx.__exit__(None, None, None)
                _proc.wait()

                # Build display: prefer structured results table, fall back to stdout
                if _results_data is not None:
                    _STATUS = {
                        "PASS": "\u2705",
                        "FAIL": "\u274c",
                        "WAIT": "\u23f3",
                        "ERR": "\u26a0\ufe0f",
                        "---": "\u2014",
                        "EXPORT_FAILED": "\u274c",
                    }
                    _labels = _results_data["labels"]
                    _trows = _results_data["rows"]
                    _has_marks = any("auto_mark" in r for r in _trows)
                    _hdr = "| Notebook | " + " | ".join(_labels)
                    if _has_marks:
                        _hdr += " | Marks"
                    _hdr += " | Errors |"
                    _sep = "|" + "|".join(["---"] * (_hdr.count("|") - 1)) + "|"
                    _lines = [_hdr, _sep]
                    for _r in _trows:
                        _cells = [_r["notebook"]]
                        for _l in _labels:
                            _st = _r["checks"].get(_l, "---")
                            _cells.append(_STATUS.get(_st, _st))
                        if _has_marks:
                            if _r.get("auto_mark") is not None:
                                _cells.append(f"{_r['auto_mark']}/{_r['total_mark']}")
                            else:
                                _cells.append("\u2014")
                        _cells.append(str(_r["cell_errors"]))
                        _lines.append("| " + " | ".join(_cells) + " |")
                    _table_md = "\n".join(_lines)
                    if _proc.returncode == 0:
                        set_action_log(
                            f"**{_label}** — done.{_review_link}\n\n{_table_md}"
                        )
                    else:
                        set_action_log(
                            f"**{_label}** — exited with code "
                            f"{_proc.returncode}.\n\n{_table_md}"
                        )
                else:
                    _stdout = (_proc.stdout.read() if _proc.stdout else "").strip()
                    _code = f"\n```\n{_stdout}\n```" if _stdout else ""
                    if _proc.returncode == 0:
                        set_action_log(f"**{_label}** — done.{_review_link}{_code}")
                    else:
                        set_action_log(
                            f"**{_label}** — exited with code "
                            f"{_proc.returncode}.{_code}"
                        )
            else:
                with mo.status.spinner(title=_label, remove_on_exit=True):
                    _proc = sp.run(
                        [MOGRADER_BIN] + _cmd,
                        capture_output=True,
                        text=True,
                        timeout=600,
                        cwd=COURSE_DIR,
                    )
                _output = (_proc.stdout + _proc.stderr).strip()
                _code = f"\n```\n{_output}\n```" if _output else ""
                if _proc.returncode == 0:
                    set_action_log(f"**{_label}** — done.{_review_link}{_code}")
                else:
                    set_action_log(
                        f"**{_label}** — exited with code {_proc.returncode}.{_code}"
                    )
        except sp.TimeoutExpired:
            set_action_log(f"**{_label}** — timed out after 600s.")
        except Exception:
            set_action_log(f"**{_label}** — error.\n```\n{_tb.format_exc()}\n```")

        set_data_version(lambda v: v + 1)
        set_pending_action(None)
    return


if __name__ == "__main__":
    app.run()
