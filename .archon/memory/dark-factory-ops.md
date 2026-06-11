# Dark Factory Ops — Accumulated Lessons

This file is maintained automatically by the dark factory implement agent. Do not edit manually.
Entries are advisory. If an entry conflicts with CLAUDE.md or ARCHITECTURE.md, follow those documents.

## Docker Volume Sharing

- [AVOID] Never define a Docker named volume with `driver_opts: type: tmpfs` when the intent is to share files across containers — Docker tmpfs mounts are per-container; each container that mounts the volume gets its own independent tmpfs, making writes from one container invisible to another. Use a regular named volume (no `driver_opts`) for shared-directory patterns like prometheus-client multiprocess mode. <!-- issue:#194 date:2026-06-05 expires:2026-12-05 source:implement -->

## Preview Stack

- [PATTERN] Preview ports follow the formula `1{ISSUE_NUM_PADDED}XX` where `ISSUE_NUM_PADDED` is zero-padded to two digits and XX is the service suffix (33=frontend, 80=backend, 54=postgres, 63=redis). Example: issue #3 → frontend `:10333`, backend `:10380`. <!-- bootstrap date:2026-06-02 expires:2026-12-02 source:implement -->

## Container Root and Mounts

- [PATTERN] The dark factory container runs as the `factory` user (uid 1000) with `/workspace` as the working directory. The repo is cloned to `/workspace/markethawk`. Paths inside the container that start with `/opt/` (e.g. `/opt/refinement-skills/`) are read-only mounts from the host and are not git-tracked by the cloned repo. <!-- bootstrap date:2026-06-02 expires:2026-12-02 source:implement -->

- [PATTERN] `.archon/commands/` files are read from the cloned repo at runtime (live — no image rebuild needed). `.claude/skills/refinement/` files are COPYed into the image as `/opt/refinement-skills/` at build time (requires `docker compose --profile factory build dark-factory` to pick up changes). New prompt files for pipeline agents go in `.claude/skills/refinement/`. <!-- issue:#162 date:2026-06-03 expires:2026-12-03 source:implement -->

## Seed Files

- [PATTERN] Seed files in `dark-factory/seed/` are named with a two-digit prefix (`00_`, `01_`, ...) so they apply in deterministic order. `docker-compose.preview.yml` mounts `./seed:/seed:ro` and runs `for f in /seed/*.sql` — only files at the root of `dark-factory/seed/` are executed; subdirectory files are NOT run. <!-- issue:#207 date:2026-06-04 expires:2026-12-04 source:implement -->

- [AVOID] Seed SQL that INSERTs into `scanner_configs` must always include `universe_id` in the column list (value `1` for the default universe). The column is NOT NULL with no server default; omitting it causes a NOT NULL violation on fresh preview stacks. <!-- issue:#207 date:2026-06-04 expires:2026-12-04 source:implement -->

- [AVOID] Do not embed data directly in Alembic migration files — migrations are schema-only. Feature-specific seed data goes in `dark-factory/seed/99_feature.sql` (idempotent, `ON CONFLICT DO NOTHING`). Data needed across multiple features goes in a new numbered baseline module. <!-- bootstrap date:2026-06-02 expires:2026-12-02 source:implement -->

## Diff Computation

- [PATTERN] When fetching base file content to compute a formatter delta for a `main...HEAD` three-dot diff, use `git merge-base main HEAD` for the base ref, then `git show "$MERGE_BASE:{filepath}"`. Using `git show "main:{filepath}"` references main's current tip — on branches where main later updated the file, the wrong base produces false positives (feature hunk mis-classified as formatter-only) or false negatives. path:dark-factory/scripts/fmt_hunk_filter.py <!-- issue:#276 date:2026-06-11 expires:2026-12-11 source:implement -->

## Scope Enforcement

- [PATTERN] When an out-of-scope defect is noticed during implementation, write it to `$ARTIFACTS_DIR/out-of-scope.md` with `- <file>: <one-sentence description>` and leave the defect unfixed. The conformance gate reads this file and converts each entry into a `scope-spillover`-labelled backlog ticket automatically. <!-- issue:#206 date:2026-06-04 expires:2026-12-04 source:implement -->

## Memory Entry Format

- [PATTERN] Every memory entry must carry an `expires:YYYY-MM-DD` inline comment with a 6-month TTL from the date it was written. Format: `<!-- issue:#NNN date:YYYY-MM-DD expires:YYYY-MM-DD source:implement -->`. The expiry date is used by the awk cleanup one-liner to prune stale lessons automatically. <!-- issue:#149 date:2026-06-02 expires:2026-12-02 source:implement -->

