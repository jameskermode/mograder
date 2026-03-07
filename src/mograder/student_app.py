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
        is_cache_stale,
        load_cached_results,
        save_cached_results,
    )
    from mograder.config import load_config
    from mograder.moodle_api import (
        MoodleAPIClient,
        MoodleAPIError,
        load_cached_token,
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
        create_shared_sandbox,
        datetime,
        format_check_summary,
        is_cache_stale,
        load_cached_results,
        load_cached_token,
        mo,
        re,
        run_notebook,
        save_cached_results,
        save_cached_token,
        sp,
        sys,
        timezone,
    )


# --- State ---
@app.cell
def _(CONFIG, load_cached_token, mo):
    get_action_log, set_action_log = mo.state("")
    get_refresh, set_refresh = mo.state(0)
    get_validating, set_validating = mo.state("")

    # Initialize token from cache if available
    _initial_token = ""
    _url = CONFIG.moodle_url
    if _url:
        _cached_tok = load_cached_token(_url)
        if _cached_tok:
            _initial_token = _cached_tok["token"]
    get_token, set_token = mo.state(_initial_token)

    return (
        get_action_log,
        get_refresh,
        get_token,
        get_validating,
        set_action_log,
        set_refresh,
        set_token,
        set_validating,
    )


# --- Login cell ---
@app.cell
def _(
    CONFIG,
    COURSE_DIR,
    MoodleAPIClient,
    MoodleAPIError,
    get_token,
    mo,
    save_cached_token,
    set_action_log,
    set_token,
):
    moodle_url = CONFIG.moodle_url
    token_input = mo.ui.text(label="", value="")

    if not moodle_url or not CONFIG.moodle_assignments:
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
        # Already logged in — show header only
        mo.output.replace(
            mo.hstack(
                [
                    mo.md("# mograder student"),
                    mo.md(f"`{COURSE_DIR}`"),
                ],
                justify="space-between",
                align="center",
            )
        )
    else:
        # Need login
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
    return (moodle_url, token_input)


