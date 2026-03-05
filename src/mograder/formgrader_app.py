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

    COURSE_DIR = Path(os.environ.get("MOGRADER_COURSE_DIR", ".")).resolve()
    return COURSE_DIR, Path, mo, os, plt, sns, sp, sys


@app.cell
def _(mo):
    get_selected, set_selected = mo.state("")
    get_action_log, set_action_log = mo.state("")
    get_pending_action, set_pending_action = mo.state(None)
    return (
        get_action_log,
        get_pending_action,
        get_selected,
        set_action_log,
        set_pending_action,
        set_selected,
    )


@app.cell
def _(COURSE_DIR, mo):
    refresh_btn = mo.ui.button(label="Refresh")
    mo.hstack(
        [
            mo.md(f"# mograder formgrader\n\n`{COURSE_DIR}`"),
            refresh_btn,
        ],
        justify="space-between",
        align="start",
    )
    return (refresh_btn,)


@app.cell
def _(COURSE_DIR, refresh_btn):
    from mograder.formgrader import scan_course

    _ = refresh_btn.value
    assignments = scan_course(COURSE_DIR)
    return assignments, scan_course


@app.cell
def _(COURSE_DIR, assignments, refresh_btn):
    from mograder.feedback import collect_grades as _collect_grades

    _ = refresh_btn.value
    _stats = {}
    for _a in assignments:
        _d = COURSE_DIR / "autograded" / _a.name
        if not _d.is_dir():
            continue
        _nbs = sorted(_d.glob("*.py"))
        if not _nbs:
            continue
        _grades = _collect_grades(_nbs)
        _marks = [g["mark"] for g in _grades if g["mark"] is not None]
        if _marks:
            _mean = sum(_marks) / len(_marks)
            _var = (
                sum((m - _mean) ** 2 for m in _marks) / len(_marks)
                if len(_marks) > 1
                else 0
            )
            _stats[_a.name] = {
                "mean": _mean,
                "std": _var**0.5,
                "min": min(_marks),
                "max": max(_marks),
            }
    grade_stats = _stats
    return (grade_stats,)


@app.cell
def _(
    COURSE_DIR,
    assignments,
    grade_stats,
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
            _out = str(COURSE_DIR / "release")
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
        _sub_dir = COURSE_DIR / "submitted" / _a.name
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
        _auto_dir = COURSE_DIR / "autograded" / _a.name
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
    for _i, _a in enumerate(assignments):
        _st = grade_stats.get(_a.name, {})

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

        _rows.append(
            {
                "Assignment": _a.name,
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
                "Mean": f"{_st['mean']:.1f}" if _st else "\u2013",
                "Std": f"{_st['std']:.1f}" if _st else "\u2013",
            }
        )

    assignments_table = (
        mo.ui.table(
            _rows,
            selection="single",
            label="Select an assignment to view submissions",
        )
        if _rows
        else None
    )
    assignments_content = (
        mo.vstack([assignments_table])
        if assignments_table
        else mo.md(
            "_No assignments found. Check that the course directory contains "
            "`source/`, `submitted/`, etc._"
        )
    )
    return (
        assignments_content,
        assignments_table,
        src_btns,
        rel_btns,
        gen_btns,
        auto_btns,
        fb_btns,
    )


@app.cell
def _(assignments_table, set_selected):
    if assignments_table is not None and assignments_table.value:
        _sel = assignments_table.value[0]
        set_selected(_sel["Assignment"])
    return


@app.cell
def _(COURSE_DIR, get_selected, mo, plt, refresh_btn, set_action_log, sns, sp, sys):
    from mograder.formgrader import scan_submissions

    _ = refresh_btn.value
    _selected = get_selected()

    if _selected:
        _subs = scan_submissions(COURSE_DIR, _selected)

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
def _(Path, moodle_file, show_names):
    if show_names.value and moodle_file.value:
        from mograder.moodle import read_moodle_worksheet as _read_ws

        _bytes = moodle_file.value[0].contents
        _tmp = Path("/tmp/_mograder_moodle_upload.csv")
        _tmp.write_bytes(_bytes)
        _, _rows = _read_ws(_tmp)
        name_lookup = {
            r["Username"]: r["Full name"]
            for r in _rows
            if "Username" in r and "Full name" in r
        }
    else:
        name_lookup = {}
    return (name_lookup,)


@app.cell
def _(
    COURSE_DIR,
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
    _student_marks = collect_student_marks(COURSE_DIR, assignments)
    _max_marks = get_max_marks(COURSE_DIR, assignments)
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
def _(get_action_log, mo, set_action_log):
    _log = get_action_log()
    if _log:
        _kind = (
            "danger" if "exited with code" in _log or "timed out" in _log else "info"
        )
        clear_btn = mo.ui.button(
            label="Dismiss",
            on_change=lambda _: set_action_log(""),
        )
        action_log_content = mo.vstack([mo.callout(mo.md(_log), kind=_kind), clear_btn])
    else:
        clear_btn = mo.ui.button(label="Dismiss", disabled=True)
        action_log_content = mo.md("")
    return action_log_content, clear_btn


@app.cell
def _(get_pending_action, mo, set_action_log, set_pending_action, sp):
    import json as _json

    _action = get_pending_action()
    if _action is not None:
        _cmd, _label = _action["cmd"], _action["label"]
        _is_autograde = _cmd and _cmd[0] == "autograde"

        if _is_autograde:
            _full_cmd = ["mograder"] + _cmd + ["--progress"]
            _proc = sp.Popen(
                _full_cmd, stdout=sp.PIPE, stderr=sp.PIPE, text=True, bufsize=1
            )
            _bar = None
            _sandbox_bar = None
            for _line in _proc.stderr:
                _line = _line.strip()
                if not _line.startswith("{"):
                    continue
                try:
                    _msg = _json.loads(_line)
                except _json.JSONDecodeError:
                    continue
                if _msg.get("event") == "sandbox_start":
                    _sandbox_bar = mo.status.spinner(
                        title=f"{_label}: installing dependencies…",
                        remove_on_exit=True,
                    )
                    _sandbox_bar.__enter__()
                elif _msg.get("event") == "sandbox_done":
                    if _sandbox_bar is not None:
                        _sandbox_bar.__exit__(None, None, None)
                        _sandbox_bar = None
                elif _msg.get("event") == "start":
                    _bar = mo.status.progress_bar(
                        total=_msg["total"], title=_label, remove_on_exit=True
                    )
                    _bar.__enter__()
                elif _msg.get("event") == "progress" and _bar is not None:
                    _bar.update(subtitle=f"{_msg['notebook']}")
            if _sandbox_bar is not None:
                _sandbox_bar.__exit__(None, None, None)
            if _bar is not None:
                _bar.__exit__(None, None, None)
            _proc.wait()
            _stdout = (_proc.stdout.read() if _proc.stdout else "").strip()
            _code = f"\n```\n{_stdout}\n```" if _stdout else ""
            if _proc.returncode == 0:
                set_action_log(f"**{_label}** — done.{_code}")
            else:
                set_action_log(
                    f"**{_label}** — exited with code {_proc.returncode}.{_code}"
                )
        else:
            try:
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
        set_pending_action(None)
    return


@app.cell
def _(
    action_log_content,
    assignments_content,
    mo,
    students_content,
    submissions_content,
):
    mo.vstack(
        [
            mo.ui.tabs(
                {
                    "Assignments": assignments_content,
                    "Submissions": submissions_content,
                    "Students": students_content,
                }
            ),
            action_log_content,
        ]
    )
    return


if __name__ == "__main__":
    app.run()
