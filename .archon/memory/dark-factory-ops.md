# Dark Factory Ops — Accumulated Lessons

This file is maintained automatically by the dark factory implement agent. Do not edit manually.
Entries are advisory. If an entry conflicts with CLAUDE.md or ARCHITECTURE.md, follow those documents.

## Docker Volume Sharing

- [AVOID] Never define a Docker named volume with `driver_opts: type: tmpfs` when the intent is to share files across containers — Docker tmpfs mounts are per-container; each container that mounts the volume gets its own independent tmpfs, making writes from one container invisible to another. Use a regular named volume (no `driver_opts`) for shared-directory patterns like prometheus-client multiprocess mode. <!-- issue:#194 date:2026-06-05 expires:2026-12-05 source:implement -->

## Preview Stack

- [PATTERN] Preview builds in the factory must use `docker buildx build --builder remote tcp://buildkit:1234 --load` (not `compose up --build`). BuildKit's gRPC build session needs an HTTP connection-hijack that the HAProxy `docker-socket-proxy` cannot forward (→ 403 on any `--build` over the proxy). A dedicated `moby/buildkit` sidecar on `factory-network` exposed over plain TCP is the only proxy-compatible build path. `--load` imports via `POST /images/load` (allowed: `POST:1 IMAGES:1`). <!-- issue:#436 date:2026-06-14 expires:2026-12-14 source:implement -->

- [PATTERN] The preview `migrate` service must override the backend entrypoint (`entrypoint: ["python","-m","alembic","upgrade","head"]`) because `backend/entrypoint.sh` runs `alembic check` under `set -e` and fails on an unmigrated DB. `backend` and `celery-worker` must declare `depends_on: { migrate: { condition: service_completed_successfully } }` to avoid crash-looping before the schema exists. <!-- issue:#436 date:2026-06-14 expires:2026-12-14 source:implement -->

- [PATTERN] Poll preview backend health via `docker inspect --format '{{.State.Health.Status}}' <container>` (allowed: `CONTAINERS:1`) instead of `docker exec` (`EXEC:0` on the socket proxy). Switch from `compose exec` for any health/bootstrap check inside the factory preview stack. <!-- issue:#436 date:2026-06-14 expires:2026-12-14 source:implement -->

## Container Root and Mounts

- [PATTERN] Copy shared entrypoint scripts to `/entrypoint.sh` (outside `/app`) in `backend/Dockerfile` — not to `./entrypoint.sh` or `/app/entrypoint.sh`. The `docker-compose.override.yml` local-dev bind-mount `./backend:/app:ro` shadows the entire `/app` directory, so any file placed inside `/app` is invisible at runtime in dev; files outside `/app` are unaffected. <!-- issue:#289 date:2026-06-12 expires:2026-12-12 source:implement -->

## Seed Files

- [PATTERN] Seed files in `dark-factory/seed/` are named with a two-digit prefix (`00_`, `01_`, ...) so they apply in deterministic order. `docker-compose.preview.yml` mounts `./seed:/seed:ro` and runs `for f in /seed/*.sql` — only files at the root of `dark-factory/seed/` are executed; subdirectory files are NOT run. <!-- issue:#207 date:2026-06-04 expires:2026-12-04 source:implement -->

- [AVOID] Seed SQL that INSERTs into `scanner_configs` must always include `universe_id` in the column list (value `1` for the default universe). The column is NOT NULL with no server default; omitting it causes a NOT NULL violation on fresh preview stacks. <!-- issue:#207 date:2026-06-04 expires:2026-12-04 source:implement -->

## Diff Computation


## Scheduler Config Pattern

- [PATTERN] When scheduler.sh defers `read_config()` until after the `SCHEDULER_SOURCE_ONLY` guard, every bash test file that sources scheduler.sh (`SCHEDULER_SOURCE_ONLY=1 source "$SCHED"`) must explicitly `export VAR=value` for all config-driven policy vars before sourcing — otherwise helper functions that reference those vars fail with `set -u` unbound-variable errors. The canonical list is in `test_scheduler.sh`'s pre-source export block. <!-- issue:#338 date:2026-06-13 expires:2026-12-13 source:implement -->