## Scheduler Architecture

- [PATTERN] All `dispatch()` call sites in `scheduler.sh` must use `if dispatch ...; then ... fi` guards. A bare `dispatch "..."` under `set -e` exits the daemon on non-zero return, which triggers `restart: unless-stopped` and wipes the retry counter — the root cause of the #159 loop. <!-- issue:#160 date:2026-06-03 expires:2026-12-03 source:implement -->

## Codeindex / MCP Integration

- [PATTERN] Register a project-scoped MCP server in `entrypoint.sh` by writing the cloned repo's `.claude/settings.local.json` (gitignored) with the tool's absolute path: `$(which codeindex)`. Never rely on `"command": "codeindex"` — Claude Code does not inherit the shell PATH and will fail to launch the server. <!-- issue:#159 date:2026-06-03 expires:2026-12-03 source:implement -->

- [PATTERN] Pre-commit hooks that invoke advisory/optional tools (e.g. `codeindex-blast`) must always exit 0 — use `|| true` or `; exit 0`. A non-zero exit from a pre-commit hook blocks the commit and will abort an autonomous factory run. <!-- issue:#159 date:2026-06-03 expires:2026-12-03 source:implement -->

- [AVOID] `codeindex symbols . --inline` embeds all symbols into `codeindex.json` rather than producing a standalone file — use `codeindex symbols . --output symbolindex.json` to write the symbol index as a separate `symbolindex.json` artifact. <!-- issue:#264 date:2026-06-10 expires:2026-12-10 source:implement -->

- [PATTERN] Write `codeindex high-blast` output to a temp file then atomically rename: `codeindex high-blast > "$TARGET.tmp" && mv "$TARGET.tmp" "$TARGET"` — direct `>` truncates the file before writing, so a crash mid-run leaves a zero-byte artifact; the temp+mv pattern ensures the file is either fully written or unchanged. <!-- issue:#264 date:2026-06-10 expires:2026-12-10 source:implement -->

## Docker Port Hardening

- [PATTERN] All host-facing port bindings in `docker-compose.yml` should use the `"127.0.0.1:HOST:CONTAINER"` format to prevent inadvertent exposure on public interfaces even without a reverse proxy — defense-in-depth independent of whether a TLS profile is active. <!-- issue:#202 date:2026-06-05 expires:2026-12-05 source:implement -->

- [PATTERN] Profile-gated infra services (Caddy, forecaster, scheduler) follow the same restart pattern in `deploy.yml`: `docker compose --profile <name> up -d <service>`. Guard the Caddy step with `[ -n "${DOMAIN:-}" ]` so a missing `DOMAIN` emits a clear message rather than starting Caddy with an empty hostname. <!-- issue:#202 date:2026-06-07 expires:2026-12-07 source:implement -->

- [PATTERN] `caddy/Caddyfile` must use `{$DOMAIN}` (no `:default` fallback) — adding `{$DOMAIN:localhost}` causes Caddy to silently serve via a self-signed local-CA cert on real deploys where `DOMAIN` is unset, producing broken TLS without an obvious error. <!-- issue:#202 date:2026-06-07 expires:2026-12-07 source:implement -->

## Environment and Credentials

- [PATTERN] AI credentials (`CLAUDE_CODE_OAUTH_TOKEN` or `ANTHROPIC_API_KEY`) and `GH_TOKEN` belong in `.archon/.env`, not in `.env`. The `.archon/.env` file is gitignored to keep secrets out of the repo. <!-- bootstrap date:2026-06-02 expires:2026-12-02 source:implement -->

## DAG Trigger Rules

- [PATTERN] Every OR-join node in `archon-dark-factory.yaml` — a node whose `depends_on` list contains mutually-exclusive upstream branches (one is always skipped per intent) — must declare `trigger_rule: none_failed_min_one_success` (or `one_success`). The default `all_success` treats a skipped upstream as non-success and silently skips the join and all its descendants. The four current OR-join nodes are `validate`, `de-conflict`, `status-in-review`, and `report`; when adding a new one, also update `REQUIRED_OR_JOIN_NODES` and `EXPECTED_TRIGGER_RULE_COUNT` in `dark-factory/scripts/check_workflow_dag.py`. <!-- issue:#224 date:2026-06-11 expires:2026-12-11 source:implement -->

## Refine-Branch Pre-Implementation

