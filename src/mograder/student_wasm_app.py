import marimo

__generated_with = "0.20.0"
app = marimo.App(width="medium")


@app.cell
def _():
    import json
    import urllib.parse
    import urllib.request

    import marimo as mo

    params = mo.query_params()
    # Snapshot which params were provided — plain set, no reactive writes
    provided_params = frozenset(
        k
        for k in ("server", "repo", "path", "branch", "wasm_base")
        if params.get(k, "")
    )
    return json, mo, params, provided_params, urllib


@app.cell
def _(mo, params, provided_params):
    server_url = mo.ui.text(
        value=params.get("server", ""),
        label="Server URL",
        placeholder="https://mograder-demo.jrkermode.uk",
        full_width=True,
    )
    github_repo = mo.ui.text(
        value=params.get("repo", ""),
        label="GitHub Repo (owner/repo)",
        placeholder="jameskermode/mograder",
        full_width=True,
    )
    release_path = mo.ui.text(
        value=params.get("path", "demo/course"),
        label="Release path in repo",
        full_width=True,
    )
    branch = mo.ui.text(
        value=params.get("branch", "main"),
        label="Branch",
    )

    # Only show widgets for params not already provided via URL
    _rows = []
    if "server" not in provided_params:
        _rows.append(mo.hstack([server_url]))
    if not provided_params.issuperset({"repo", "path", "branch"}):
        _repo_row = [
            w
            for k, w in [
                ("repo", github_repo),
                ("path", release_path),
                ("branch", branch),
            ]
            if k not in provided_params
        ]
        if _repo_row:
            _rows.append(mo.hstack(_repo_row))

    mo.vstack([mo.md("# mograder student dashboard")] + _rows)
    return branch, github_repo, release_path, server_url


@app.cell
def _(json, server_url, urllib):
    def fetch_json(url):
        """Fetch JSON from a URL using urllib (works in both WASM and regular Python)."""
        with urllib.request.urlopen(url) as resp:
            return json.loads(resp.read().decode())

    assignments = []
    connection_error = ""
    if server_url.value:
        try:
            assignments = fetch_json(f"{server_url.value.rstrip('/')}/assignments")
        except Exception as e:
            connection_error = str(e)
    return assignments, connection_error, fetch_json


@app.cell
def _(connection_error, mo):
    if connection_error:
        mo.callout(mo.md(f"**Connection error:** {connection_error}"), kind="danger")
    return


@app.cell
def _(assignments, branch, github_repo, mo, params, release_path):
    if not assignments:
        mo.output.replace(
            mo.callout(
                mo.md("Enter a server URL above to see assignments."),
                kind="neutral",
            )
        )
        mo.stop(True)

    _repo = github_repo.value
    _branch = branch.value
    _rel_path = release_path.value.strip("/")

    _rows = []
    for _a in assignments:
        _name = _a["name"]
        _files = _a.get("files", [])
        _links = []
        _wasm = params.get("wasm_base", "")
        for _f in _files:
            _fname = _f["filename"]
            if _fname.endswith(".py"):
                if _wasm:
                    _nb_name = _fname.rsplit(".", 1)[0]
                    _wasm_url = f"{_wasm.rstrip('/')}/{_nb_name}.html"
                    _links.append(mo.md(f"[Edit in Browser]({_wasm_url})"))
                elif _repo:
                    _molab = (
                        f"https://molab.marimo.io/github/{_repo}"
                        f"/blob/{_branch}/{_rel_path}/{_name}/files/{_fname}"
                    )
                    _links.append(mo.md(f"[Edit in Molab]({_molab})"))
                else:
                    _links.append(_fname)
            else:
                _links.append(_fname)
        _rows.append(
            {
                "Assignment": _name,
                "Files": mo.hstack(_links, gap=0.5) if _links else "",
            }
        )

    mo.output.replace(
        mo.vstack([mo.md("## Assignments"), mo.ui.table(_rows, selection=None)])
    )
    return


if __name__ == "__main__":
    app.run()
