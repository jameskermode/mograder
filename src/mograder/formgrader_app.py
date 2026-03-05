import marimo

__generated_with = "0.20.0"
app = marimo.App(width="medium")


@app.cell
def _():
    import os
    import subprocess as sp
    import sys
    from pathlib import Path

    import marimo as mo

    import matplotlib.pyplot as plt
    import seaborn as sns

    from mograder.config import load_config
    from mograder.formgrader import DirNames

    COURSE_DIR = Path(os.environ.get("MOGRADER_COURSE_DIR", ".")).resolve()
    MOGRADER_CONFIG = load_config(COURSE_DIR)
    DIR_NAMES = DirNames(
        source=MOGRADER_CONFIG.source_dir,
        release=MOGRADER_CONFIG.release_dir,
        submitted=MOGRADER_CONFIG.submitted_dir,
        autograded=MOGRADER_CONFIG.autograded_dir,
        feedback=MOGRADER_CONFIG.feedback_dir,
    )
    return COURSE_DIR, DIR_NAMES, MOGRADER_CONFIG, Path, mo, os, plt, sns, sp, sys


@app.cell
def _(mo):
    get_selected, set_selected = mo.state("")
    get_action_log, set_action_log = mo.state("")
    get_pending_action, set_pending_action = mo.state(None)
    get_grading_index, set_grading_index = mo.state(0)
    get_data_version, set_data_version = mo.state(0)
    return (
        get_action_log,
        get_data_version,
        get_grading_index,
        get_pending_action,
        get_selected,
        set_action_log,
        set_data_version,
        set_grading_index,
        set_pending_action,
        set_selected,
    )


@app.cell
def _(COURSE_DIR, mo):
    refresh_btn = mo.ui.button(label="Refresh")
    mo.md(f"# mograder formgrader\n\n`{COURSE_DIR}`")
    return (refresh_btn,)


@app.cell
def _(COURSE_DIR, DIR_NAMES, get_data_version, refresh_btn):
    from mograder.formgrader import scan_course

    _refresh = refresh_btn.value, get_data_version()
    assignments = scan_course(COURSE_DIR, dir_names=DIR_NAMES)
    return assignments, scan_course


@app.cell
def _(assignments, mo, set_selected):
    assignment_dropdown = mo.ui.dropdown(
        options={a.name: a.name for a in assignments},
        label="Assignment",
        on_change=lambda val: set_selected(val or ""),
    )
    return (assignment_dropdown,)


