import marimo

__generated_with = "0.20.0"
app = marimo.App(width="medium")


@app.cell
def _():
    import json
    import urllib.parse
    import urllib.request
    from datetime import datetime

    import marimo as mo

    params = mo.query_params()
    # Snapshot which params were provided — plain set, no reactive writes
    provided_params = frozenset(k for k in ("server", "title") if params.get(k, ""))

    # Auto-detect server URL when running in WASM (browser)
    default_server = ""
    try:
        from pyodide.ffi import JsProxy  # noqa: F401 — only exists in Pyodide

        import js  # noqa: F811

        default_server = js.location.origin + "/live/student/api"
    except (ImportError, AttributeError):
        pass

    return datetime, default_server, json, mo, params, provided_params, urllib


@app.cell
def _(default_server, mo, params, provided_params):
    server_url = mo.ui.text(
        value=params.get("server", default_server),
        label="Server URL",
        placeholder="https://sciml.warwick.ac.uk/live/student/api",
        full_width=True,
    )

    # Only show widget if server not already provided via URL or auto-detected
    _rows = []
    if "server" not in provided_params and not default_server:
        _rows.append(mo.hstack([server_url]))

    _title = params.get("title", "Assignment Dashboard")
    mo.vstack([mo.md(f"# {_title}")] + _rows)
    return (server_url,)


@app.cell
def _(json, server_url, urllib):
    def fetch_json(url):
        """Fetch JSON from a URL using urllib (works in both WASM and regular Python)."""
        with urllib.request.urlopen(url) as resp:
            return json.loads(resp.read().decode())

    assignments = []
    moodle_url = ""
    connection_error = ""
    if server_url.value:
        _base = server_url.value.rstrip("/")
        try:
            assignments = fetch_json(f"{_base}/assignments")
            _config = fetch_json(f"{_base}/config")
            moodle_url = _config.get("moodle_url", "")
        except Exception as e:
            connection_error = str(e)
    return assignments, connection_error, fetch_json, moodle_url


@app.cell
def _():
    # Pre-computed "Edit in Molab" URLs, populated at build time by
    # `mograder wasm-edit-links`.  Keys are assignment directory names.
    precomputed_edit_links = {}
    return (precomputed_edit_links,)


@app.cell
def _(connection_error, mo):
    if connection_error:
        mo.callout(mo.md(f"**Connection error:** {connection_error}"), kind="danger")
    return


@app.cell
def _(
    assignments, datetime, mo, moodle_url, params, precomputed_edit_links, server_url
):
    if not assignments:
        mo.output.replace(
            mo.callout(
                mo.md("Enter a server URL above to see assignments."),
                kind="neutral",
            )
        )
        mo.stop(True)

    _base = server_url.value.rstrip("/")
    # Derive WASM base URL: explicit query param > auto-detect from server URL
    _wasm_base = params.get("wasm_base", "")
    if not _wasm_base and "/api" in _base:
        _wasm_base = _base.rsplit("/api", 1)[0] + "/wasm"

    _rows = []
    for _a in assignments:
        _name = _a["name"]
        _files = _a.get("files", [])
        _dir = _a.get("dir", "") or _a.get("id", "") or _name

        # Due date
        _due = ""
        if _a.get("duedate"):
            _dt = datetime.fromtimestamp(_a["duedate"])
            _due = _dt.strftime("%d %b %Y")

        # Edit column: WASM link + edit_links (molab, codespaces, etc.)
        _edit_parts = []
        _has_wasm = bool(
            _wasm_base and (_a.get("wasm_url") or params.get("wasm_base", ""))
        )
        if _has_wasm:
            _wasm_href = _wasm_base.rstrip("/") + "/" + _dir + ".html"
            _edit_parts.append(f"**[Edit in Browser]({_wasm_href})**")
        _link_labels = {"molab": "Edit in Molab", "codespaces": "Edit in Codespaces"}
        for _link in _a.get("edit_links", []):
            _label = _link_labels.get(_link["name"], _link["name"].title())
            _href = _link["url"]
            if _has_wasm:
                _edit_parts.append(f"[{_label}]({_href})")
            elif not _edit_parts:
                _edit_parts.append(f"**[{_label}]({_href})**")
            else:
                _edit_parts.append(f"[{_label}]({_href})")
        # Fall back to pre-computed edit links when server didn't provide any
        if not _a.get("edit_links"):
            _key = _a.get("dir", "") or _a.get("name", "")
            if _key in precomputed_edit_links:
                _pre_href = precomputed_edit_links[_key]
                if _edit_parts:
                    _edit_parts.append(f"[Edit in Molab]({_pre_href})")
                else:
                    _edit_parts.append(f"**[Edit in Molab]({_pre_href})**")
        _edit = mo.md(" | ".join(_edit_parts)) if _edit_parts else ""

        # Download column: link to file(s); show "Download" for zip bundles
        _downloads = []
        for _f in _files:
            _fname = _f["filename"]
            _label = "Download" if _fname.endswith(".zip") else _fname
            _url = f"{_base}{_f['url']}"
            _downloads.append(mo.md(f"[{_label}]({_url})"))
        _download = mo.hstack(_downloads, gap=0.5) if _downloads else ""

        # Submit column: Moodle link if available
        _submit = ""
        if moodle_url and _a.get("cmid"):
            _moodle_href = f"{moodle_url}/mod/assign/view.php?id={_a['cmid']}"
            _submit = mo.md(f"[Submit on Moodle]({_moodle_href})")

        _rows.append(
            {
                "Assignment": _name,
                "Due": _due,
                "Edit": _edit,
                "Download": _download,
                "Submit": _submit,
            }
        )

    mo.output.replace(
        mo.vstack([mo.md("## Assignments"), mo.ui.table(_rows, selection=None)])
    )
    return


if __name__ == "__main__":
    app.run()
