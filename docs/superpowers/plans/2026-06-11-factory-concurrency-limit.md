# Dark Factory Configurable Concurrency Limit — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the backlog scheduler run up to `FACTORY_WIP_LIMIT` concurrent dark-factory containers (default 1, locally set to 2), changeable via `.archon/.env` without an image rebuild.

**Architecture:** `dark-factory/scheduler.sh` gains a `FACTORY_WIP_LIMIT` config var and a tiny `factory_at_capacity()` helper; the hardcoded "any running container → skip cycle" guard in the main loop calls the helper instead. The helper lives above the `SCHEDULER_SOURCE_ONLY` line so the existing bash unit-test harness can source and test it. No compose changes: the scheduler already loads `.archon/.env` via `env_file`.

**Tech Stack:** Bash, Docker Compose. Tests: `dark-factory/tests/test_scheduler.sh` (sourced-function harness with stubs, run via `bash`).

**Spec:** `docs/superpowers/specs/2026-06-11-factory-concurrency-limit-design.md` · **Ticket:** #347

---

### Task 1: `factory_at_capacity()` + `FACTORY_WIP_LIMIT` (TDD)

**Files:**
- Modify: `dark-factory/scheduler.sh` (config block ~line 14, helpers ~line 116, startup log ~line 632, main-loop guard ~lines 719–727, orphan-sweep comment ~lines 729–735, cycle-summary echoes ~lines 940–944)
- Test: `dark-factory/tests/test_scheduler.sh` (new section L, insert before the `Cleanup` section at the bottom)

- [ ] **Step 1: Write the failing tests**