@app.cell
def _(
    COURSE_DIR,
    DIR_NAMES,
    assignments,
    get_selected,
    mo,
    set_action_log,
    set_pending_action,
    sp,
    sys,
):
    def _open_marimo(mode, path, label):
        sp.Popen([sys.executable, "-m", "marimo", mode, "--sandbox", str(path)])
        set_action_log(f"Opened **{mode}** for `{label}`")

    # --- build per-assignment buttons ---
    _src_btns_list = []
    _rel_btns_list = []
    _gen = []
    _auto = []
    _fb = []

    for _a in assignments:
        # Source — edit source notebook
        if _a.source_path:
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
            _p2 = _a.release_path
            _n2 = _a.name
            _rel_btns_list.append(
                mo.ui.button(
                    label="\u270f\ufe0f",
                    on_change=lambda _, p=_p2, n=_n2: _open_marimo("run", p, n),
                    tooltip=f"Preview {_a.release_path}",
                )
            )
        else:
            _rel_btns_list.append(mo.md("\u2013"))

        # Generate
        if _a.source_path:
            _src = str(_a.source_path)
            _out = str(COURSE_DIR / DIR_NAMES.release)
            _n3 = _a.name
            _gen.append(
                mo.ui.button(
                    label="\u2192",
                    on_change=lambda _, s=_src, o=_out, n=_n3: set_pending_action(
                        {"cmd": ["generate", s, "-o", o], "label": f"generate {n}"}
                    ),
                    tooltip="Generate",
                )
            )
        else:
            _gen.append(mo.ui.button(label="\u2192", disabled=True, tooltip="Generate"))

        # Autograde
        _sub_dir = COURSE_DIR / DIR_NAMES.submitted / _a.name
        if _sub_dir.is_dir() and any(_sub_dir.glob("*.py")):
            _files = [str(f) for f in sorted(_sub_dir.glob("*.py"))]
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

        # Feedback export
        _auto_dir = COURSE_DIR / DIR_NAMES.autograded / _a.name
        if _auto_dir.is_dir() and any(_auto_dir.glob("*.py")):
            _ffiles = [str(f) for f in sorted(_auto_dir.glob("*.py"))]
            _cmd2 = ["feedback"] + _ffiles
            _n5 = _a.name
            _fb.append(
                mo.ui.button(
                    label="\u2192",
                    on_change=lambda _, c=_cmd2, n=_n5: set_pending_action(
                        {"cmd": c, "label": f"feedback {n}"}
                    ),
                    tooltip="Export feedback",
                )
            )
        else:
            _fb.append(
                mo.ui.button(label="\u2192", disabled=True, tooltip="Export feedback")
            )

    # Wrap interactive buttons in mo.ui.array for marimo state tracking
    _src_ui = [e for e in _src_btns_list if not isinstance(e, mo.Html)]
    _rel_ui = [e for e in _rel_btns_list if not isinstance(e, mo.Html)]
    src_btns = mo.ui.array(_src_ui) if _src_ui else None
    rel_btns = mo.ui.array(_rel_ui) if _rel_ui else None
    gen_btns = mo.ui.array(_gen)
    auto_btns = mo.ui.array(_auto)
    fb_btns = mo.ui.array(_fb)

    # Map array indices back to row positions for mixed button/md lists
    _src_idx = 0
    _rel_idx = 0

    # --- build merged assignments + grades table ---
    _rows = []
    _selected_name = get_selected()
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

        # Release column: ✅ + preview button or –
        if isinstance(_rel_btns_list[_i], mo.Html):
            _rel_cell = _rel_btns_list[_i]
        else:
            _rel_cell = mo.hstack(
                [mo.md("\u2705"), rel_btns[_rel_idx]], justify="start", gap=0.25
            )
            _rel_idx += 1

        # Submitted column: count only
        _sub_cell = mo.md(str(_a.num_submitted))

        # Feedback column: text only
        _fb_text = (
            f"{_a.num_feedback}/{_a.num_autograded}" if _a.num_autograded else "\u2013"
        )

        _name = f"**{_a.name}**" if _a.name == _selected_name else _a.name

        _rows.append(
            {
                "Assignment": mo.md(_name),
                "Source": _src_cell,
                "Generate": gen_btns[_i],
                "Release": _rel_cell,
                "Submitted": _sub_cell,
                "Autograde": auto_btns[_i],
                "Autograded": "\u2705" if _a.num_autograded > 0 else "\u2013",
                "Graded": f"{_a.num_graded}/{_a.num_autograded}"
                if _a.num_autograded
                else "\u2013",
                "Export FB": fb_btns[_i],
                "Feedback": mo.md(_fb_text),
            }
        )

    assignments_content = (
        mo.ui.table(_rows)
        if _rows
        else mo.md(
            "_No assignments found. Check that the course directory contains "
            "`source/`, `submitted/`, etc._"
        )
    )
    return (
        assignments_content,
        src_btns,
        rel_btns,
        gen_btns,
        auto_btns,
        fb_btns,
    )


