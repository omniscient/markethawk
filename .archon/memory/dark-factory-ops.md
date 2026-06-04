# Dark Factory Ops — Accumulated Lessons

This file is maintained automatically by the dark factory implement agent. Do not edit manually.
Entries are advisory. If an entry conflicts with CLAUDE.md or ARCHITECTURE.md, follow those documents.

## Preview Stack

- [PATTERN] Preview ports follow the formula `1{ISSUE_NUM_PADDED}XX` where `ISSUE_NUM_PADDED` is zero-padded to two digits and XX is the service suffix (33=frontend, 80=backend, 54=postgres, 63=redis). Example: issue #3 → frontend `:10333`, backend `:10380`. <!-- bootstrap date:2026-06-02 expires:2026-12-02 source:implement -->

## Container Root and Mounts

- [PATTERN] The dark factory container runs as the `factory` user (uid 1000) with `/workspace` as the working directory. The repo is cloned to `/workspace/markethawk`. Paths inside the container that start with `/opt/` (e.g. `/opt/refinement-skills/`) are read-only mounts from the host and are not git-tracked by the cloned repo. <!-- bootstrap date:2026-06-02 expires:2026-12-02 source:implement -->

- [PATTERN] `.archon/commands/` files are read from the cloned repo at runtime (live — no image rebuild needed). `.claude/skills/refinement/` files are COPYed into the image as `/opt/refinement-skills/` at build time (requires `docker compose --profile factory build dark-factory` to pick up changes). New prompt files for pipeline agents (e.g. `conformance-reviewer-prompt.md`) go in `.claude/skills/refinement/`. <!-- issue:#162 date:2026-06-03 expires:2026-12-03 source:implement -->

## Seed Files

- [PATTERN] Seed files in `dark-factory/seed/seed/` are named with a two-digit prefix (`00_`, `01_`, ...) so they apply in deterministic order. The next available slot for a new baseline module is determined by `ls dark-factory/seed/seed/ | sort | tail -1`. <!-- bootstrap date:2026-06-02 expires:2026-12-02 source:implement -->

- [AVOID] Do not embed data directly in Alembic migration files — migrations are schema-only. Feature-specific seed data goes in `dark-factory/seed/99_feature.sql` (idempotent, `ON CONFLICT DO NOTHING`). Data needed across multiple features goes in a new numbered baseline module. <!-- bootstrap date:2026-06-02 expires:2026-12-02 source:implement -->

## YAML Block Scalar / Bash Multiline Strings

- [AVOID] Never use multiline bash string assignments with literal newlines inside a YAML `|` block scalar — non-blank content at column 1 terminates the block scalar, causing a YAML parse error. Use `printf "line1\n\nline2"` or `$'\n'` concatenation instead (e.g. `VAR=$(printf "### Header\n\n%s" "${BODY}")`). <!-- issue:#162 date:2026-06-03 expires:2026-12-03 source:implement -->

## Awk Compatibility

- [AVOID] The three-argument form of `match()` — `match($0, /regex/, arr)` — is a GNU awk (gawk) extension. The dark factory container ships `mawk`, which does not support this form. Use the two-argument form with `substr($0, RSTART+N, LEN)` for capture: `found=match($0, /expires:[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]/); if (found) { val=substr($0, RSTART+8, 10) }`. <!-- issue:#149 date:2026-06-02 expires:2026-12-02 source:implement -->

## Memory Entry Format

- [PATTERN] Every memory entry must carry an `expires:YYYY-MM-DD` inline comment with a 6-month TTL from the date it was written. Format: `<!-- issue:#NNN date:YYYY-MM-DD expires:YYYY-MM-DD source:implement -->`. The expiry date is used by the awk cleanup one-liner to prune stale lessons automatically. <!-- issue:#149 date:2026-06-02 expires:2026-12-02 source:implement -->

## Scheduler Testing

- [PATTERN] When writing tests for `dark-factory/scheduler.sh` with `SCHEDULER_SOURCE_ONLY=1`, set stub credentials (`GH_TOKEN=stub CLAUDE_CODE_OAUTH_TOKEN=stub`) before sourcing — the credential validation block runs before the `SCHEDULER_SOURCE_ONLY` guard and will abort otherwise. <!-- issue:#160 date:2026-06-03 expires:2026-12-03 source:implement -->

- [FIX] Functions defined in `scheduler.sh` (e.g. `set_board_status`, `is_issue_running`) override `export -f` stubs when the scheduler is sourced. Re-define stubs AFTER the `source` call to win the override race — do not rely on exported functions surviving the source. <!-- issue:#160 date:2026-06-03 expires:2026-12-03 source:implement -->

- [AVOID] `grep -c "keyword"` against a stub log that includes multi-line command bodies (e.g. `gh issue comment ... --body "..."`) can over-count if the keyword appears in the body text. Use a more specific pattern like `grep -c -- '--add-label keyword'` to target the command argument, not the body content. <!-- issue:#160 date:2026-06-03 expires:2026-12-03 source:implement -->

## Scheduler Architecture

- [PATTERN] The `backlog-scheduler` uses a named Docker volume `scheduler_state` mounted at `/var/lib/dark-factory` for durable retry counters. `STATE_FILE` is `${SCHEDULER_STATE_DIR}/scheduler-state.json`. Running `docker compose down -v` would destroy the volume — use `docker compose down` (without `-v`) for normal restarts. <!-- issue:#160 date:2026-06-03 expires:2026-12-03 source:implement -->