In `dark-factory/tests/test_scheduler.sh`, insert immediately before the `# Cleanup` section (after section K's stub-restore block):

```bash
# ==========================================
# L: factory_at_capacity / FACTORY_WIP_LIMIT
# ==========================================
echo ""
echo "--- L: factory_at_capacity ---"

assert_eq "L0: FACTORY_WIP_LIMIT defaults to 1" "1" "${FACTORY_WIP_LIMIT:-}"

FACTORY_WIP_LIMIT=1
factory_at_capacity 0 \
  && assert_eq "L1: 0 running, limit 1 → below capacity" "0" "1" \
  || assert_eq "L1: 0 running, limit 1 → below capacity" "0" "0"
factory_at_capacity 1 \
  && assert_eq "L2: 1 running, limit 1 → at capacity" "0" "0" \
  || assert_eq "L2: 1 running, limit 1 → at capacity" "0" "1"

FACTORY_WIP_LIMIT=2
factory_at_capacity 1 \
  && assert_eq "L3: 1 running, limit 2 → below capacity" "0" "1" \
  || assert_eq "L3: 1 running, limit 2 → below capacity" "0" "0"
factory_at_capacity 2 \
  && assert_eq "L4: 2 running, limit 2 → at capacity" "0" "0" \
  || assert_eq "L4: 2 running, limit 2 → at capacity" "0" "1"
factory_at_capacity 3 \
  && assert_eq "L5: 3 running, limit 2 → at capacity" "0" "0" \
  || assert_eq "L5: 3 running, limit 2 → at capacity" "0" "1"

FACTORY_WIP_LIMIT=1
```

(The `&& assert / || assert` pattern matches sections D/H — `assert_eq "desc" "0" "0"` records pass, `"0" "1"` records fail.)

- [ ] **Step 2: Run tests to verify the new section fails**

Run: `bash dark-factory/tests/test_scheduler.sh`
Expected: L0 FAILs (`expected='1' got=''`); L1–L5 fail with `factory_at_capacity: command not found` (counted as FAIL or visible as command errors). All pre-existing sections A–K still PASS. Final line shows non-zero failed count.

- [ ] **Step 3: Implement in `dark-factory/scheduler.sh`**

3a. Config block — after the `CONFLICT_RESOLUTION_ENABLED` line (line 14), add:

```bash
# Max concurrent factory containers, any run type (implement/refine/plan/deconflict/
# close). Override in .archon/.env — takes effect on scheduler recreate, no rebuild.
FACTORY_WIP_LIMIT="${FACTORY_WIP_LIMIT:-1}"
```

3b. Helper — directly below `count_factory_running()` (after line 116), add:

```bash
# True when the running factory-container count ($1) has reached FACTORY_WIP_LIMIT.
factory_at_capacity() {
  [ "$1" -ge "$FACTORY_WIP_LIMIT" ]
}
```

3c. Main-loop guard — replace lines 719–727:

```bash
  # Guard: only one factory container at a time (Claude Max rate limit). Everything
  # below DISPATCHES factory work, so it waits for the current run; the CI gate above
  # has already run regardless of factory activity.
  FACTORY_RUNNING=$(count_factory_running)
  if [ "$FACTORY_RUNNING" -gt 0 ]; then
    echo "[$(date -u +%FT%TZ)] skip=factory_running count=${FACTORY_RUNNING}"
    sleep "$POLL_INTERVAL"
    continue
  fi
```

with:

```bash
  # Guard: cap concurrent factory containers at FACTORY_WIP_LIMIT (Claude Max 5h-window
  # burn scales with concurrency — default 1, override in .archon/.env). Everything
  # below DISPATCHES factory work, so it waits for a free slot; the CI gate above has
  # already run regardless of factory activity.
  FACTORY_RUNNING=$(count_factory_running)
  if factory_at_capacity "$FACTORY_RUNNING"; then
    echo "[$(date -u +%FT%TZ)] skip=factory_at_capacity running=${FACTORY_RUNNING}/${FACTORY_WIP_LIMIT}"
    sleep "$POLL_INTERVAL"
    continue
  fi
```

3d. Orphan-sweep comment — in the comment block starting `# --- Sweep: recover orphaned "In progress" items ---` (~line 729), replace the two sentences:

```
  # We only reach here when no factory container is running (FACTORY_RUNNING guard
  # above), so any issue still in "In progress" was abandoned mid-run. The usual
```

with:

```
  # We reach here whenever a factory slot is free (capacity guard above). An issue in
  # "In progress" whose container is alive is skipped by is_issue_running below; one
  # with no container was abandoned mid-run. The usual
```

3e. Startup WIP log line (~line 632) — replace:

```bash
echo "WIP limits: in_progress=${MAX_IN_PROGRESS} in_review=${MAX_IN_REVIEW}"
```

with:

```bash
echo "WIP limits: in_progress=${MAX_IN_PROGRESS} in_review=${MAX_IN_REVIEW} factory=${FACTORY_WIP_LIMIT}"
```

3f. Cycle-summary echoes (~lines 940–944) — in BOTH the `dispatched=` and `skip=nothing_to_do` echo lines, insert `factory_running=${FACTORY_RUNNING}/${FACTORY_WIP_LIMIT} ` immediately before `refine_running=`.

- [ ] **Step 4: Run tests to verify everything passes**

Run: `bash dark-factory/tests/test_scheduler.sh`
Expected: all sections A–L PASS, `Results: N passed, 0 failed`, exit 0.

Also run the other two suites (they source the same script and must not regress):
`bash dark-factory/tests/test_159_regression.sh && bash dark-factory/tests/test_has_new_comment_after_report.sh`
Expected: 0 failed in each.

- [ ] **Step 5: Commit**

```bash
git add dark-factory/scheduler.sh dark-factory/tests/test_scheduler.sh
git commit -m "feat(factory): configurable concurrent-run limit via FACTORY_WIP_LIMIT (#347)"
```

---

### Task 2: Set local limit to 2 in `.archon/.env`

**Files:**
- Modify: `.archon/.env` (gitignored — verify with `git check-ignore .archon/.env` before editing; do NOT commit)

- [ ] **Step 1: Append the override**

Add this line to `.archon/.env` (Edit tool, or append preserving existing content — never truncate this file, it holds secrets):

```bash
FACTORY_WIP_LIMIT=2
```

- [ ] **Step 2: Confirm it is not staged**

Run: `git status --short .archon/`
Expected: no output (file ignored).

---

### Task 3: Rebuild image, recreate scheduler, validate live

`scheduler.sh` is baked into the shared dark-factory image, so this needs one rebuild. The same image serves dispatched factory runs (which don't read this var) — harmless.

- [ ] **Step 1: Rebuild and recreate**

```bash
docker compose --profile scheduler build backlog-scheduler
docker compose --profile scheduler up -d --force-recreate backlog-scheduler
```

Expected: build succeeds; `backlog-scheduler` container recreated and running.

- [ ] **Step 2: Validate startup + cycle logs**

Run: `docker logs backlog-scheduler --tail 30`
Expected:
- `WIP limits: in_progress=999 in_review=999 factory=2`
- `Backlog scheduler started (poll every 60s)`
- cycle summary lines containing `factory_running=0/2` (or `1/2` if a run is active), OR `skip=factory_at_capacity running=2/2` once both slots fill.
- No `SCHED_UNHANDLED_ERR` lines.

- [ ] **Step 3: Validate the changeability story (the actual feature)**

Flip the knob down and back to prove env-only changes work without rebuild:

```bash
# Temporarily set FACTORY_WIP_LIMIT=1 in .archon/.env, then:
docker compose --profile scheduler up -d backlog-scheduler
docker logs backlog-scheduler --tail 5
```

Expected: compose recreates the container (env change detected) and the new startup line shows `factory=1`. Restore `FACTORY_WIP_LIMIT=2` and `up -d` again; expect `factory=2`.

- [ ] **Step 4: Post plan summary + close out ticket #347**

Comment on the ticket (use a temp file + `--body-file`, never a heredoc): one-paragraph summary of the change, the commit SHA, and the validation evidence from Steps 2–3. Push `main` (`git push`) so the committed default ships.
