# Main-Red Auto-Fix — autonomous pipeline recovery

**Status:** design
**Date:** 2026-06-21
**Epic:** #548 (Dark Factory platform — maintenance, telemetry)
**Sibling spec:** `2026-06-21-epic-autopilot-broaden-reach-design.md` (implement that first)
**Build constraint:** Factory self-edit → **human-implemented** only. New module +
`scheduler.sh` priority are **baked**; need `docker compose build backlog-scheduler` +
`up --force-recreate` to deploy.

## Problem

When the smoke gate trips, `smoke_gate.sh` writes a `main-is-red` sentinel (and a
`main-is-red-issue` regression ticket) which pauses all implementation dispatch
(`scheduler.sh:865`, Priorities 1.5/2/3 gated). Recovery today is either the throttled
"Recheck main" run (which only clears the sentinel if main *self-heals*) or a human fixing
the break. In this repo red main is most often caused by the **pipeline itself** —
smoke-gate env gaps, migrations not-up-to-date, compose/CI regressions — and it can block
the whole factory for hours.

We want a bounded autonomous agent that, when main is red, **diagnoses → fixes →
verifies-green → merges**, and escalates to a human when it can't.

## Decision

A new **Main-Red Auto-Fix** path, separate from Epic Autopilot (different action model: it
edits code and merges to main). A new scheduler priority fires when the sentinel is set; a
new module (`factory_core/main_red_fixer.py`, pure-core + injected-IO) drives one bounded
fix attempt per cycle. Ships **OFF** behind its own kill-switch.

### Trigger & dedupe (`scheduler.sh`)

A new block at the **top of the loop** (highest priority — nothing matters more than green
main), guarded by `MAIN_IS_RED == true` and `MAIN_RED_AUTOFIX_ENABLED == true`:

```sh
if [ "$MAIN_IS_RED" = "true" ] && [ "${MAIN_RED_AUTOFIX_ENABLED:-false}" = "true" ]; then
  if ! fix_container_running; then          # reuse the recheck dedupe pattern (:170)
    dispatch "Fix main" && DISPATCHED="Fix main"
  fi
fi
```

One attempt at a time (dedupe on a running "Fix main" container), one per cycle. The
existing "Recheck main" self-clear path is **left intact** as a fallback for self-healing
breaks.

### Diagnosis input

The fixer reads:
- `${SMOKE_STATE_DIR}/main-is-red-issue` → the regression ticket number, and that ticket's
  body/comments (what `smoke_gate.sh` recorded).
- Reproduces locally via the smoke gate's own checks (`tsc`, python import) and, when
  available, the failing GitHub CI logs for `main`.

### Scope (hard envelope)

**Allowed:** smoke-gate scripts, alembic migrations, `docker-compose*.yml`, `.github/`
workflows, env contracts (`.env*` templates / preview compose), and app code
(`backend/`, `frontend/`).

**Blocked (escalate immediately, never attempt):** `scheduler.sh`, `factory_core/`, the
autopilot/fixer modules themselves — the control loop must not rewrite its own brain. If
diagnosis concludes the root cause lives in the protected zone, the fixer posts the
diagnosis to the regression ticket, notifies a human, and stops (counts as a terminal
escalation, not a retry).

### Fix loop (verify-green-then-merge)

1. Branch from `main` (`fix/main-red-<issue>`).
2. Apply the fix (a `claude -p` coding agent constrained to the allowed scope).
3. Push → open a **ready** (non-draft) PR linking the regression ticket, with the diagnosis
   in the body.
4. **Wait for the branch's full CI to pass.** Poll the PR checks (bounded wait).
5. **CI green → merge** (squash). The existing green-recheck then clears the `main-is-red`
   sentinel and closes the regression ticket — no new sentinel logic needed.
6. **CI red →** treat as a failed attempt (see bounding).

It **never** merges a red or unverified branch.

### Bounding & escalation

- **Attempt cap** `max_attempts` (default **3**) per red event, tracked in a state file
  keyed by the regression-issue number. An attempt = one fix→push→CI cycle.
- On cap reached (or a protected-zone root cause): stop, **leave the last PR open**, post a
  summary to the regression ticket, and send an escalation notification. No further attempts
  until the sentinel clears and a new red event opens a new issue number.