- [PATTERN] All `dispatch()` call sites in `scheduler.sh` must use `if dispatch ...; then ... fi` guards. A bare `dispatch "..."` under `set -e` exits the daemon on non-zero return, which triggers `restart: unless-stopped` and wipes the (old `/tmp`) retry counter — the root cause of the #159 loop. <!-- issue:#160 date:2026-06-03 expires:2026-12-03 source:implement -->

## Codeindex / MCP Integration

- [AVOID] `pip install codeindex` installs an unrelated PyPI package (`cr0hn/the-opensource-context`). Always use `pip install "git+https://github.com/scheidydude/codeindex.git"` — no alternative install path exists. <!-- issue:#159 date:2026-06-03 expires:2026-12-03 source:implement -->

- [PATTERN] Register a project-scoped MCP server in `entrypoint.sh` by writing the cloned repo's `.claude/settings.local.json` (gitignored) with the tool's absolute path: `$(which codeindex)`. Never rely on `"command": "codeindex"` — Claude Code does not inherit the shell PATH and will fail to launch the server. <!-- issue:#159 date:2026-06-03 expires:2026-12-03 source:implement -->

- [PATTERN] For two-pass index regeneration (startup + post-implement), add two workflow nodes: `update-codeindex` (depends on `setup-branch`, before `implement`) and `regen-codeindex` (depends on `implement`, before `preview-up`). `preview-up` should depend on `regen-codeindex`, not `implement`, so the committed artifact always matches the final code in the PR. <!-- issue:#159 date:2026-06-03 expires:2026-12-03 source:implement -->

- [PATTERN] Pre-commit hooks that invoke advisory/optional tools (e.g. `codeindex-blast`) must always exit 0 — use `|| true` or `; exit 0`. A non-zero exit from a pre-commit hook blocks the commit and will abort an autonomous factory run. <!-- issue:#159 date:2026-06-03 expires:2026-12-03 source:implement -->

## Preview Environment Differentiator

- [PATTERN] When a workflow node's tail depends on a conditionally-built resource (e.g. preview stack), use a gated executor pattern rather than a conditional node: always run the node, read the decision from the prior step, and write a `PREVIEW_SKIPPED` marker to `$ARTIFACTS_DIR/preview_env.sh` so all downstream steps can branch on it uniformly. <!-- issue:#178 date:2026-06-04 expires:2026-12-04 source:implement -->

- [PATTERN] `$ARTIFACTS_DIR/preview_env.sh` is the single source of truth for preview state across `preview-up`, `validate`, `push-and-pr`, and `report`. Downstream steps source this file rather than parsing step output, except for the two nodes that need `grep '^PREVIEW_SKIPPED='` on step output directly. <!-- issue:#178 date:2026-06-04 expires:2026-12-04 source:implement -->

- [PATTERN] For fail-safe LLM classifier guards, skip only on explicit `false` (string comparison `[ "$VAR" = "false" ]`); any other value — including empty string or garbled output — falls through to the safe direction (building the preview). This prevents wrongly skipped previews when the classifier errors. <!-- issue:#178 date:2026-06-04 expires:2026-12-04 source:implement -->

## Environment and Credentials

- [PATTERN] Every new environment variable introduced by a feature must be documented in `ENV_VARIABLES.md` with its default value and a one-line description. CLAUDE.md references ENV_VARIABLES.md as the authoritative env var reference. <!-- bootstrap date:2026-06-02 expires:2026-12-02 source:implement -->

- [PATTERN] AI credentials (`CLAUDE_CODE_OAUTH_TOKEN` or `ANTHROPIC_API_KEY`) and `GH_TOKEN` belong in `.archon/.env`, not in `.env`. The `.archon/.env` file is gitignored to keep secrets out of the repo. <!-- bootstrap date:2026-06-02 expires:2026-12-02 source:implement -->

## Plan Drift

- [PATTERN] When a refinement plan specifies exact line numbers or file counts for reference fixes, always re-grep the actual files (`grep -rn "Docs/" ...`) rather than trusting the plan's enumeration — commits landing between plan creation and implementation can shift line numbers and add/remove references (e.g. PR #179 slimmed CLAUDE.md, changing a stated 1-ref count to 3 actual refs). <!-- issue:#171 date:2026-06-04 expires:2026-12-04 source:implement -->

## PR Iteration — Removing Specific Commits

- [PATTERN] When feedback is "remove commit X from this PR and move to a separate branch": (1) create the new branch from the commit just before X, (2) cherry-pick X onto the new branch, (3) push the new branch, (4) create a GitHub issue + add to project in Blocked column (`gh project item-add` + GraphQL mutation on `PVTSSF_lAHOAAFds84BWh4wzhR1VaA` with option id `93d87b2f`), (5) on the original branch run `git reset --hard <parent-of-X>`, (6) force-push. Use `git reset --hard` (not `git revert`) when removing a tip commit — revert adds noise; reset keeps history clean. <!-- issue:#174 date:2026-06-04 expires:2026-12-04 source:implement -->

- [PATTERN] The MarketHawk Kanban has no `blocked` label. To place an issue in the Blocked column, use `needs-discussion` label + set project status via GraphQL (`updateProjectV2ItemFieldValue` with field `PVTSSF_lAHOAAFds84BWh4wzhR1VaA`, option `93d87b2f`). <!-- issue:#174 date:2026-06-04 expires:2026-12-04 source:implement -->