# --- Assignments table ---
@app.cell
def _(
    COURSE_DIR,
    CONFIG,
    MoodleAPIClient,
    create_shared_sandbox,
    datetime,
    format_check_summary,
    get_refresh,
    get_token,
    get_validating,
    is_cache_stale,
    load_cached_results,
    mo,
    moodle_url,
    re,
    run_notebook,
    save_cached_results,
    set_action_log,
    set_refresh,
    set_validating,
    sp,
    sys,
    timezone,
):
    assignments_cfg = CONFIG.moodle_assignments
    token = get_token()
    _ = get_refresh()  # reactive dependency

    buttons = mo.ui.dictionary({})

    if not moodle_url or not assignments_cfg or not token:
        mo.output.replace(mo.md(""))
    else:
        client = MoodleAPIClient(moodle_url, token)

        def assignment_slug(name):
            """Derive a directory slug from assignment name, e.g. 'A1'."""
            m = re.match(r"(A\d+)", name)
            if m:
                return m.group(1)
            return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:30]

        def assignment_dir(slug):
            d = COURSE_DIR / slug
            d.mkdir(exist_ok=True)
            return d

        def find_local_notebook(adir):
            pys = list(adir.glob("*.py"))
            return pys[0] if pys else None

        # --- Action handlers ---

        def do_download(_, assign=None, slug=None):
            adir = assignment_dir(slug)
            name = assign["name"]
            files = assign.get("files", [])
            py_files = [f for f in files if f["name"].endswith(".py")]
            if not py_files:
                set_action_log(f"No `.py` file attached to **{name}**")
                return
            for finfo in py_files:
                dest = adir / finfo["name"]
                try:
                    file_url = finfo["url"].replace(
                        "/pluginfile.php/", "/webservice/pluginfile.php/"
                    )
                    client.download_file(file_url, dest)
                except Exception as exc:
                    set_action_log(f"Download failed for **{name}**: {exc}")
                    return
            set_action_log(f"Downloaded **{name}** to `{slug}/`")
            set_refresh(lambda v: v + 1)

        def do_edit(_, path=None, name=None):
            sp.Popen([sys.executable, "-m", "marimo", "edit", "--sandbox", str(path)])
            set_action_log(f"Opened **{name}** for editing")

        def do_validate(_, path=None, name=None):
            set_validating(name)
            set_action_log(f"Validating **{name}** — installing dependencies...")
            sandbox = create_shared_sandbox(path)
            set_action_log(f"Validating **{name}** — running notebook...")
            try:
                result = run_notebook(path, sandbox_dir=sandbox)
                mtime = path.stat().st_mtime
                save_cached_results(COURSE_DIR, path.name, result, mtime)
                passed = sum(1 for c in result.checks if c.status == "success")
                total = len(result.checks)
                if not result.export_ok:
                    msg = f"Validation of **{name}** failed: {result.export_error}"
                elif total == 0:
                    msg = f"Validation of **{name}** complete (no checks found)"
                else:
                    msg = (
                        f"Validation of **{name}** complete: "
                        f"{passed}/{total} checks passed"
                    )
                if result.cell_errors > 0:
                    msg += f" ({result.cell_errors} cell error(s))"
                set_action_log(msg)
            except Exception as exc:
                set_action_log(f"Validation failed for **{name}**: {exc}")
            finally:
                set_validating("")
                set_refresh(lambda v: v + 1)

        def do_submit(_, path=None, assign=None, name=None):
            try:
                item_id = client.upload_file(path)
                client.save_submission(assign["id"], item_id)
                set_action_log(f"Submitted **{name}** (`{path.name}`)")
                set_refresh(lambda v: v + 1)
            except Exception as exc:
                set_action_log(f"Submit failed for **{name}**: {exc}")

        def do_feedback(_, assign=None, name=None):
            try:
                status = client.get_submission_status(assign["id"])
                if status["graded"]:
                    msg = f"**{name}** — Grade: **{status['grade']}**"
                    if status["feedback"]:
                        msg += f"\n\nFeedback: {status['feedback']}"
                else:
                    msg = f"**{name}** — Status: {status['status']} (not yet graded)"
                set_action_log(msg)
            except Exception as exc:
                set_action_log(f"Could not fetch feedback for **{name}**: {exc}")

        # --- Build table ---
        all_buttons = {}
        is_validating = get_validating()
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

            status = f"Downloaded ({local_nb.name})" if local_nb else "\u2014"

            # Validation cache
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
                    on_change=lambda _, a=a, s=slug: do_download(_, assign=a, slug=s),
                )
                btn_keys.append(key)

            if local_nb is not None:
                key = f"{i}_edit"
                all_buttons[key] = mo.ui.button(
                    label="Edit",
                    on_change=lambda _, p=local_nb, n=a["name"]: do_edit(
                        _, path=p, name=n
                    ),
                )
                btn_keys.append(key)

                key = f"{i}_validate"
                all_buttons[key] = mo.ui.button(
                    label=(
                        "Validating..." if is_validating == a["name"] else "Validate"
                    ),
                    on_change=lambda _, p=local_nb, n=a["name"]: do_validate(
                        _, path=p, name=n
                    ),
                    disabled=bool(is_validating),
                )
                btn_keys.append(key)

                key = f"{i}_submit"
                all_buttons[key] = mo.ui.button(
                    label="Submit",
                    on_change=lambda _, p=local_nb, a=a, n=a["name"]: do_submit(
                        _, path=p, assign=a, name=n
                    ),
                )
                btn_keys.append(key)

            key = f"{i}_feedback"
            all_buttons[key] = mo.ui.button(
                label="Feedback",
                on_change=lambda _, a=a, n=a["name"]: do_feedback(_, assign=a, name=n),
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
            row["Actions"] = mo.hstack(btns, gap=0.5) if btns else mo.md("")
            display_rows.append(row)

        if display_rows:
            table = mo.ui.table(display_rows, selection=None)
            mo.output.replace(mo.vstack([mo.md("### Assignments"), table]))

    return (buttons,)


# --- Activity log ---
@app.cell
def _(get_action_log, mo):
    log_text = get_action_log()
    dismiss_btn = mo.ui.button(label="Dismiss")

    if log_text:
        kind = (
            "danger"
            if "failed" in log_text.lower() or "error" in log_text.lower()
            else "info"
        )
        activity_log = mo.vstack([mo.callout(mo.md(log_text), kind=kind), dismiss_btn])
    else:
        activity_log = mo.md("")

    mo.output.replace(activity_log)
    return (activity_log, dismiss_btn)


@app.cell
def _(dismiss_btn, set_action_log):
    # When dismiss button is clicked (value increments), clear the log
    if dismiss_btn.value:
        set_action_log("")
    return ()


if __name__ == "__main__":
    app.run()
