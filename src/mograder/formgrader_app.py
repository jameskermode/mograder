import marimo

__generated_with = "0.20.0"
app = marimo.App(width="medium")


@app.cell
def _():
    import io
    import os
    import subprocess as sp
    import sys
    import zipfile
    from pathlib import Path

    import marimo as mo

    import matplotlib.pyplot as plt
    import seaborn as sns

    from mograder.config import load_config
    from mograder.formgrader import DirNames
    from mograder.gradebook import Gradebook
    from mograder.moodle_api import load_cached_token

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
    moodle_assign_names = {
        a["name"]
        for a in (MOGRADER_CONFIG.assignments or MOGRADER_CONFIG.moodle_assignments)
    }

    def is_instructor() -> bool:
        """Check if the current user is an instructor.

        Reads user identity from mo.app_meta().request.user, which is
        populated by TrustedProxyAuth middleware in ASGI mode.
        Defaults to True for local/non-ASGI use (no middleware).
        """
        req = mo.app_meta().request
        user = req.user if req else {}
        return user.get("is_instructor", True)

    def get_user_display() -> str:
        """Return 'username@host' for display in the navbar."""
        req = mo.app_meta().request
        user = req.user if req else {}
        username = user.get("username", "")
        if not username:
            username = os.environ.get("USER", "local")
        hostname = socket.gethostname().split(".")[0]
        return f"{username}@{hostname}"

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
        get_user_display,
        is_instructor,
        moodle_assign_names,
        io,
        mo,
        os,
        plt,
        sns,
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
    return (
        get_action_log,
        get_data_version,
        get_grading_index,
        get_grading_inputs,
        get_pending_action,
        get_selected,
        set_action_log,
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
    from mograder.formgrader import scan_course

    _refresh = refresh_btn.value, get_data_version()
    assignments = scan_course(COURSE_DIR, dir_names=DIR_NAMES, gradebook=GRADEBOOK)
    return assignments, scan_course


@app.cell
def _(assignments, get_selected, mo, set_selected):
    _options = {a.name: a.name for a in assignments}
    _current = get_selected()
    assignment_dropdown = mo.ui.dropdown(
        options=_options,
        value=_current if _current in _options else None,
        label="Assignment",
        on_change=lambda val: set_selected(val or ""),
    )
    # Second independent dropdown bound to the same state for the Grading tab
    assignment_dropdown_grading = mo.ui.dropdown(
        options=_options,
        value=_current if _current in _options else None,
        label="Assignment",
        on_change=lambda val: set_selected(val or ""),
    )
    return assignment_dropdown, assignment_dropdown_grading


@app.cell
def _(
    COURSE_DIR,
    DIR_NAMES,
    MOGRADER_CONFIG,
    TRANSPORT_READY,
    TRANSPORT_TYPE,
    moodle_assign_names,
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
        sp.Popen([sys.executable, "-m", "marimo", mode, "--sandbox", str(path)])
        set_action_log(f"Opened **{mode}** for `{label}`")

    # --- build per-assignment buttons ---
    _src_btns_list = []
    _rel_btns_list = []
    _rel_dl_list = []
    _imp_list = []
    _gen = []
    _auto = []
    _fb = []
    _fb_csv_dl_list = []
    _fb_zip_dl_list = []
    _auto_upload_list = []
    _fetch_sub_list = []
    _upload_fb_list = []

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
                        label="\u270f\ufe0f",
                        on_change=lambda _, p=_p, n=_n: _open_marimo("edit", p, n),
                        tooltip=f"Edit {_a.source_path}",
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
                        label="\u270f\ufe0f",
                        on_change=lambda _, p=_p2, n=_n2: _open_marimo("edit", p, n),
                        tooltip=f"Edit {_a.release_path}",
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
                mo.download(data=_make_zip, filename=_zip_name, label="\U0001f4e6")
            )
        else:
            _rel_btns_list.append(mo.md("\u2013"))
            _rel_dl_list.append(None)

        # Import — file upload for CSV + ZIP (hidden when sync transport available)
        if not TRANSPORT_READY:
            _imp_list.append(
                mo.ui.file(
                    filetypes=[".csv", ".zip"],
                    multiple=True,
                    label="📥",
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
                    label="\u2192",
                    on_change=lambda _, cmd=_gen_cmd, n=_n3: set_pending_action(
                        {"cmd": cmd, "label": f"generate {n}"}
                    ),
                    tooltip="Generate",
                )
            )
        else:
            _gen.append(mo.ui.button(label="\u2192", disabled=True, tooltip="Generate"))

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
                    label="\u2192",
                    on_change=lambda _, c=_cmd, n=_n4: set_pending_action(
                        {"cmd": c, "label": f"autograde {n}"}
                    ),
                    tooltip="Autograde",
                )
            )
        else:
            _auto.append(
                mo.ui.button(label="\u2192", disabled=True, tooltip="Autograde")
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
                    label="\u2192",
                    on_change=lambda _, c=_sub_cmds, n=_n5: set_pending_action(
                        {"cmd": c, "label": f"export {n}"}
                    ),
                    tooltip=_tooltip,
                )
            )
        else:
            _fb.append(
                mo.ui.button(label="\u2192", disabled=True, tooltip="Export Moodle")
            )

        # Feedback downloads — CSV and ZIP if they exist
        _export_csv = _export_dir / f"{_a.name}.csv"
        if _export_csv.is_file():
            _cp = _export_csv
            _cn = _export_csv.name

            def _read_fb_csv(p=_cp):
                return p.read_bytes()

            _fb_csv_dl_list.append(
                mo.download(data=_read_fb_csv, filename=_cn, label="📋")
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
                mo.download(data=_read_fb_zip, filename=_zn, label="\U0001f4e6")
            )
        else:
            _fb_zip_dl_list.append(None)

        # Autograded upload — ZIP file upload per assignment (hidden when sync available)
        if not TRANSPORT_READY:
            _auto_upload_list.append(
                mo.ui.file(
                    filetypes=[".zip"],
                    multiple=False,
                    label="📤",
                    kind="button",
                )
            )
        else:
            _auto_upload_list.append(mo.md(""))

        # Fetch submissions via transport (instructor only)
        _sub_out = str(COURSE_DIR / DIR_NAMES.submitted / _a.name)
        if TRANSPORT_READY and _a.name in moodle_assign_names and is_instructor():
            _n_fetch = _a.name
            _fetch_sub_list.append(
                mo.ui.button(
                    label="⬇",
                    on_change=lambda _, n=_n_fetch, o=_sub_out: set_pending_action(
                        {
                            "cmd": [TRANSPORT_TYPE, "fetch-submissions", n, "-o", o],
                            "label": f"fetch submissions {n}",
                        }
                    ),
                    tooltip="Fetch submissions",
                )
            )
        else:
            _fetch_sub_list.append(
                mo.ui.button(
                    label="⬇", disabled=True, tooltip="Fetch submissions"
                )
            )

        # Upload grades & feedback via transport (instructor only)
        _fb_dir_path = COURSE_DIR / DIR_NAMES.feedback / _a.name
        _has_feedback = _fb_dir_path.is_dir() and any(_fb_dir_path.glob("*.html"))
        if TRANSPORT_READY and _a.name in moodle_assign_names and _has_feedback and is_instructor():
            _n_up = _a.name
            _fb_d = str(_fb_dir_path)
            _upload_fb_list.append(
                mo.ui.button(
                    label="⬆",
                    on_change=lambda _, n=_n_up, d=_fb_d: set_pending_action(
                        {
                            "cmd": [
                                TRANSPORT_TYPE,
                                "upload-feedback",
                                n,
                                "--feedback-dir",
                                d,
                            ],
                            "label": f"upload feedback {n}",
                        }
                    ),
                    tooltip="Upload grades & feedback",
                )
            )
        else:
            _upload_fb_list.append(
                mo.ui.button(
                    label="⬆",
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
        if TRANSPORT_READY:
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

        # Release column: combine edit + download
        _rel_items = [_rel_cell]
        if _rel_dl_list[_i] is not None and rel_downloads is not None:
            _rel_items.append(rel_downloads[_rel_dl_idx])
            _rel_dl_idx += 1
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
            f"{_a.num_graded}/{_a.num_autograded}"
            if _a.num_autograded
            else "\u2013"
        )

        _row = {
            "Assignment": mo.md(_name),
            "Source": _src_cell,
            "→": gen_btns[_i],
            "Release": _rel_combined,
        }
        if not TRANSPORT_READY:
            _row["Import"] = _imp_list[_i]
        _row["Submitted"] = _sub_cell
        _row["→ "] = auto_btns[_i]
        if not TRANSPORT_READY:
            _row["Graded"] = mo.hstack(
                [mo.md(_graded_text), _auto_upload_list[_i]],
                justify="start",
                gap=0.25,
            )
        else:
            _row["Graded"] = mo.md(_graded_text)
        _row["Export"] = _export_cell
        _row["Feedback"] = mo.md(_fb_text)
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
    from mograder.moodle import extract_submissions, read_moodle_worksheet

    for _i, _a in enumerate(assignments):
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
    assignment_dropdown,
    get_data_version,
    get_selected,
    mo,
    plt,
    refresh_btn,
    set_action_log,
    sns,
    sp,
    sys,
):
    from mograder.formgrader import scan_submissions

    _refresh = refresh_btn.value, get_data_version()
    _selected = get_selected()

    if _selected:
        _subs = scan_submissions(
            COURSE_DIR, _selected, dir_names=DIR_NAMES, gradebook=GRADEBOOK
        )

        def _open_editor(path):
            sp.Popen([sys.executable, "-m", "marimo", "edit", "--sandbox", str(path)])
            set_action_log(f"Opened editor for **{path.name}**")

        _edit_list = []
        for _s in _subs:
            if MOGRADER_CONFIG.no_edit:
                _edit_list.append(mo.ui.button(label="✏️", disabled=True))
            elif _s.autograded_path:
                _p = _s.autograded_path
                _edit_list.append(
                    mo.ui.button(
                        label="✏️",
                        on_change=lambda _, p=_p: _open_editor(p),
                    )
                )
            else:
                _edit_list.append(mo.ui.button(label="✏️", disabled=True))

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
            _fig, _axes = plt.subplots(1, 3, figsize=(12, 3))
            for _ax, _data, _label in zip(
                _axes,
                [_auto_marks, _manual_marks, _total_marks],
                ["Auto Mark", "Manual Mark", "Total"],
            ):
                if _data:
                    sns.histplot(_data, bins=8, ax=_ax, color="#4C78A8")
                _ax.set_xlabel(_label)
                _ax.set_ylabel("Count")
            _fig.tight_layout()
            _histogram = mo.as_html(_fig)
            plt.close(_fig)

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
    from mograder.moodle import read_moodle_worksheet as _read_ws

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
    assignments,
    mo,
    plt,
    refresh_btn,
    sns,
    students_controls,
    students_name_lookup,
):
    from mograder.formgrader import collect_student_marks, get_max_marks

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
        _fig, _ax = plt.subplots(figsize=(5, 2.5))
        sns.histplot(_averages, bins=8, ax=_ax, color="#4C78A8")
        _ax.set_xlabel("Average %")
        _ax.set_ylabel("Count")
        _fig.tight_layout()
        _mean = sum(_averages) / len(_averages)
        _var = sum((a - _mean) ** 2 for a in _averages) / len(_averages)
        _std = _var**0.5
        _histogram = mo.vstack(
            [
                mo.as_html(_fig),
                mo.md(
                    f"**Mean:** {_mean:.1f}% | **Std:** {_std:.1f} "
                    f"| **Min:** {min(_averages)}% | **Max:** {max(_averages)}%"
                ),
            ]
        )
        plt.close(_fig)

    students_content = mo.vstack([students_controls, _table, _histogram])
    return collect_student_marks, get_max_marks, students_content