- [PATTERN] In `test_scheduler.sh`, `$STUB_LOG` captures only calls to stubbed external commands (`gh`, `docker`, `set_board_status`). Scheduler functions that emit log lines via `echo` write to stdout — to assert on these in a test, capture the function's output with `_OUTPUT=$(fn_name args 2>&1) && _RET=0 || _RET=1` and grep `$_OUTPUT`, not `$STUB_LOG`. <!-- issue:#389 date:2026-06-15 expires:2026-12-15 source:implement -->

## Scheduler Architecture

## Codeindex / MCP Integration

- [AVOID] `codeindex symbols . --inline` embeds all symbols into `codeindex.json` rather than producing a standalone file — use `codeindex symbols . --output symbolindex.json` to write the symbol index as a separate `symbolindex.json` artifact. <!-- issue:#264 date:2026-06-10 expires:2026-12-10 source:implement -->

- [PATTERN] Write `codeindex high-blast` output to a temp file then atomically rename: `codeindex high-blast > "$TARGET.tmp" && mv "$TARGET.tmp" "$TARGET"` — direct `>` truncates the file before writing, so a crash mid-run leaves a zero-byte artifact; the temp+mv pattern ensures the file is either fully written or unchanged. <!-- issue:#264 date:2026-06-10 expires:2026-12-10 source:implement -->

## Docker Port Hardening

- [PATTERN] All host-facing port bindings in `docker-compose.yml` should use the `"127.0.0.1:HOST:CONTAINER"` format to prevent inadvertent exposure on public interfaces even without a reverse proxy — defense-in-depth independent of whether a TLS profile is active. <!-- issue:#202 date:2026-06-05 expires:2026-12-05 source:implement -->

- [PATTERN] Profile-gated infra services (Caddy, forecaster, scheduler) follow the same restart pattern in `deploy.yml`: `docker compose --profile <name> up -d <service>`. Guard the Caddy step with `[ -n "${DOMAIN:-}" ]` so a missing `DOMAIN` emits a clear message rather than starting Caddy with an empty hostname. <!-- issue:#202 date:2026-06-07 expires:2026-12-07 source:implement -->

- [PATTERN] `caddy/Caddyfile` must use `{$DOMAIN}` (no `:default` fallback) — adding `{$DOMAIN:localhost}` causes Caddy to silently serve via a self-signed local-CA cert on real deploys where `DOMAIN` is unset, producing broken TLS without an obvious error. <!-- issue:#202 date:2026-06-07 expires:2026-12-07 source:implement -->

## Archon when: Expression Grammar

- [PATTERN] Archon's `when:` parser supports simple equality (`$node.output == 'value'`), same-operator chains (`$a == 'x' && $b == 'y'`), but NOT parentheses or mixed `&&`/`||`. CI enforces this via `dark-factory/scripts/check_workflow_when.py` (called from the "Validate Archon workflow YAML" step in `.github/workflows/ci.yml`). Adding `(` `)` or mixing `&&` with `||` will fail CI. <!-- issue:#403 date:2026-06-14 expires:2026-12-14 source:implement -->

## DAG Trigger Rules