@app.cell
def _(
    COURSE_DIR,
    DIR_NAMES,
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
        _subs = scan_submissions(COURSE_DIR, _selected, dir_names=DIR_NAMES)

        def _open_editor(path):
            sp.Popen([sys.executable, "-m", "marimo", "edit", "--sandbox", str(path)])
            set_action_log(f"Opened editor for **{path.name}**")

        _edit_list = []
        for _s in _subs:
            if _s.autograded_path:
                _p = _s.autograded_path
                _edit_list.append(
                    mo.ui.button(
                        label="Edit",
                        on_change=lambda _, p=_p: _open_editor(p),
                    )
                )
            else:
                _edit_list.append(mo.ui.button(label="Edit", disabled=True))

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

        # Seaborn histogram of marks
        _marks = [_s.mark for _s in _subs if _s.mark is not None]
        _histogram = mo.md("")
        if len(_marks) >= 2:
            _fig, _ax = plt.subplots(figsize=(5, 2.5))
            sns.histplot(_marks, bins=8, ax=_ax, color="#4C78A8")
            _ax.set_xlabel("Mark")
            _ax.set_ylabel("Count")
            _fig.tight_layout()
            _mean = sum(_marks) / len(_marks)
            _var = sum((m - _mean) ** 2 for m in _marks) / len(_marks)
            _std = _var**0.5
            _histogram = mo.vstack(
                [
                    mo.as_html(_fig),
                    mo.md(
                        f"**Mean:** {_mean:.1f} | **Std:** {_std:.1f} "
                        f"| **Min:** {min(_marks)} | **Max:** {max(_marks)}"
                    ),
                ]
            )
            plt.close(_fig)

        submissions_content = mo.vstack(
            [
                mo.md(f"## Submissions: {_selected}"),
                mo.ui.table(_rows, selection=None)
                if _rows
                else mo.md("_No submissions found._"),
                _histogram,
            ]
        )
    else:
        edit_btns = mo.ui.array([])
        submissions_content = mo.md("_Select an assignment in the Assignments tab._")
    return edit_btns, scan_submissions, submissions_content


@app.cell
def _(mo):
    show_names = mo.ui.switch(label="Show names")
    moodle_file = mo.ui.file(label="Moodle CSV", filetypes=[".csv"])
    students_controls = mo.hstack([show_names, moodle_file], justify="start", gap=1)
    return moodle_file, show_names, students_controls


@app.cell
def _(COURSE_DIR, MOGRADER_CONFIG, Path, moodle_file, show_names):
    if show_names.value:
        from mograder.moodle import read_moodle_worksheet as _read_ws

        _match_col = MOGRADER_CONFIG.moodle_match_column
        _name_col = MOGRADER_CONFIG.moodle_name_column
        _rows = None

        # Priority 1: uploaded file
        if moodle_file.value:
            _bytes = moodle_file.value[0].contents
            _tmp = Path("/tmp/_mograder_moodle_upload.csv")
            _tmp.write_bytes(_bytes)
            _, _rows = _read_ws(_tmp)
        # Priority 2: config moodle_csv
        elif MOGRADER_CONFIG.moodle_csv:
            _csv_path = COURSE_DIR / MOGRADER_CONFIG.moodle_csv
            if _csv_path.is_file():
                _, _rows = _read_ws(_csv_path)

        if _rows is not None:
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
    assignments,
    mo,
    name_lookup,
    plt,
    refresh_btn,
    sns,
    students_controls,
):
    from mograder.formgrader import collect_student_marks, get_max_marks

    _ = refresh_btn.value
    _student_marks = collect_student_marks(COURSE_DIR, assignments, dir_names=DIR_NAMES)
    _max_marks = get_max_marks(COURSE_DIR, assignments, dir_names=DIR_NAMES)
    _assignment_names = [a.name for a in assignments]

    _rows = []
    _averages = []
    for _sid in sorted(_student_marks):
        _display = name_lookup.get(_sid, _sid)
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
def _(COURSE_DIR, DIR_NAMES, get_selected, refresh_btn, set_grading_index):
    from mograder.formgrader import scan_submissions as _scan_subs

    _ = refresh_btn.value

    # Use the assignment selected in the Assignments tab
    _sel = get_selected()
    if _sel:
        grading_subs = _scan_subs(COURSE_DIR, _sel, dir_names=DIR_NAMES)
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
def _(grading_current_sub, mo):
    from mograder.cells import parse_auto_marks as _parse_auto
    from mograder.cells import parse_gta_feedback as _parse_fb

    # Create mark + feedback inputs, re-reading the .py file for fresh data
    if grading_current_sub is not None and grading_current_sub.autograded_path:
        _lines = grading_current_sub.autograded_path.read_text().splitlines(
            keepends=True
        )
        _mark, _feedback_text = _parse_fb(_lines)
        _auto_mark = _parse_auto(_lines)

        _existing_mark = ""
        if _mark is not None:
            if _auto_mark is not None:
                _existing_mark = str(_mark)
            else:
                _existing_mark = str(_mark)

        _mark_label = "Mark (0-100)"
        if _auto_mark is not None:
            _mark_label = "Manual mark"

        grading_mark_input = mo.ui.text(
            value=_existing_mark,
            label=_mark_label,
            full_width=False,
        )
        grading_feedback_input = mo.ui.text_area(
            value=_feedback_text or "",
            label="Feedback",
            rows=8,
            full_width=True,
            debounce=300,
        )
        grading_auto_info = (
            f"**Auto marks:** {_auto_mark}" if _auto_mark is not None else ""
        )
    else:
        grading_mark_input = mo.ui.text(value="", label="Mark")
        grading_feedback_input = mo.ui.text_area(value="", label="Feedback")
        grading_auto_info = ""
    return grading_auto_info, grading_feedback_input, grading_mark_input