@app.cell
def _(COURSE_DIR, DIR_NAMES, GRADEBOOK, get_selected, refresh_btn, set_grading_index):
    from mograder.formgrader import scan_submissions as _scan_subs

    _ = refresh_btn.value

    # Use the assignment selected in the Assignments tab
    _sel = get_selected()
    if _sel:
        grading_subs = _scan_subs(
            COURSE_DIR, _sel, dir_names=DIR_NAMES, gradebook=GRADEBOOK
        )
        grading_subs = [s for s in grading_subs if s.autograded_path]
    else:
        grading_subs = []
    # Reset index when assignment changes
    set_grading_index(0)
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
    from mograder.cells import extract_marking_scale as _extract_scale
    from mograder.cells import parse_auto_marks as _parse_auto
    from mograder.cells import parse_gta_feedback as _parse_fb

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

        # Compute auto_max (marks available for auto-graded questions)
        if _marks_meta and _auto_mark is not None:
            _db_sub2 = (
                GRADEBOOK.get_submission(
                    grading_assignment_name, grading_current_sub.student
                )
                if GRADEBOOK
                else None
            )
            if _db_sub2:
                _check_keys = {
                    c["label"].split(":")[0].strip() for c in _db_sub2["check_results"]
                }
                _auto_max = sum(v for k, v in _marks_meta.items() if k in _check_keys)
            else:
                _auto_max = 0
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

        # Store scaling info for _save_current
        grading_scale_info = {
            "auto_mark": _auto_mark,
            "auto_max": _auto_max,
            "manual_available": _manual_available,
            "max_mark": _max_mark,
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
    set_data_version,
    set_grading_index,
):
    import re as _re
    from mograder.cells import write_gta_feedback as _write_fb

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
                return  # Don't save — UI shows validation warning

            # Scale slider (0-100) to manual contribution
            _manual_available = grading_scale_info["manual_available"]
            _auto_mark = grading_scale_info["auto_mark"]
            if _manual_available > 0 and _auto_mark is not None:
                _manual_contribution = round(_slider_val / 100 * _manual_available)
                _total = _auto_mark + _manual_contribution
            else:
                _total = _slider_val

            # Write to DB if available (store raw slider as manual_mark,
            # pass computed total)
            if GRADEBOOK is not None and grading_assignment_name:
                GRADEBOOK.save_manual_grade(
                    grading_assignment_name,
                    grading_current_sub.student,
                    _slider_val,
                    _feedback,
                    total_mark=_total,
                )
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
        if _html_path.exists():
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
        _kind = (
            "danger" if "exited with code" in _log or "timed out" in _log else "info"
        )
        action_log_content = mo.vstack([mo.callout(mo.md(_log), kind=_kind), clear_btn])
    else:
        action_log_content = mo.md("")
    return (action_log_content,)


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
    assignments_content,
    get_user_display,
    grading_content,
    mo,
    new_btn,
    new_name_input,
    refresh_btn,
    students_content,
    submissions_content,
):
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
            mo.hstack(
                [
                    mo.md("# mograder"),
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
    set_action_log,
    set_data_version,
    set_pending_action,
    sp,
):
    import json as _json
    import traceback as _tb

    _action = get_pending_action()
    if _action is not None and _action.get("action") == "new_assignment":
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
        # Compound action: list of sub-commands to run sequentially
        _is_compound = _cmd and isinstance(_cmd[0], list)
        # Commands that support --progress with JSON events on stderr
        _PROGRESS_CMDS = {"autograde", "generate"}
        _has_progress = (
            not _is_compound and _cmd and _cmd[0] in _PROGRESS_CMDS
        )

        try:
            if _is_compound:
                _combined_output = []
                _overall_ok = True
                with mo.status.spinner(title=_label, remove_on_exit=True):
                    for _sub_cmd in _cmd:
                        _sub_has_progress = (
                            _sub_cmd and _sub_cmd[0] in _PROGRESS_CMDS
                        )
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
                    set_action_log(f"**{_label}** — done.{_code}")
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
                for _line in _proc.stderr:
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
                        set_action_log(f"**{_label}** — done.\n\n{_table_md}")
                    else:
                        set_action_log(
                            f"**{_label}** — exited with code "
                            f"{_proc.returncode}.\n\n{_table_md}"
                        )
                else:
                    _stdout = (_proc.stdout.read() if _proc.stdout else "").strip()
                    _code = f"\n```\n{_stdout}\n```" if _stdout else ""
                    if _proc.returncode == 0:
                        set_action_log(f"**{_label}** — done.{_code}")
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
                    set_action_log(f"**{_label}** — done.{_code}")
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