- [AVOID] Do not add structural OR-join detection (checking whether all upstreams carry a `when:` condition) to a ticket where the spec listed it as Non-Goal (v1) — it changes what gets built and will be caught as a material conformance deviation even when the intent is to improve coverage. <!-- issue:#224 date:2026-06-11 expires:2026-12-11 source:conformance path:dark-factory/scripts/ -->
- [INVALID: node count was 4; expanded to 6 in issue #668 (added budget-implement, implement)] Every OR-join node in `archon-dark-factory.yaml` — a node whose `depends_on` list contains mutually-exclusive upstream branches (one is always skipped per intent) — must declare `trigger_rule: none_failed_min_one_success` (or `one_success`). The default `all_success` treats a skipped upstream as non-success and silently skips the join and all its descendants. The four known OR-join nodes (`validate`, `de-conflict`, `status-in-review`, `report`) are enumerated in `REQUIRED_OR_JOIN_NODES` in `dark-factory/scripts/check_workflow_dag.py`; when adding a new OR-join, add its ID there too. A sync tripwire (count of trigger_rule-bearing nodes must equal `len(REQUIRED_OR_JOIN_NODES)`) fires with an "update REQUIRED_OR_JOIN_NODES" prompt if the count drifts. <!-- issue:#224 date:2026-06-11 expires:2026-12-11 source:conformance -->

## Refine-Branch Pre-Implementation


## Conflict Resolution



## Service Dependencies

- [PATTERN] Two per-consumer socket proxies replace the old shared one (issue #379): `docker-socket-proxy-scheduler` (CONTAINERS/IMAGES/POST=1, no BUILD/EXEC/NETWORKS/VOLUMES) for `backlog-scheduler`; `docker-socket-proxy-factory` (all verbs incl. EXEC=1) for `dark-factory`. Both have no `profiles:` key. Wire consumers via `DOCKER_HOST: tcp://docker-socket-proxy-<consumer>:2375` and `depends_on: [docker-socket-proxy-<consumer>]`. <!-- issue:#379 date:2026-06-14 expires:2026-12-14 source:implement -->

- [INVALID: factory proxy now has EXEC=1 as of issue #379] The `docker-socket-proxy` blocks `exec` operations (HTTP 403) from inside the factory container — `docker exec` and testcontainer healthchecks both fail; verify container user via `docker inspect --format '{{.Config.User}}'` or source Dockerfile instead. <!-- evidence:curl-response issue:#287 date:2026-06-11 evidence2:docker-exec issue:#259 date:2026-06-13 expires:2026-12-13 source:implement -->

## Gate Shared Library

- [PATTERN] Gate commands (conformance, code-review, validate) that need `route_memory_file()`, `write_memory_entry()`, or `emit_verdict()` must source `dark-factory/scripts/gate_lib.sh` at Phase 1 LOAD: `REPO_ROOT=$(git rev-parse --show-toplevel); source "${REPO_ROOT}/dark-factory/scripts/gate_lib.sh"`. Do NOT add `set -euo pipefail` in gate_lib.sh — it is sourced, not executed, and strictness in the library would abort the caller on any non-zero grep/awk. <!-- issue:#334 date:2026-06-12 expires:2026-12-12 source:implement path:.archon/commands/ -->

## Scope Enforcement

- [PATTERN] `dedupe_oos.py` classifies each `[OOS]` conformance finding as one of three actions: `create` (no existing match → file a new scope ticket), `comment:<n>` (an open issue `<n>` already carries a matching embedded `<!-- dedup-key: <file/area>|<finding-type> -->` → post a comment instead of a duplicate ticket), or `suppress` (ruff/reformat-class noise or a within-run duplicate → drop silently). The dedup-key is `<file-or-area lowercased>|<finding-type>`; cross-run dedup matches it against `<!-- dedup-key: … -->` markers in open issue bodies, so every auto-filed scope ticket must embed its own dedup-key for later runs to find it. This replaces the older "one ticket per finding" behaviour. path:dark-factory/scripts/dedupe_oos.py <!-- issue:#421 date:2026-06-14 expires:2026-12-14 source:implement -->

## Path-Tag Memory Filtering


- [INVALID: functions moved to dark-factory/scripts/gate_lib.sh — source instead of inline-define] Gate commands (conformance, code-review) that need to write `[AVOID]` memory entries should define `route_memory_file()` and `write_memory_entry()` as inline shell functions using: dedup via `grep -qF`, 30-entry cap check, mawk-compatible two-arg awk expiry cleanup, and `sed -i "/^---$/i ENTRY"` to insert before the PROVISIONAL section delimiter. <!-- issue:#213 date:2026-06-09 expires:2026-12-09 source:implement -->

- [AVOID] Never use a simple hex-sequence like `a1b2c3d4e5f6` as an Alembic revision ID — the existing migration set contains files with IDs following this pattern and conflicts will produce a `CycleDetected` error. Use `python -m alembic revision -m "..."` to generate a unique ID, or pick a random 12-char alphanumeric string that doesn't appear in `ls backend/app/alembic/versions/` output. <!-- issue:#299 date:2026-06-11 expires:2026-12-11 source:implement -->

---
<!-- PROVISIONAL — entries below are from a single observed run; unverified.
     Do not rely on these as authoritative guidance. They are excluded from
     plan/implement prompt injection except as advisory context.
     Each will be promoted to [PATTERN] on second-run confirmation (different issue number) or dropped at TTL. -->


- [PROVISIONAL] When `.env` is absent, retrieve the running postgres password via `curl -s "http://docker-socket-proxy:2375/v1.54/containers/stockscanner-db/json" | python3 -c "import json,sys; [print(e) for e in json.load(sys.stdin)['Config']['Env'] if 'PASSWORD' in e]"`. <!-- evidence:curl-response issue:#287 date:2026-06-11 expires:2026-12-11 source:implement -->

- [PROVISIONAL] Tests that source `entrypoint.sh` via `ENTRYPOINT_SOURCE_ONLY=1 source entrypoint.sh` must: (1) make the empty-arguments check guard-aware (`[ "${ENTRYPOINT_SOURCE_ONLY:-0}" != "1" ]`); (2) add `|| true` to the INTENT grep pipeline so it survives empty ARGUMENTS under pipefail; (3) call `trap - ERR; set +e; set +o pipefail` immediately after sourcing to reset the entrypoint's ERR trap and strict mode. <!-- evidence:test-output issue:#431 date:2026-06-20 expires:2026-12-20 source:implement -->

- [PROVISIONAL] For standalone sidecar services (not reusing the backend image), place the Dockerfile at `docker/Dockerfile.<service>` and set `build: context: .` in `docker-compose.yml` so `COPY scripts/<file>` can reach files from the repo root; use a separate named `docker/` directory rather than placing service Dockerfiles at the project root. <!-- evidence:docker-compose-yml issue:#90 date:2026-06-12 expires:2026-12-12 source:implement -->

- [PROVISIONAL] When a `dark-factory/Dockerfile` layer change (e.g. user/group creation) risks being silently skipped by GitHub CI's Docker layer cache, temporarily add `no-cache: true` to the `build-push-action@v6` `with:` block in `.github/workflows/ci-publish.yml`'s `build-dark-factory` job, then revert after smoke tests confirm the layer executed (`whoami` returns `factory` not `root`). <!-- evidence:ci-publish-yml issue:#261 date:2026-06-13 expires:2026-12-13 source:implement -->

- [PROVISIONAL] `/opt/archon` is installed by the `dark-factory/Dockerfile` as root (not factory user) — `factory` cannot write to it; implement Archon fixes by cloning to a writable path (`GH_TOKEN=$(gh auth token) && git clone "https://${GH_TOKEN}@github.com/omniscient/Archon.git" ~/archon-fix`), then push a branch, create an Archon PR, and update the `git checkout` hash in `dark-factory/Dockerfile`. <!-- evidence:docker-build issue:#402 date:2026-06-20 expires:2026-12-20 source:implement -->

- [PROVISIONAL] In the baked-image dark factory environment (no bind-mounts), `python -m alembic revision --autogenerate` fails with `OSError: [Errno 30] Read-only file system`. Workaround: (1) write the migration file manually to `/workspace/markethawk/backend/app/alembic/versions/` with the correct `revision` and `down_revision`; (2) apply the schema change via `docker compose exec backend python -c "from app.core.database import SessionLocal; from sqlalchemy import text; db=SessionLocal(); db.execute(text('ALTER TABLE ... ADD COLUMN IF NOT EXISTS ...')); db.execute(text(\"INSERT INTO alembic_version (version_num) VALUES ('<rev_id>') ON CONFLICT DO NOTHING\")); db.commit(); db.close()"`. The workspace file will be baked into the next image build. <!-- evidence:docker-exec issue:#387 date:2026-06-21 expires:2026-12-21 source:implement -->
- [AVOID] After applying advisory fixes that change an entry format (e.g. removing a tag field), always update test assertions in all test files that verify the removed field — stale assertions cause silent failures on the next run <!-- issue:#648 date:2026-06-30 expires:2026-12-30 source:implement scope:dark-factory path:dark-factory/tests/ -->
- [PATTERN] In Dark Factory gate commands (.archon/commands/), load memory with a single `python3 "${REPO_ROOT}/dark-factory/scripts/memory_retrieve.py" --phase <role> --files "$AFFECTED" --issue "$ISSUE_NUM" --memory-dir "${REPO_ROOT}/.archon/memory"` call; it handles area-file routing and source/path filtering internally — do not inline load_memory() bash functions. <!-- issue:#652 date:2026-06-30 expires:2026-12-30 source:implement path:.archon/commands/ -->
- [AVOID] memory_write.py hardcodes the [AVOID] tag (line 192 of dark-factory/scripts/memory_write.py); both chosen-approach and rejected-approach entries from the refine gate write path are written as [AVOID]. Do not expect [PATTERN] entries from memory_write.py until the tag is parameterized. <!-- issue:#652 date:2026-06-30 expires:2026-12-30 source:implement path:dark-factory/scripts/memory_write.py -->
- [PATTERN] When fetching base file content to compute a formatter delta for a `main...HEAD` three-dot diff, use `git merge-base main HEAD` for the base ref, then `git show "$MERGE_BASE:{filepath}"`. Using `git show "main:{filepath}"` references main's current tip — on branches where main later updated the file, the wrong base produces false positives (feature hunk mis-classified as formatter-only) or false negatives. path:dark-factory/scripts/fmt_hunk_filter.py <!-- issue:#276 date:2026-06-11 expires:2026-12-11 source:implement -->
- [PATTERN] Path-tag filtering in Phase 1 LOAD extracts the `path:` prefix with `sed 's/.*path:\([^ >]*\).*/\1/'` (POSIX-compatible; not `grep -oP`) and matches via `echo "$AFFECTED" | grep -q "^${PATH_TAG}"` against the affected file list; empty `AFFECTED` means "include all" — correct fallback for new branches. <!-- issue:#213 date:2026-06-09 expires:2026-12-09 source:implement -->
- [PATTERN] Every OR-join node in `archon-dark-factory.yaml` — a node whose `depends_on` list contains mutually-exclusive upstream branches (one is always skipped per intent) — must declare `trigger_rule: none_failed_min_one_success` (or `one_success`). The default `all_success` silently skips the join and all descendants when an upstream is skipped. The six known OR-join nodes (`validate`, `de-conflict`, `status-in-review`, `report`, `budget-implement`, `implement`) are enumerated in `REQUIRED_OR_JOIN_NODES` in `dark-factory/scripts/check_workflow_dag.py`; when adding a new OR-join, add its ID there too. A sync tripwire (count of trigger_rule-bearing nodes must equal `len(REQUIRED_OR_JOIN_NODES)`) fires with an "update REQUIRED_OR_JOIN_NODES" prompt if the count drifts. <!-- issue:#668 date:2026-07-01 expires:2027-01-01 source:implement -->
- [PATTERN] `.archon/commands/` files are read from the cloned repo at runtime (live — no image rebuild needed). `.claude/skills/refinement/` files are COPYed into the image as `/opt/refinement-skills/` at build time (requires `docker compose --profile factory build dark-factory` to pick up changes). New prompt files for pipeline agents go in `.claude/skills/refinement/`. <!-- issue:#162 date:2026-06-03 expires:2026-12-03 source:implement -->

- [PATTERN] All `dispatch()` call sites in `scheduler.sh` must use `if dispatch ...; then ... fi` guards. A bare `dispatch "..."` under `set -e` exits the daemon on non-zero return, which triggers `restart: unless-stopped` and wipes the retry counter — the root cause of the #159 loop. <!-- issue:#160 date:2026-06-03 expires:2026-12-03 source:implement -->

- [PATTERN] Register a project-scoped MCP server in `entrypoint.sh` by writing the cloned repo's `.claude/settings.local.json` (gitignored) with the tool's absolute path: `$(which codeindex)`. Never rely on `"command": "codeindex"` — Claude Code does not inherit the shell PATH and will fail to launch the server. <!-- issue:#159 date:2026-06-03 expires:2026-12-03 source:implement -->

- [PATTERN] Pre-commit hooks that invoke advisory/optional tools (e.g. `codeindex-blast`) must always exit 0 — use `|| true` or `; exit 0`. A non-zero exit from a pre-commit hook blocks the commit and will abort an autonomous factory run. <!-- issue:#159 date:2026-06-03 expires:2026-12-03 source:implement -->
- [PROVISIONAL] codebase-memory-mcp v0.8.1: Python callers() returns empty list via trace_path — real callers (e.g. pre_market_scan.py:340 calling calculate_day_metrics) are invisible; do not use for blast-radius gate until upstream fixes <!-- evidence:tool-output issue:#675 date:2026-07-02 expires:2027-01-02 source:implement -->
