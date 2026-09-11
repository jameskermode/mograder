# ADR: Keep the mograder hub; don't adopt marimohub yet

| | |
|---|---|
| **Status** | Proposed |
| **Date** | 2026-09-11 |
| **Scope** | `src/mograder/hub/`, `core/edit_sessions.py`, RONIN deployment for ES98E |
| **Evaluated** | [marimohub](https://github.com/marimo-team/marimohub) v0.3.12 (2026-08-28) against mograder 0.3.3 |
| **Revisit** | On marimohub 1.0, or if Warwick grants ECS / Kubernetes |

marimohub is a promising team-notebook platform, but it has **no per-student
notebook model**, is three months old at v0.3, and its only workable mode
behind RONIN's SSH-only security group is one its own docs mark *trusted
environments only*. We keep `src/mograder/hub/` and instead borrow its best
idea: **a Docker container per kernel**.

## Context: what marimohub is

A self-hostable notebook platform from the marimo team. Three swappable ports —
storage, compute, identity — and a Node server that owns everything else:
projects, notebooks, version history, sessions, an audit log. There is no
database; the object store is the source of truth and must support conditional
writes.

| | |
|---|---|
| Repo created | 2026-06-17 (pushed 2026-09-11) |
| Release | v0.3.12 — 8 releases in the last month |
| Stack | TypeScript / Node, pnpm monorepo, 39 packages |
| Licence | Apache-2.0 · 61 stars · 13 open issues |
| Storage backends | `s3`, `gcs`, `azure`, `r2`, `fs` (`fs` = single replica) |
| Compute backends | `docker`, `podman`, `kubernetes`, `fargate`, `modal`, `e2b`, `coreweave`, `local` |
| Auth backends | `oidc`, `proxy-header`, `cloudflare-access`, `dev` |
| Roles | `viewer` · `editor` · `manager` · `admin` per project, plus super-admins |

It also ships a lot we would never switch on: typed integrations and secret
stores, Workload Identity Federation, GitHub sync, scheduled jobs, VS Code and
OpenCode surfaces, an AI proxy, Slack/SMTP/webhook notifications, security
labels. Each is a feature for a data team and an attack surface for a
classroom.

## Analysis: the models don't match

marimohub is a collaboration hub: a notebook has one canonical copy that
editors share. The mograder hub is a classroom hub: every student gets a
private copy of every assignment, fetched from `hub-release/` on first open
and never overwritten.

**marimohub — one copy, many editors**

```
project (members + roles)
└ notebook (versioned in bucket)
  └ persistent editor sandbox
    └ shared or exclusive claim
```

From the editor-sessions docs: exclusive mode "isolates the live sandbox, not
the stored project data" and "does not create a private mount for each user".
The closest thing to per-user state is the viewer mode `ephemeral-sandbox`,
which discards everything on exit.

**mograder hub — one release, N copies**

```
hub-release/<assignment>/
└ hub-notebooks/<user>/<assignment>/
  └ marimo edit (per user, per assignment)
    └ /edit/user/<user>/<assignment>/
```

Validate, submit, reset and status all key on `(username, assignment)`. The
deep link `/edit/<assignment>` resolves to the caller's copy, so one URL works
for the whole cohort in Moodle.

The only faithful mapping is **one project per student** (or per student ×
assignment), provisioned by an instructor script through the API, with the
release notebook uploaded into each. That is N×M notebooks and N×M persistent
sandboxes, per-student URLs that need our own redirect layer for Moodle, and a
provisioning job we would own. Feasible — but it is working against the tool's
grain, not with it.

### What we would still have to run ourselves

Nothing grading-specific in `hub/app.py` has a home in marimohub:

- **Validate** — headless check run and HTML report (`/validate`, `/validate-report`)
- **Submit** — integrity reinjection of tampered check/marks cells, submit-cell
  stripping, timestamped write to `submitted/`
- **Reset to release**, **status**, **mark-exported**
- **Publish** with PEP 723 shared venv and uv cache warming for JAX/PyTorch-sized
  dependency sets
- **Lectures** via per-user `marimo run --include-code`
- **Moodle enrolment allowlist** (`allowed_users.txt`, hot-reloaded) and **workshops**

These would move behind `mograder serve` and be driven from inside the notebook
via `mograder.remote`. That machinery exists, but it is a rewrite of the student
flow, not a deletion. Net effect: retire roughly `spawner.py`, `proxy.py`,
`hub/auth.py` and `core/edit_sessions.py` (≈1,600 lines) and take on a Node
service, a sandbox-image pipeline, and a per-cohort provisioning script.

## Constraint: fit with RONIN on AWS

RONIN gives us an EC2 instance (t3.large, 50 GB EBS at `/srv/mograder`) with a
security group that exposes port 22 only. Everything reaches students through
the sciml.warwick.ac.uk proxy at `/live/hub/`, which authenticates via
Shibboleth and forwards `X-Remote-User`. This is the decisive constraint.

| Concern | marimohub | mograder hub today |
|---|---|---|
| Kernel exposure | **Blocker.** Default `subdomain` mode needs a *separate registrable domain* with direct browser→kernel traffic — impossible behind a path-prefix proxy on an SSH-only host. That forces `proxy` mode, which the security docs label "trusted environments only" (kernels become same-origin with the control plane; must set `MARIMOHUB_SANDBOX_PROXY_ACK_UNTRUSTED=true`). | Already proxies every session through the app under the same trust profile; no second domain needed. |
| Compute | **Partial.** `fargate` needs ECS plus `iam:PassRole`, which RONIN project users typically don't get (unverified). Realistic path is `docker`: the Docker socket mounted into the hub container, a custom sandbox image with marimo + uv + course deps pushed to a registry we can pull from. | `marimo edit` subprocess wrapped in bubblewrap; shared per-assignment venv warmed at publish time. |
| Storage | **Fine.** `fs` backend on EBS (single replica, which we have anyway) or S3 if RONIN provides a bucket. | Plain directories on EBS; `scp`-able. |
| Auth | **Adaptable.** `proxy-header` matches the sciml flow but wants email + subject headers and a mandatory `ALLOWED_EMAIL_DOMAINS`; the sciml proxy would synthesise `user@warwick.ac.uk`. Cohort allowlist becomes a per-project membership list, not a synced file. | `X-Remote-User` from a trusted proxy IP → signed session cookie; `moodle sync-users` writes the allowlist. |
| Recipe maturity | **Untested.** The single-instance guide (fs + docker + Caddy on one VM — our exact shape) opens with "Outline — not yet a tested recipe. Contributions welcome." | Ran ES98E on RONIN; `scripts/deploy-hub-aws.sh` and a systemd unit are documented. |
| Publishing over SSH | **Same problem.** HTTP API only, and with bucket-backed storage you can't sidestep it with `scp`. | HTTP API today; SSH-based `hub publish` is an open feature request. |
| Ops footprint | **Heavier.** Node runtime, Docker daemon, derived hub image (adds the docker CLI), sandbox image registry, maintenance replica flag, session-JWT expiry semantics that hard-kill kernels at the deadline. | One Python service; `uv`, `marimo`, `bwrap`. |

## Decision: keep the hub, borrow the container-per-kernel design

We do not retire `src/mograder/hub/`. We add Docker as a sandbox backend
alongside bubblewrap, and we re-evaluate marimohub when the triggers below
fire.

1. **Model mismatch is structural.** A per-student copy of a template notebook
   is the whole point of our hub and is absent from marimohub's project model.
   Emulating it with N×M projects would leave us owning the awkward parts.
2. **We'd rebuild the student flow, not delete it.** Validate, submit, integrity
   checks, deep links, lectures, cohort allowlists and cache warming all live
   outside marimohub's scope.
3. **RONIN forces the mode marimohub warns against.** Proxy exposure is the only
   option without a second public domain, and it collapses the isolation
   benefit that would justify the switch.
4. **Maturity.** Three months old, pre-1.0, weekly releases with documented
   protocol changes that require draining all sessions, and an untested recipe
   for our topology. Our hub is ~2,400 lines with ~2,300 lines of tests and a
   real term of production use.

Where marimohub is unambiguously better is kernel isolation: a container per
kernel with a baked image beats bubblewrap plus a warmed uv cache on security,
reproducibility and cold-start predictability. That is a contained change to
`spawner.py`, so we take it.

## Consequence: planned capability — Docker sandbox per session

> **Status: planned, not implemented.**

Add `_wrap_with_docker()` next to `_wrap_with_bwrap()` in `hub/spawner.py`,
selected by a new `[security] sandbox` key. The hub process, storage layout,
proxy and student flow are unchanged; only the process wrapper differs.

### Shape

```toml
# mograder.toml
[security]
sandbox = "docker"   # "bubblewrap" | "docker" | "none"
image   = "mograder-sandbox:es98e-2026"
memory  = "2g"
cpus    = 1.0
```

```sh
# hub/spawner.py — command the hub spawns
docker run --rm --name mg-{user}-{assignment}
  --user {uid}:{gid}
  --read-only --tmpfs /tmp --tmpfs /home/student
  -v {student_dir}:/work:rw
  -v {release_dir}/{assignment}/.venv:/venv:ro
  --network mograder-kernels        # internal, no egress
  -p 127.0.0.1:{port}:2718
  --memory {memory} --cpus {cpus} --pids-limit 256
  --cap-drop ALL --security-opt no-new-privileges
  {image} marimo edit /work/{assignment}.py
      --headless --host 0.0.0.0 --port 2718
      --token --token-password {token}
```

### Design points

- **Image replaces cache warming.** `hub publish` gains a `--build-image` step
  that resolves the union of PEP 723 deps across published assignments into one
  image tag; `hub warm-cache` becomes the fallback for the bubblewrap backend
  only. Heavy JAX/PyTorch layers are pulled once per host, not per session.
- **Network.** bubblewrap uses `--unshare-net`; the Docker equivalent is an
  `internal` bridge so the hub reaches the published loopback port but the
  kernel has no egress. *Verify during implementation that the current
  `--unshare-net` wrapper actually lets the hub reach the marimo port — a new
  network namespace has only `lo`.*
- **Lifecycle.** Session cull calls `docker stop`; hub restart adopts running
  containers by name prefix `mg-` instead of orphaning them, borrowing
  marimohub's reconcile-by-owner-label pattern.
- **Lectures** use the same wrapper with `marimo run --include-code` and the
  release dir mounted read-only.
- **Hub itself stays a host process** (systemd, service user in the `docker`
  group). No docker-in-docker.

### Open questions before building

- Docker socket access for the `mograder` service user on RONIN.
- Where to build and store the image given SSH-only access (build on the host
  via `hub publish` vs. push from a laptop).
- Container cold-start vs. today's ~2 s subprocess spawn on a t3.large.
- EBS headroom for image layers alongside 50 GB of student data.

## Revisit when

- marimohub adds a template → per-user copy primitive (a classroom or
  assignment mode). Nothing in the docs or roadmap suggests one today.
- marimohub reaches 1.0 with a tested single-instance recipe and a stable
  editor-claim protocol.
- Warwick provides ECS/Fargate or a Kubernetes namespace. That is where
  marimohub's horizontal design pays off and ours cannot follow.
- We want VS Code or AI surfaces inside student sessions.

### Worth reading regardless

- Its HMAC-signed `/proxy/<token>/` route design and per-request
  re-authorisation on WebSocket upgrade.
- Exclusive-session takeover protocol (drain → save → destroy → replace with a
  lease), if we ever hit multi-tab or stale-session bugs.
- `ephemeral-sandbox` viewer mode — it is our `/run/<lecture>` semantics,
  independently arrived at.

## Sources (consulted 2026-09-11)

- [github.com/marimo-team/marimohub](https://github.com/marimo-team/marimohub) — repo metadata, releases, package list
- [Architecture](https://marimohub.docs.marimo.io/architecture) — ports, no-database model, request flow
- [Editor sessions](https://marimohub.docs.marimo.io/editor-sessions) — shared vs exclusive, no per-user mount
- [Security model](https://marimohub.docs.marimo.io/security) — subdomain vs proxy exposure, roles
- [Compute](https://marimohub.docs.marimo.io/compute) — docker, fargate, local backends
- [Auth](https://marimohub.docs.marimo.io/auth) — proxy-header, viewer modes, default roles
- [Deploying on a single instance](https://marimohub.docs.marimo.io/deploying/single-instance) — the untested outline
- [Deployment options](https://marimohub.docs.marimo.io/deployment-options) — config-driven vs library
- `src/mograder/hub/`, `docs/hub-deployment.md` — our current hub
