# Security Model for `mograder autograde`

## Threat model

When running `mograder autograde`, student-submitted notebooks are executed on the grading server. A malicious or buggy notebook could attempt to:

1. **Resource exhaustion** — infinite loops, fork bombs, memory allocation
2. **Filesystem access** — read other students' submissions, overwrite grading data
3. **Network access** — exfiltrate data, phone home, abuse the server as a proxy
4. **Process escape** — spawn persistent background processes that outlive the grading run

mograder provides layered defences, each progressively stronger. Not all layers are required — choose the combination that fits your environment.

## Layer 1: Resource limits (`rlimits`)

Every subprocess spawned by `run_notebook()` has POSIX resource limits applied via `preexec_fn`:

| Limit | Config key | Default | Effect |
|-------|-----------|---------|--------|
| CPU time | `rlimits.cpu` | 600 s | SIGKILL after this many CPU-seconds |
| User processes | `rlimits.nproc` | 512 | Caps total processes for the UID |
| Open files | `rlimits.nofile` | 256 | Caps open file descriptors |
| Virtual memory | `rlimits.as` | 1 GiB | Caps address space (Linux only) |

Configure in `mograder.toml`:

```toml
[rlimits]
cpu = 120
nproc = 64
nofile = 128
as = 2147483648   # 2 GiB
```

Or override per-run with `--max-memory` (in MB):

```bash
mograder autograde hw1 --max-memory 2048
```

A value of `0` disables that limit. `RLIMIT_AS` is skipped on macOS where it is unreliable.

## Layer 2: Execution timeout

The `--timeout` flag (default 300 s) sets a wall-clock deadline. If the notebook process hasn't exited by then, the **entire process tree** is killed (not just the direct child). This handles cases where `marimo export html` spawns `uv run` which spawns inner Python.

The tree-kill implementation walks `/proc/*/stat` to find all descendants, sends `SIGTERM` (leaves first), waits 300 ms, then sends `SIGKILL` to any survivors.

## Layer 3: Static safety check (`--safety-check`)

Before execution, the submitted `.py` file is scanned using AST analysis for dangerous patterns:

- Denied imports (`os`, `subprocess`, `socket`, `shutil`, etc.)
- Use of `eval()`, `exec()`, `compile()`
- `__import__()` calls

If unsafe patterns are found, execution is skipped and the notebook is marked as failed. Enable with:

```bash
mograder autograde hw1 --safety-check
```

This is a best-effort heuristic — it catches common attack patterns but cannot prevent all possible exploits (e.g. obfuscated imports via `importlib`).

## Layer 4: Temp directory isolation (`isolate_cwd`)

During autograde, each notebook is copied into a fresh `tempfile.mkdtemp()` directory before execution. The subprocess `cwd` is set to this temp dir rather than the notebook's original parent directory. This prevents:

- Student code writing files next to other submissions
- Student code reading other students' `.py` files in the same directory

The temp dir is cleaned up in a `finally` block after execution, even on failure. This is enabled automatically by `mograder autograde`.

## Layer 5: Bubblewrap filesystem sandbox (optional)

For stronger isolation, enable [bubblewrap](https://github.com/containers/bubblewrap) (`bwrap`) in `mograder.toml`:

```toml
[security]
use_bubblewrap = true
```

When enabled, the subprocess command is wrapped with:

```
bwrap --ro-bind / / --tmpfs /tmp --tmpfs /home --bind <cwd> <cwd> --unshare-net --die-with-parent -- <cmd>
```

This provides:
- **Read-only root filesystem** — student code cannot modify system files
- **Empty `/home`** — no access to other users' files
- **Isolated `/tmp`** — each notebook gets its own tmpfs
- **Network namespace** — no outbound network access
- **Bind-mounted working directory** — only the notebook's temp dir is writable

If `bwrap` is not found on `PATH`, a warning is logged and execution proceeds without sandboxing.

**Install bubblewrap**: `sudo dnf install bubblewrap` (RHEL/Fedora) or `sudo apt install bubblewrap` (Debian/Ubuntu).

## Layer 6: Integrity checking

When `--source` is provided (or auto-discovered), mograder compares check cells, marks definitions, and cell hashes between the source and submitted notebooks. Tampered cells are reinjected from the source before execution, preventing students from modifying test logic to fake passing checks.

## Recommendations

For a production grading server:

1. **Always** run autograde on a dedicated service account (not your personal account)
2. **Always** use `--safety-check` for untrusted submissions
3. **Always** use `--source` for integrity checking
4. Configure tight resource limits in `mograder.toml`
5. Consider enabling `use_bubblewrap = true` for filesystem isolation
6. Set `--timeout` to a reasonable value for your assignments (e.g. 120-300 s)
7. Monitor the grading server for runaway processes after autograde runs