@app.cell
def _(
    grading_auto_info,
    grading_current_sub,
    grading_feedback_input,
    grading_mark_input,
    mo,
):
    # Build form layout — must NOT access .value here to avoid re-renders
    if grading_current_sub is not None:
        grading_form = mo.vstack(
            [
                mo.md(grading_auto_info) if grading_auto_info else mo.md(""),
                mo.hstack([grading_mark_input]),
                grading_feedback_input,
            ]
        )
    else:
        grading_form = mo.md("_No submission selected._")
    return (grading_form,)


@app.cell
def _(mo):
    grading_show_names = mo.ui.switch(label="Show names")
    return (grading_show_names,)


@app.cell
def _(
    get_grading_index,
    grading_assignment_name,
    grading_current_sub,
    grading_feedback_input,
    grading_mark_input,
    grading_show_names,
    grading_subs,
    mo,
    name_lookup,
    set_data_version,
    set_grading_index,
):
    from mograder.cells import write_gta_feedback as _write_fb

    def _save_current():
        if grading_current_sub is not None and grading_current_sub.autograded_path:
            _mark_str = grading_mark_input.value.strip()
            _mark = int(_mark_str) if _mark_str else None
            _feedback = grading_feedback_input.value or ""
            _write_fb(grading_current_sub.autograded_path, _mark, _feedback)
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
                mo.md(f"**{grading_assignment_name}**")
                if grading_assignment_name
                else mo.md(""),
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
        grading_nav = mo.md("_Select an assignment in the Assignments tab._")
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
    grading_form,
    grading_nav,
    grading_preview,
    grading_subs,
    mo,
):
    grading_content = (
        mo.vstack(
            [
                grading_nav,
                grading_form,
                grading_preview,
            ]
        )
        if grading_subs
        else mo.md(
            "_Select an assignment with autograded submissions in the Assignments tab._"
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
def _(
    action_log_content,
    assignment_dropdown,
    assignments_content,
    grading_content,
    mo,
    refresh_btn,
    students_content,
    submissions_content,
):
    mo.vstack(
        [
            mo.hstack([assignment_dropdown, refresh_btn], justify="start", gap=1),
            mo.ui.tabs(
                {
                    "Assignments": assignments_content,
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
    if _action is not None:
        _cmd, _label = _action["cmd"], _action["label"]
        _is_autograde = _cmd and _cmd[0] == "autograde"

        try:
            if _is_autograde:
                _full_cmd = ["mograder"] + _cmd + ["--progress"]
                _proc = sp.Popen(
                    _full_cmd, stdout=sp.PIPE, stderr=sp.PIPE, text=True, bufsize=1
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
                        ["mograder"] + _cmd,
                        capture_output=True,
                        text=True,
                        timeout=600,
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