- Per-attempt timeouts on the coding agent and the CI wait (fail → counts as an attempt).

### Notifications (`/api/v1/alerts/system`, fail-soft)

1. **Red detected / fixing** *(warning)* — "🛠️ Main is red (#issue) — auto-fix attempt N/3 in progress."
2. **Recovered** *(info)* — "✅ Main-red auto-fix merged PR #P — main is green again."
3. **Escalation** *(warning)* — cap reached or protected-zone cause; "human needed."

## Module shape (`dark-factory/scripts/factory_core/main_red_fixer.py`)

Pure-core + injected-IO, mirroring `epic_autopilot.py`:

- **Pure:** `classify_scope(target_paths, allowed, blocked)` → allowed | protected | unknown;
  `should_escalate(attempts, cap, scope_verdict)`; attempt-state read/record with cap +
  per-issue keying; PR-checks → green/red/pending reducer.
- **LiveIO:** `read_regression(issue)`, `reproduce()` (run smoke checks), `apply_fix(prompt)`
  (`claude -p` constrained agent), `open_pr(branch)`, `poll_ci(pr)`, `merge(pr)`,
  `comment()`, `notify()`.
- `run_once(cfg, io, state)` → one bounded attempt; returns
  `{outcome: fixing|merged|escalated|noop, issue, pr}`.

## Config (`.claude/skills/refinement/config.yaml`, new `main_red_autofix:` section)

```yaml
main_red_autofix:
  enabled: false                 # kill-switch — ships OFF (env MAIN_RED_AUTOFIX_ENABLED)
  model: claude-opus-4-8
  max_attempts: 3                # fix→CI cycles per red event
  ci_wait_minutes: 20            # bounded wait for branch CI
  allowed_paths: [ "backend/", "frontend/", "alembic/", "dark-factory/smoke_gate.sh",
                   "docker-compose", ".github/", ".env" ]
  blocked_paths: [ "dark-factory/scheduler.sh", "dark-factory/scripts/factory_core/",
                   "dark-factory/entrypoint.sh" ]
```

## Known limitations (call out in implementation)

- **Baked-file fixes don't self-deploy.** A fix to `smoke_gate.sh` (a baked file) lands in
  git and goes green in CI, but the *running* scheduler/gate keeps the old baked copy until a
  human rebuilds the image + force-recreates. The fixer notes this in the recovered
  notification when its diff touches baked paths.
- The fixer reproduces with the smoke gate's lightweight checks (`tsc` + python import); a
  red caused by something the smoke gate doesn't run (e.g. a full integration suite) is
  diagnosed from CI logs only.

## Error handling / safety summary

Red-only trigger · highest priority · one attempt/cycle with container dedupe · allowed/
blocked path envelope (protected zone → immediate escalation) · verify-green-before-merge
(never lands red) · attempt cap + escalate · separate kill-switch (ships OFF) · every action
commented on the regression ticket + notified · existing recheck self-clear left intact.

## Validation

- **Python unit tests** (mocked): `classify_scope` (allowed/protected/unknown);
  protected-zone cause → escalate without attempting; attempt-cap enforcement + per-issue
  keying; CI-checks reducer (green/red/pending); never-merge-on-red; outcome shapes;
  notification payloads.
- **Scheduler bash test** (`SCHEDULER_SOURCE_ONLY`): the "Fix main" block fires only when
  `MAIN_IS_RED=true` + enabled + no fix container running; does not fire when green.
- **Manual (staging):** induce a red main with an app-code break (tsc/import) → confirm
  branch → PR → CI green → merge → sentinel cleared + ticket closed + recovered notification.
  Induce a protected-zone cause → confirm immediate escalation, no PR. Force `max_attempts`
  → confirm escalation notification + PR left open.

## Accepted trade-offs

- Auto-merging to main is gated on branch-CI-green, so it cannot make main *worse*, but it
  does bypass human pre-merge review for pipeline fixes — bounded by the attempt cap + scope
  envelope + kill-switch.
- Cannot fix breaks rooted in its own brain (by design) — those escalate.
- Baked-file fixes need a human rebuild to deploy (noted above).