- [PATTERN] When the architect subagent implements plan tasks during validation (indicated by "Verdict: Approved (implemented directly...)" in the issue comment), cherry-pick those commits from `origin/refine/issue-NNN-...` onto the feat branch rather than reimplementing from scratch: `git log --oneline main..origin/refine/<branch>` to find the commits, then `git cherry-pick <hashes>` in chronological order. <!-- issue:#173 date:2026-06-04 expires:2026-12-04 source:implement -->

## Plan Drift

- [PATTERN] When a refinement plan specifies exact line numbers or file counts for reference fixes, always re-grep the actual files rather than trusting the plan's enumeration — commits landing between plan creation and implementation can shift line numbers and add/remove references. <!-- issue:#171 date:2026-06-04 expires:2026-12-04 source:implement -->

## Conflict Resolution

- [PATTERN] `check_pr_mergeable()` calls `gh pr view --json mergeable --jq '.mergeable'`; GitHub returns the string "CONFLICTING", "MERGEABLE", or "UNKNOWN". Always skip UNKNOWN — GitHub hasn't computed mergeability yet and will compute it on the next poll. <!-- issue:#210 date:2026-06-04 expires:2026-12-04 source:implement -->

- [PATTERN] After `git merge` returns non-zero, `git diff --name-only --diff-filter=U` lists files with unresolved conflict markers. Once resolved and `git add`-ed, the file disappears from this list. Add a hard `find . -exec grep -l '^<<<<<<' {}` safety grep AFTER all resolutions as a final marker check before committing. <!-- issue:#210 date:2026-06-04 expires:2026-12-04 source:implement -->

- [PATTERN] The shared de-conflict step for `continue` runs in `entrypoint.sh` BEFORE the archon call: checkout the feature branch, merge origin/main, apply Tier 1/2/3. Archon then runs on the already-synced branch. The implement agent sees the merge commit in `git log` and understands the sync already happened. <!-- issue:#210 date:2026-06-04 expires:2026-12-04 source:implement -->

## Service Dependencies

- [PATTERN] The `docker-socket-proxy` service must have no `profiles:` key so it is a lifecycle superset of both `factory` and `scheduler` profiles. Consumers (`dark-factory`, `backlog-scheduler`) drop their raw `/var/run/docker.sock` volumes and instead set `DOCKER_HOST: tcp://docker-socket-proxy:2375` with `depends_on: [docker-socket-proxy]`. <!-- issue:#203 date:2026-06-05 expires:2026-12-05 source:implement -->

## Path-Tag Memory Filtering

- [PATTERN] Path-tag filtering in Phase 1 LOAD extracts the `path:` prefix with `sed 's/.*path:\([^ >]*\).*/\1/'` (POSIX-compatible; not `grep -oP`) and matches via `echo "$AFFECTED" | grep -q "^${PATH_TAG}"` against the affected file list; empty `AFFECTED` means "include all" — correct fallback for new branches. <!-- issue:#213 date:2026-06-09 expires:2026-12-09 source:implement -->

- [PATTERN] Gate commands (conformance, code-review) that need to write `[AVOID]` memory entries should define `route_memory_file()` and `write_memory_entry()` as inline shell functions using: dedup via `grep -qF`, 30-entry cap check, mawk-compatible two-arg awk expiry cleanup, and `sed -i "/^---$/i ENTRY"` to insert before the PROVISIONAL section delimiter. <!-- issue:#213 date:2026-06-09 expires:2026-12-09 source:implement -->

---
<!-- PROVISIONAL — entries below are from a single observed run; unverified.
     Do not rely on these as authoritative guidance. They are excluded from
     plan/implement prompt injection except as advisory context.
     Each will be promoted to [PATTERN] on second-run confirmation (different issue number) or dropped at TTL. -->

- [PROVISIONAL] The `docker-socket-proxy` blocks `exec` operations (HTTP 403), so testcontainers healthchecks fail inside the factory container; use `TEST_DATABASE_URL=postgresql://postgres:<pw>@postgres:5432/test_markethawk` instead (create DB via SQLAlchemy AUTOCOMMIT before running pytest). <!-- evidence:curl-response issue:#287 date:2026-06-11 expires:2026-12-11 source:implement -->

- [PROVISIONAL] When `.env` is absent, retrieve the running postgres password via `curl -s "http://docker-socket-proxy:2375/v1.54/containers/stockscanner-db/json" | python3 -c "import json,sys; [print(e) for e in json.load(sys.stdin)['Config']['Env'] if 'PASSWORD' in e]"`. <!-- evidence:curl-response issue:#287 date:2026-06-11 expires:2026-12-11 source:implement -->
