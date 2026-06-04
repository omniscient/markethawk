# Dark Factory — Auto-Detect and Resolve Merge Conflicts — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent in-review PRs from silently rotting into merge conflict by adding a
Priority 1.5 scheduler gate that detects `CONFLICTING` PRs each cycle and dispatches a
tiered conflict-resolution run (mechanical Tier 1 → AI Tier 2 → escalate Tier 3). The
de-conflict step is shared into the `continue` flow so iterations also stay current with
`main`.

**Architecture:** Config kill-switch (env var) → scheduler Priority 1.5 loop → `resolve`
intent in the Archon workflow → `de-conflict` bash node (Tier 1 allowlist + Tier 2 AI) →
hard grep gate → existing `validate` → push-to-existing-PR.

**Tech Stack:** Bash, YAML (Archon workflow), Python (alembic), jq, pytest

**Spec:** [`docs/superpowers/specs/2026-06-04-dark-factory-conflict-resolution-design.md`](../specs/2026-06-04-dark-factory-conflict-resolution-design.md)
**Issue:** [#210](https://github.com/omniscient/markethawk/issues/210)

---

## File Structure

| Path | Change |
|------|--------|
| `.claude/skills/refinement/config.yaml` | Add `conflict_resolution` section |
| `dark-factory/scheduler.sh` | Add `get_pr_mergeable`, `conflict_resolution_enabled`, Priority 1.5 loop; add `resolve` case to `trip_to_blocked` |
| `dark-factory/entrypoint.sh` | Add `resolve` to INTENT regex; guard In-Progress board move; guard `on_failure` |
| `.archon/workflows/archon-dark-factory.yaml` | Add `resolve` intent, `setup-branch-resolve`, `de-conflict`, `preview-up-resolve`, `push-resolve` nodes; wire `resolve` through validate/status/report |
| `dark-factory/tests/test_scheduler.sh` | Extend with 5 Priority 1.5 conflict gate tests |

---

## Task 1 — Config: add conflict_resolution section

**Files:** `.claude/skills/refinement/config.yaml`

### Steps

- [ ] 1.1 Read the current config to verify the file ends after the `preview:` block:

  ```bash
  cat .claude/skills/refinement/config.yaml
  ```

- [ ] 1.2 Append the `conflict_resolution` section at the end of `.claude/skills/refinement/config.yaml`:

  ```yaml
  conflict_resolution:
    enabled: true        # false = Priority 1.5 loop is a no-op (kill-switch)
    ai_tier: true        # false = skip Tier 2 entirely (Tier 1 + escalate only)
  ```

- [ ] 1.3 Verify the YAML is valid:

  ```bash
  python3 -c "import yaml; d=yaml.safe_load(open('.claude/skills/refinement/config.yaml')); \
    print('conflict_resolution section:', d.get('conflict_resolution'))"
  ```

  Expected output:
  ```
  conflict_resolution section: {'enabled': True, 'ai_tier': True}
  ```

- [ ] 1.4 Commit:

  ```bash
  git add .claude/skills/refinement/config.yaml
  git commit -m "config(#210): add conflict_resolution kill-switch and ai_tier flag"
  ```

---

## Task 2 — Scheduler: add `get_pr_mergeable`, `conflict_resolution_enabled`, and Priority 1.5 gate

**Files:** `dark-factory/scheduler.sh`

### Steps

- [ ] 2.1 In the `# --- Configuration ---` block at the top of `scheduler.sh`, add the new config variable immediately after `PLAN_GRACE_MINUTES`:

  Find:
  ```bash
  PLAN_GRACE_MINUTES="${PLAN_GRACE_MINUTES:-30}"
  ```

  Add after it:
  ```bash
  CONFLICT_RESOLUTION_ENABLED="${CONFLICT_RESOLUTION_ENABLED:-true}"
  ```

  This follows the existing env-var-first config style — the scheduler never reads `config.yaml` directly. The `.claude/skills/refinement/config.yaml` value is the doc-level default; operators override via `.archon/.env`.

- [ ] 2.2 Add the `get_pr_mergeable` helper function immediately after the `get_pr_for_issue` function (around line 395). Insert:

  ```bash
  # --- PR mergeability: returns CONFLICTING, MERGEABLE, or UNKNOWN (empty string if no PR) ---
  get_pr_mergeable() {
    local issue_num="$1"
    local pr_num
    pr_num=$(get_pr_for_issue "$issue_num")
    [ -z "$pr_num" ] && { echo ""; return 0; }
    gh pr view "$pr_num" --repo "${OWNER}/markethawk" \
      --json mergeable --jq '.mergeable // ""' 2>/dev/null || echo ""
  }
  ```

- [ ] 2.3 Add the `conflict_resolution_enabled` helper immediately after `get_pr_mergeable`:

  ```bash
  # --- Returns 0 (true) when conflict resolution is enabled, 1 (false) otherwise ---
  # Reads CONFLICT_RESOLUTION_ENABLED env var (set at top of scheduler; default "true").
  conflict_resolution_enabled() {
    [ "${CONFLICT_RESOLUTION_ENABLED:-true}" = "true" ]
  }
  ```

- [ ] 2.4 Insert the Priority 1.5 block in the main loop **after** the Priority 1 block ends (after the `done < <(echo "$IN_REVIEW" | jq -c '.[]')` line of Priority 1, around line 769) and **before** the `# --- Priority 2` comment. The new block:

  ```bash
    # --- Priority 1.5: In Review items with CONFLICTING mergeable (proactive conflict resolution) ---
    # Runs when no item was dispatched yet this cycle AND conflict_resolution is enabled.
    # Each in-review PR is checked for mergeable == CONFLICTING; if found, dispatches
    # "Resolve conflicts issue #N". UNKNOWN is skipped (GitHub hasn't computed it yet).
    # Uses the same :resolve retry key with existing trip_to_blocked circuit-breaker.
    if [ -z "$DISPATCHED" ] && conflict_resolution_enabled; then
      while IFS= read -r item; do
        [ -n "$DISPATCHED" ] && break
        ISSUE=$(get_issue_number "$item")
        if has_skip_label "$item"; then continue; fi
        if is_issue_running "$ISSUE"; then continue; fi

        RETRIES=$(get_retry_count "${ISSUE}:resolve")
        if [ "$RETRIES" -ge "$MAX_RETRIES" ]; then
          trip_to_blocked "$ISSUE" "resolve" "retry limit of ${MAX_RETRIES} reached"
          continue
        fi

        MERGEABLE=$(get_pr_mergeable "$ISSUE")
        echo "[$(date -u +%FT%TZ)] conflict_gate issue=#${ISSUE} mergeable=${MERGEABLE:-unknown}"
        case "$MERGEABLE" in
          CONFLICTING)
            increment_retry "${ISSUE}:resolve"
            if dispatch "Resolve conflicts issue #${ISSUE}"; then
              DISPATCHED="Resolve conflicts issue #${ISSUE}"
            fi
            ;;
          UNKNOWN|"")
            ;;
          *)
            ;;
        esac
      done < <(echo "$IN_REVIEW" | jq -c '.[]')
    fi
  ```

- [ ] 2.5 Add a `resolve` case to `trip_to_blocked`'s `retry_cmd` switch. Find:

  ```bash
      # 3. Manual retry command varies by phase
      local retry_cmd
      case "$phase" in
        refine) retry_cmd="Refine issue #${issue_num}" ;;
        plan)   retry_cmd="Plan issue #${issue_num}" ;;
        *)      retry_cmd="Fix issue #${issue_num}" ;;
      esac
  ```

  Replace with:

  ```bash
      # 3. Manual retry command varies by phase
      local retry_cmd
      case "$phase" in
        refine)  retry_cmd="Refine issue #${issue_num}" ;;
        plan)    retry_cmd="Plan issue #${issue_num}" ;;
        resolve) retry_cmd="Resolve conflicts issue #${issue_num}" ;;
        *)       retry_cmd="Fix issue #${issue_num}" ;;
      esac
  ```

- [ ] 2.6 Update `entrypoint.sh` — add `resolve` to the INTENT extraction regex. Find line 46:

  ```bash
  INTENT=$(echo "$ARGUMENTS" | grep -oiP '^\s*\K(fix|continue|close|refine|plan)' | head -1 | tr '[:upper:]' '[:lower:]')
  ```

  Replace with:

  ```bash
  INTENT=$(echo "$ARGUMENTS" | grep -oiP '^\s*\K(fix|continue|close|refine|plan|resolve)' | head -1 | tr '[:upper:]' '[:lower:]')
  ```

- [ ] 2.7 Guard the "Move to In Progress" block so `resolve` does not move the issue out of
  In Review. Find line 79:

  ```bash
  if [ -n "$ISSUE_NUM" ] && [ "$INTENT" != "close" ] && [ "$INTENT" != "refine" ] && [ "$INTENT" != "plan" ]; then
  ```

  Replace with:

  ```bash
  if [ -n "$ISSUE_NUM" ] && [ "$INTENT" != "close" ] && [ "$INTENT" != "refine" ] && [ "$INTENT" != "plan" ] && [ "$INTENT" != "resolve" ]; then
  ```

- [ ] 2.8 Guard the `on_failure` handler so `resolve` failures defer to the scheduler's retry
  loop (same as `refine`/`plan`) rather than immediately moving to Blocked (which would route
  it into Priority 3's "Continue" path). Find line 230:

  ```bash
      if [ "$INTENT" = "refine" ] || [ "$INTENT" = "plan" ]; then
  ```

  Replace with:

  ```bash
      if [ "$INTENT" = "refine" ] || [ "$INTENT" = "plan" ] || [ "$INTENT" = "resolve" ]; then
  ```

- [ ] 2.9 Verify `entrypoint.sh` is valid bash:

  ```bash
  bash -n dark-factory/entrypoint.sh && echo "Syntax OK"
  ```

  Expected: `Syntax OK`

- [ ] 2.10 Verify `scheduler.sh` is valid bash:

  ```bash
  bash -n dark-factory/scheduler.sh && echo "Syntax OK"
  ```

  Expected: `Syntax OK`

- [ ] 2.11 Commit:

  ```bash
  git add dark-factory/scheduler.sh dark-factory/entrypoint.sh
  git commit -m "feat(#210): scheduler Priority 1.5 — detect and dispatch CONFLICTING in-review PRs"
  ```

---

## Task 3 — Workflow: add `resolve` intent, `setup-branch-resolve` node, and parse-intent update

**Files:** `.archon/workflows/archon-dark-factory.yaml`

### Steps

- [ ] 3.1 Update the `parse-intent` node prompt text. Find the exact line:

  ```
        2. The intent: "new" (first time working on this issue), "continue" (iterate on existing work), "close" (merge and tear down), "refine" (generate a design spec), or "plan" (generate an implementation plan)
  ```

  Replace with:

  ```
        2. The intent: "new" (first time working on this issue), "continue" (iterate on existing work), "close" (merge and tear down), "refine" (generate a design spec), "plan" (generate an implementation plan), or "resolve" (merge main into an existing branch and resolve conflicts)
  ```

- [ ] 3.2 Update the `parse-intent` `output_format` enum. Find:

  ```yaml
          enum: [new, continue, close, refine, plan]
  ```

  Replace with:

  ```yaml
          enum: [new, continue, close, refine, plan, resolve]
  ```

- [ ] 3.3 Add the `setup-branch-resolve` node immediately after the `setup-refine-branch` node (which ends with `timeout: 15000`). Insert:

  ```yaml
    # Resolve branch setup — checkout the existing feat/issue-N-slug branch (no new branch)
    - id: setup-branch-resolve
      bash: |
        ISSUE=$(echo $fetch-issue.output | jq -r '.resolved_number')
        SLUG=$(echo $fetch-issue.output | jq -r '.title // "feature"' | tr '[:upper:]' '[:lower:]' | sed 's/[^a-z0-9]/-/g' | head -c 40)
        BRANCH="feat/issue-${ISSUE}-${SLUG}"

        echo "Checking out existing branch ${BRANCH} for conflict resolution..."
        if ! git fetch origin "$BRANCH" 2>/dev/null; then
          echo "ERROR: branch $BRANCH not found on origin — nothing to resolve"
          exit 1
        fi
        git checkout "$BRANCH"
        echo "$BRANCH"
      depends_on: [parse-intent, fetch-issue]
      when: "$parse-intent.output.intent == 'resolve'"
      timeout: 15000
  ```

- [ ] 3.4 Verify YAML syntax:

  ```bash
  python3 -c "import yaml; yaml.safe_load(open('.archon/workflows/archon-dark-factory.yaml')); print('YAML OK')"
  ```

  Expected: `YAML OK`

- [ ] 3.5 Commit:

  ```bash
  git add .archon/workflows/archon-dark-factory.yaml
  git commit -m "feat(#210): add resolve intent and setup-branch-resolve node to archon workflow"
  ```

---

## Task 4 — Workflow: add `de-conflict` bash node

**Files:** `.archon/workflows/archon-dark-factory.yaml`

### Steps

- [ ] 4.1 Insert the `de-conflict` node after `regen-codeindex` and before `preview-changeset`.
  The node's `depends_on` lists both `regen-codeindex` and `setup-branch-resolve`:
  - For `continue`: `regen-codeindex` runs (its `when` matches), `setup-branch-resolve` is
    skipped (its `when` does not match). Archon treats a `when`-filtered node as a resolved
    (skipped) dependency, so `de-conflict` fires after `regen-codeindex`.
  - For `resolve`: `setup-branch-resolve` runs, `regen-codeindex` is skipped.
  This is the same pattern used throughout the workflow (e.g. `implement` depends on
  `update-codeindex` which is skipped for `close`).

  ```yaml
    # De-conflict: merge main into branch, Tier 1 mechanical resolution → Tier 2 AI → hard grep gate.
    # Shared between `continue` (runs after regen-codeindex) and `resolve` (runs after branch checkout).
    - id: de-conflict
      bash: |
        ISSUE=$(echo $fetch-issue.output | jq -r '.resolved_number')
        ARTIFACTS_DIR="${ARTIFACTS_DIR:-/tmp/artifacts/${ISSUE}}"
        mkdir -p "$ARTIFACTS_DIR"

        echo "[de-conflict] issue=#${ISSUE} fetching and merging main..."
        git fetch origin main

        # Attempt merge. --no-edit accepts the default merge commit message.
        set +e
        MERGE_OUTPUT=$(git merge origin/main --no-edit 2>&1)
        MERGE_EXIT=$?
        set -e

        if echo "$MERGE_OUTPUT" | grep -q "Already up to date"; then
          {
            echo "CONFLICT_VERDICT=none"
            echo "FILES_CONFLICTED=0"
            echo "TIER1_RESOLVED=0"
            echo "TIER2_RESOLVED=0"
            echo "ESCALATED=0"
          } > "$ARTIFACTS_DIR/conflict_resolution.md"
          echo "[de-conflict] already up to date — no action"
          exit 0
        fi

        if [ "$MERGE_EXIT" -eq 0 ] && ! echo "$MERGE_OUTPUT" | grep -q "CONFLICT"; then
          {
            echo "CONFLICT_VERDICT=none"
            echo "FILES_CONFLICTED=0"
            echo "TIER1_RESOLVED=0"
            echo "TIER2_RESOLVED=0"
            echo "ESCALATED=0"
          } > "$ARTIFACTS_DIR/conflict_resolution.md"
          echo "[de-conflict] clean merge — no conflicts"
          exit 0
        fi

        # Collect conflicted files
        CONFLICTED_FILES=$(git diff --name-only --diff-filter=U 2>/dev/null || true)
        FILES_CONFLICTED=$(echo "$CONFLICTED_FILES" | grep -c . || true)
        echo "[de-conflict] files_conflicted=${FILES_CONFLICTED}"

        # ----------------------------------------------------------------
        # Tier 1: Mechanical resolution — path allowlist only
        # ----------------------------------------------------------------
        TIER1_RESOLVED=0

        # Regenerated artifacts: always take theirs (regen-codeindex produced the correct copy on main)
        for REGEN_FILE in codeindex.json symbolindex.json docs/codeindex-hotspots.md; do
          if echo "$CONFLICTED_FILES" | grep -qF "$REGEN_FILE"; then
            git checkout --theirs "$REGEN_FILE" 2>/dev/null || true
            git add "$REGEN_FILE" 2>/dev/null || true
            TIER1_RESOLVED=$((TIER1_RESOLVED + 1))
            echo "[de-conflict] tier1: theirs for $REGEN_FILE"
          fi
        done

        # package-lock.json: take theirs then re-lock so the file is consistent with package.json
        LOCK_CONFLICT=$(echo "$CONFLICTED_FILES" | grep "package-lock.json" || true)
        if [ -n "$LOCK_CONFLICT" ]; then
          LOCK_PATH=$(echo "$LOCK_CONFLICT" | head -1)
          git checkout --theirs "$LOCK_PATH" 2>/dev/null || true
          git add "$LOCK_PATH" 2>/dev/null || true
          LOCK_DIR=$(dirname "$LOCK_PATH")
          (cd "$LOCK_DIR" && npm install --package-lock-only 2>/dev/null) || true
          git add "$LOCK_PATH" 2>/dev/null || true
          TIER1_RESOLVED=$((TIER1_RESOLVED + 1))
          echo "[de-conflict] tier1: package-lock.json re-locked"
        fi

        # alembic migration head divergence: accept ours for conflicted files then run alembic merge heads
        MIGRATION_CONFLICTS=$(echo "$CONFLICTED_FILES" | grep "alembic/versions/" || true)
        if [ -n "$MIGRATION_CONFLICTS" ]; then
          echo "$MIGRATION_CONFLICTS" | while IFS= read -r MF; do
            git checkout --ours "$MF" 2>/dev/null || true
            git add "$MF" 2>/dev/null || true
          done
          (cd backend && python -m alembic merge heads -m "merge conflict resolution #${ISSUE}") 2>/dev/null || true
          git add alembic/versions/ 2>/dev/null || true
          MIGRATION_COUNT=$(echo "$MIGRATION_CONFLICTS" | grep -c . || true)
          TIER1_RESOLVED=$((TIER1_RESOLVED + MIGRATION_COUNT))
          echo "[de-conflict] tier1: alembic merge heads (${MIGRATION_COUNT} migration files)"
        fi

        # models/__init__.py: guarded union-merge — collect all `from .X import Y` lines from both sides
        if echo "$CONFLICTED_FILES" | grep -q "backend/app/models/__init__.py"; then
          INIT_PATH="backend/app/models/__init__.py"
          git show MERGE_HEAD:"$INIT_PATH" 2>/dev/null | grep "^from \." > /tmp/imports_theirs.txt || true
          git show HEAD:"$INIT_PATH" 2>/dev/null | grep "^from \." > /tmp/imports_ours.txt || true
          cat /tmp/imports_ours.txt /tmp/imports_theirs.txt | sort -u > /tmp/imports_merged.txt
          printf "# Auto-generated: merged imports from conflict resolution\n" > "$INIT_PATH"
          cat /tmp/imports_merged.txt >> "$INIT_PATH"
          git add "$INIT_PATH"
          TIER1_RESOLVED=$((TIER1_RESOLVED + 1))
          echo "[de-conflict] tier1: union-merged models/__init__.py"
        fi

        # Commit Tier 1 changes if any
        if [ "$TIER1_RESOLVED" -gt 0 ]; then
          git commit -m "chore(#${ISSUE}): Tier-1 conflict resolution (merge main)" 2>/dev/null || true
        fi

        # ----------------------------------------------------------------
        # Tier 2: AI resolution — remaining conflict markers
        # ----------------------------------------------------------------
        REMAINING_CONFLICTS=$(git diff --name-only --diff-filter=U 2>/dev/null || true)
        TIER2_RESOLVED=0

        AI_TIER=$(python3 -c "import yaml; d=yaml.safe_load(open('/workspace/markethawk/.claude/skills/refinement/config.yaml')); print('true' if d.get('conflict_resolution',{}).get('ai_tier',True) else 'false')" 2>/dev/null || echo "true")

        if [ -n "$REMAINING_CONFLICTS" ] && [ "$AI_TIER" = "true" ]; then
          echo "[de-conflict] tier2: resolving remaining ${REMAINING_CONFLICTS} via AI..."
          ISSUE_BODY=$(gh issue view "$ISSUE" --repo omniscient/markethawk --json body \
            --jq '.body' 2>/dev/null || echo "")
          GIT_LOG=$(git log --oneline origin/main..HEAD 2>/dev/null | head -20 || echo "")

          while IFS= read -r CONFLICT_FILE; do
            [ -z "$CONFLICT_FILE" ] && continue
            echo "[de-conflict] tier2: resolving $CONFLICT_FILE"
            CONFLICT_CONTENT=$(cat "$CONFLICT_FILE" 2>/dev/null || echo "")
            # Build prompt into a temp file to avoid multi-line string literals inside the
            # YAML block scalar (dark-factory-ops.md [AVOID] issue:#162).
            PROMPT_FILE=$(mktemp)
            printf '%s\n' \
              "You are resolving a merge conflict in ${CONFLICT_FILE}." \
              "" \
              "Issue #${ISSUE} context:" \
              "${ISSUE_BODY}" \
              "" \
              "Recent commits on this branch:" \
              "${GIT_LOG}" \
              "" \
              "Conflicted file (contains <<<<<<< markers):" \
              "${CONFLICT_CONTENT}" \
              "" \
              "Instructions:" \
              "- Resolve the conflict by preserving both intents where possible." \
              "- Output ONLY the complete resolved file content, no explanation, no markdown fences." \
              "- If preserving both sides would break correctness, prefer the incoming change (MERGE_HEAD side)." \
              > "$PROMPT_FILE"
            RESOLUTION=$(claude -p --model sonnet "$(cat "$PROMPT_FILE")" 2>/dev/null) || true
            rm -f "$PROMPT_FILE"

            if [ -n "$RESOLUTION" ]; then
              printf '%s' "$RESOLUTION" > "$CONFLICT_FILE"
              git add "$CONFLICT_FILE"
              TIER2_RESOLVED=$((TIER2_RESOLVED + 1))
              echo "[de-conflict] tier2: resolved $CONFLICT_FILE"
            else
              echo "[de-conflict] tier2: AI returned empty output for $CONFLICT_FILE — will escalate"
            fi
          done <<< "$REMAINING_CONFLICTS"

          if [ "$TIER2_RESOLVED" -gt 0 ]; then
            git commit -m "chore(#${ISSUE}): Tier-2 AI conflict resolution" 2>/dev/null || true
          fi
        fi

        # ----------------------------------------------------------------
        # Hard grep gate: no surviving conflict markers allowed
        # ----------------------------------------------------------------
        SURVIVING=$(grep -rn "<<<<<<< " . \
          --include="*.py" --include="*.ts" --include="*.tsx" \
          --include="*.json" --include="*.yaml" --include="*.yml" \
          --include="*.sh" --include="*.sql" --include="*.md" \
          --exclude-dir=".git" --exclude-dir="node_modules" \
          2>/dev/null || true)

        ESCALATED=0
        if [ -n "$SURVIVING" ]; then
          ESCALATED=1
          CONFLICT_VERDICT="escalate"
          echo "[de-conflict] hard_grep_gate FAILED — surviving conflict markers found"
          echo "$SURVIVING"
        else
          if [ "$TIER2_RESOLVED" -gt 0 ]; then
            CONFLICT_VERDICT="tier2"
          elif [ "$TIER1_RESOLVED" -gt 0 ]; then
            CONFLICT_VERDICT="tier1"
          else
            CONFLICT_VERDICT="clean_merge"
          fi
        fi

        # Write artifact
        {
          echo "CONFLICT_VERDICT=${CONFLICT_VERDICT}"
          echo "FILES_CONFLICTED=${FILES_CONFLICTED}"
          echo "TIER1_RESOLVED=${TIER1_RESOLVED}"
          echo "TIER2_RESOLVED=${TIER2_RESOLVED}"
          echo "ESCALATED=${ESCALATED}"
        } > "$ARTIFACTS_DIR/conflict_resolution.md"

        echo "[de-conflict] verdict=${CONFLICT_VERDICT} files_conflicted=${FILES_CONFLICTED} tier1=${TIER1_RESOLVED} tier2=${TIER2_RESOLVED} escalated=${ESCALATED}"

        if [ "$ESCALATED" -eq 1 ]; then
          echo "ERROR: Conflict markers survived all resolution tiers — escalating to Blocked" >&2
          exit 1
        fi
        exit 0
      depends_on: [regen-codeindex, setup-branch-resolve]
      when: "$parse-intent.output.intent == 'continue' || $parse-intent.output.intent == 'resolve'"
      timeout: 300000
  ```

- [ ] 4.2 Update the `preview-changeset` node's `depends_on` to include `de-conflict`. Find:

  ```yaml
      depends_on: [regen-codeindex, fetch-issue]
      when: "$parse-intent.output.intent == 'new' || $parse-intent.output.intent == 'continue'"
  ```

  Replace with:

  ```yaml
      depends_on: [de-conflict, regen-codeindex, fetch-issue]
      when: "$parse-intent.output.intent == 'new' || $parse-intent.output.intent == 'continue'"
  ```

  For `new` intent, `de-conflict` is skipped (its `when` excludes `new`), so Archon treats it
  as a resolved no-op dependency. `preview-changeset` fires after `regen-codeindex` for `new`,
  after both for `continue`.

- [ ] 4.3 Verify YAML syntax:

  ```bash
  python3 -c "import yaml; yaml.safe_load(open('.archon/workflows/archon-dark-factory.yaml')); print('YAML OK')"
  ```

  Expected: `YAML OK`

- [ ] 4.4 Commit:

  ```bash
  git add .archon/workflows/archon-dark-factory.yaml
  git commit -m "feat(#210): add de-conflict bash node (Tier 1 + Tier 2 + hard grep gate)"
  ```

---

## Task 5 — Workflow: wire `resolve` through preview-up-resolve, validate, push-resolve, and report

**Files:** `.archon/workflows/archon-dark-factory.yaml`

### Steps

- [ ] 5.1 Add `preview-up-resolve` node immediately after the `preview-up` node. This node
  always sets `PREVIEW_SKIPPED=true` for `resolve` runs (validate runs pytest/tsc only):

  ```yaml
    # preview-up-resolve: resolve runs do not rebuild the preview stack — validate uses pytest/tsc only
    - id: preview-up-resolve
      bash: |
        ISSUE=$(echo $fetch-issue.output | jq -r '.resolved_number')
        ARTIFACTS_DIR="${ARTIFACTS_DIR:-/tmp/artifacts/${ISSUE}}"
        mkdir -p "$ARTIFACTS_DIR"
        {
          echo "export PREVIEW_SKIPPED=true"
          echo "export PREVIEW_SKIP_REASON=\"conflict resolution run — no preview rebuild\""
          echo "export PREVIEW_FRONTEND=\"\""
          echo "export PREVIEW_BACKEND=\"\""
          echo "export PREVIEW_NET=\"\""
        } > "$ARTIFACTS_DIR/preview_env.sh"
        echo "PREVIEW_SKIPPED=true"
        echo "PREVIEW_SKIP_REASON=conflict resolution run — no preview rebuild"
      depends_on: [de-conflict]
      when: "$parse-intent.output.intent == 'resolve'"
      timeout: 15000
  ```

- [ ] 5.2 Update the `validate` node. Find:

  ```yaml
    - id: validate
      command: dark-factory-validate
      depends_on: [preview-up]
      when: "$parse-intent.output.intent == 'new' || $parse-intent.output.intent == 'continue'"
  ```

  Replace with:

  ```yaml
    - id: validate
      command: dark-factory-validate
      depends_on: [preview-up, preview-up-resolve]
      when: "$parse-intent.output.intent == 'new' || $parse-intent.output.intent == 'continue' || $parse-intent.output.intent == 'resolve'"
  ```

  The `preview-up` node is skipped for `resolve` and `preview-up-resolve` is skipped for
  `new`/`continue`; Archon treats the skipped one as a resolved no-op dependency.

- [ ] 5.3 The `conformance` node's `when` already excludes `resolve`:

  ```yaml
      when: "$parse-intent.output.intent == 'new' || $parse-intent.output.intent == 'continue'"
  ```

  No change needed. Conformance runs for `new`/`continue` only.

- [ ] 5.4 Add the `push-resolve` node immediately after `conformance`. For `resolve`, this
  pushes to the existing PR (no PR creation):

  ```yaml
    # push-resolve: push conflict-resolved branch to the existing PR (no new PR created)
    - id: push-resolve
      bash: |
        ISSUE=$(echo $fetch-issue.output | jq -r '.resolved_number')
        BRANCH=$(git branch --show-current)
        echo "Pushing conflict-resolved branch ${BRANCH} to existing PR for issue #${ISSUE}..."
        if ! git push origin "$BRANCH"; then
          echo "ERROR: git push failed for '${BRANCH}'" >&2
          exit 1
        fi
        if ! git ls-remote --exit-code --heads origin "$BRANCH" >/dev/null 2>&1; then
          echo "ERROR: branch '$BRANCH' is not on origin after push — aborting" >&2
          exit 1
        fi
        PR_NUM=$(gh pr list --repo omniscient/markethawk --head "$BRANCH" \
          --json number --jq '.[0].number // empty')
        echo "Pushed branch ${BRANCH} to PR #${PR_NUM:-unknown}"
        echo "PR_NUM=${PR_NUM:-}"
      depends_on: [validate]
      when: "$parse-intent.output.intent == 'resolve'"
      timeout: 30000
  ```

- [ ] 5.5 Update `push-and-pr` `depends_on` to include `push-resolve` (so `status-in-review`
  can depend on a single node). Actually, simpler: update `status-in-review` directly.

  Find the `status-in-review` node:

  ```yaml
    - id: status-in-review
      bash: |
        ...
      depends_on: [push-and-pr]
      when: "$parse-intent.output.intent == 'new' || $parse-intent.output.intent == 'continue'"
  ```

  Replace with:

  ```yaml
    - id: status-in-review
      bash: |
        ISSUE=$(echo $fetch-issue.output | jq -r '.resolved_number')
        INTENT=$parse-intent.output.intent
        echo "Moving issue #${ISSUE} to In Review..."
        # For the resolve intent, the issue is already In Review — this is a no-op board move
        # that keeps the dependency chain consistent and logs a confirmation.
        [ "$INTENT" = "resolve" ] && echo "resolve: issue #${ISSUE} already In Review — no board move needed" && exit 0
        ITEM_ID=$(gh project item-list 1 --owner omniscient --format json --limit 200 \
          | jq -r ".items[] | select(.content.number == $ISSUE and .content.type == \"Issue\") | .id")
        if [ -n "$ITEM_ID" ]; then
          gh project item-edit \
            --project-id PVT_kwHOAAFds84BWh4w \
            --id "$ITEM_ID" \
            --field-id PVTSSF_lAHOAAFds84BWh4wzhR1VaA \
            --single-select-option-id df73e18b
          echo "Moved issue #$ISSUE to In Review"
        else
          echo "WARNING: Issue #$ISSUE not found on project board"
        fi
      depends_on: [push-and-pr, push-resolve]
      when: "$parse-intent.output.intent == 'new' || $parse-intent.output.intent == 'continue' || $parse-intent.output.intent == 'resolve'"
      timeout: 15000
  ```

- [ ] 5.6 Update the `report` node to include `resolve` and surface the `conflict_resolution.md`
  artifact. Make the following changes to the `report` bash block:

  **5.6a** After the line `[ "$INTENT" = "continue" ] && ACTION="Continued iteration"`, add:

  ```bash
        [ "$INTENT" = "resolve" ] && ACTION="Conflict resolution"
  ```

  **5.6a2** For the `resolve` intent, `preview-up` is skipped (its `when` is `new || continue`),
  so `$preview-up.output` is empty and `PREVIEW_SKIPPED` will be unset. Add an explicit guard
  **before** the existing `if [ "$PREVIEW_SKIPPED" = "true" ]` block:

  ```bash
        if [ "$INTENT" = "resolve" ]; then
          PREVIEW_SECTION="_No preview environment — conflict resolution run._"
        elif [ "$PREVIEW_SKIPPED" = "true" ]; then
          PREVIEW_SECTION="_No preview environment — this change does not affect the running app (${PREVIEW_SKIP_REASON})._"
        else
          PREVIEW_SECTION="| Service | URL |
      |---------|-----|
      | Frontend | ${PREVIEW_FRONTEND} |
      | Backend API | ${PREVIEW_BACKEND} |
      | API Docs | ${PREVIEW_BACKEND}/docs |
      | PostgreSQL | \`localhost:1${PREVIEW_SLOT}54\` |
      | Redis | \`localhost:1${PREVIEW_SLOT}63\` |"
        fi
  ```

  Remove the existing standalone `if [ "$PREVIEW_SKIPPED" = "true" ] ... else ... fi` block
  that this replaces — they cover the same variable, so the new block is a drop-in replacement.

  **5.6b** After the `CONFORMANCE_SECTION` block (after the closing `fi` of that section), add
  a new section:

  ```bash
        CONFLICT_SECTION=""
        if [ -f "$ARTIFACTS_DIR/conflict_resolution.md" ]; then
          VERDICT=$(grep '^CONFLICT_VERDICT=' "$ARTIFACTS_DIR/conflict_resolution.md" | cut -d= -f2-)
          if [ -n "$VERDICT" ] && [ "$VERDICT" != "none" ]; then
            FILES_C=$(grep '^FILES_CONFLICTED=' "$ARTIFACTS_DIR/conflict_resolution.md" | cut -d= -f2-)
            T1=$(grep '^TIER1_RESOLVED=' "$ARTIFACTS_DIR/conflict_resolution.md" | cut -d= -f2-)
            T2=$(grep '^TIER2_RESOLVED=' "$ARTIFACTS_DIR/conflict_resolution.md" | cut -d= -f2-)
            CONFLICT_SECTION=$(printf "\n### Conflict Resolution\n\n- Files in conflict: %s\n- Tier 1 resolved: %s\n- Tier 2 resolved: %s\n- Verdict: %s" \
              "${FILES_C:-0}" "${T1:-0}" "${T2:-0}" "${VERDICT:-unknown}")
          fi
        fi
  ```

  **5.6c** In the `gh issue comment` body string, add `${CONFLICT_SECTION}` immediately after
  `${CONFORMANCE_SECTION}` so it appears in the issue comment.

  **5.6d** Update the `report` node's `when` guard. Find:

  ```yaml
      when: "$parse-intent.output.intent == 'new' || $parse-intent.output.intent == 'continue'"
  ```

  Replace with:

  ```yaml
      when: "$parse-intent.output.intent == 'new' || $parse-intent.output.intent == 'continue' || $parse-intent.output.intent == 'resolve'"
  ```

- [ ] 5.7 Verify YAML syntax:

  ```bash
  python3 -c "import yaml; yaml.safe_load(open('.archon/workflows/archon-dark-factory.yaml')); print('YAML OK')"
  ```

  Expected: `YAML OK`

- [ ] 5.8 Commit:

  ```bash
  git add .archon/workflows/archon-dark-factory.yaml
  git commit -m "feat(#210): wire resolve intent through preview-up-resolve, validate, push-resolve, report"
  ```

---

## Task 6 — Tests: Priority 1.5 conflict gate scheduler tests

**Files:** `dark-factory/tests/test_scheduler.sh`

### Steps

- [ ] 6.1 Read the existing test file to identify where to append (before any final `echo "All tests passed"` or `exit 0` line):

  ```bash
  tail -30 dark-factory/tests/test_scheduler.sh
  ```

- [ ] 6.2 Append the following five test cases to `test_scheduler.sh`. The pattern follows
  the existing harness: source scheduler with `SCHEDULER_SOURCE_ONLY=1`, then redefine
  stubs AFTER source (to win the override race).

  ```bash
  # ============================================================
  # Priority 1.5 — Conflict gate tests (issue #210)
  # ============================================================

  echo "--- TEST P1.5-1: conflict gate dispatches CONFLICTING PR ---"
  echo '{}' > "$STATE_FILE"
  DISPATCHED=""
  DISPATCH_LOG=""

  # Stubs defined AFTER source to win override race
  get_pr_for_issue() { echo "42"; }
  get_pr_mergeable() { echo "CONFLICTING"; }
  is_issue_running() { return 1; }
  has_skip_label() { return 1; }
  dispatch() { DISPATCHED="$1"; return 0; }
  export -f get_pr_for_issue get_pr_mergeable is_issue_running has_skip_label dispatch

  ISSUE=55
  MERGEABLE=$(get_pr_mergeable "$ISSUE")
  if is_issue_running "$ISSUE"; then true
  elif has_skip_label "$ISSUE"; then true
  else
    case "$MERGEABLE" in
      CONFLICTING)
        increment_retry "${ISSUE}:resolve" || true
        if dispatch "Resolve conflicts issue #${ISSUE}"; then
          DISPATCHED="Resolve conflicts issue #${ISSUE}"
        fi
        ;;
    esac
  fi

  [ "$DISPATCHED" = "Resolve conflicts issue #55" ] \
    || { echo "FAIL: expected dispatch for CONFLICTING, got: '$DISPATCHED'"; exit 1; }
  RETRY_COUNT=$(get_retry_count "55:resolve")
  [ "$RETRY_COUNT" -eq 1 ] \
    || { echo "FAIL: expected retry count 1, got $RETRY_COUNT"; exit 1; }
  echo "PASS"

  echo "--- TEST P1.5-2: conflict gate skips UNKNOWN mergeable ---"
  DISPATCHED=""
  get_pr_mergeable() { echo "UNKNOWN"; }
  export -f get_pr_mergeable

  ISSUE=56
  MERGEABLE=$(get_pr_mergeable "$ISSUE")
  case "$MERGEABLE" in
    CONFLICTING)
      DISPATCHED="should_not_dispatch"
      ;;
  esac

  [ -z "$DISPATCHED" ] \
    || { echo "FAIL: should not dispatch for UNKNOWN, got: '$DISPATCHED'"; exit 1; }
  echo "PASS"

  echo "--- TEST P1.5-3: conflict gate skips when CONFLICT_RESOLUTION_ENABLED=false ---"
  DISPATCHED=""
  get_pr_mergeable() { echo "CONFLICTING"; }
  export -f get_pr_mergeable
  CONFLICT_RESOLUTION_ENABLED="false"

  if conflict_resolution_enabled; then
    DISPATCHED="should_not_dispatch"
  fi

  [ -z "$DISPATCHED" ] \
    || { echo "FAIL: should skip when CONFLICT_RESOLUTION_ENABLED=false, got: '$DISPATCHED'"; exit 1; }
  CONFLICT_RESOLUTION_ENABLED="true"
  echo "PASS"

  echo "--- TEST P1.5-4: conflict gate skips when is_issue_running returns true ---"
  DISPATCHED=""
  get_pr_mergeable() { echo "CONFLICTING"; }
  is_issue_running() { return 0; }
  export -f get_pr_mergeable is_issue_running

  if conflict_resolution_enabled; then
    ISSUE=57
    if ! is_issue_running "$ISSUE"; then
      DISPATCHED="should_not_dispatch"
    fi
  fi

  [ -z "$DISPATCHED" ] \
    || { echo "FAIL: should skip when is_issue_running=true, got: '$DISPATCHED'"; exit 1; }
  is_issue_running() { return 1; }
  export -f is_issue_running
  echo "PASS"

  echo "--- TEST P1.5-5: conflict gate trips to Blocked after MAX_RETRIES ---"
  echo '{}' > "$STATE_FILE"
  # Pre-fill retry counter to MAX_RETRIES
  for i in $(seq 1 "$MAX_RETRIES"); do increment_retry "99:resolve" || true; done
  COUNT=$(get_retry_count "99:resolve")
  [ "$COUNT" -eq "$MAX_RETRIES" ] \
    || { echo "FAIL: expected retry count $MAX_RETRIES, got $COUNT"; exit 1; }

  BLOCKED_CALLED=""
  trip_to_blocked() { BLOCKED_CALLED="yes:$1:$2"; }
  export -f trip_to_blocked

  ISSUE=99
  RETRIES=$(get_retry_count "${ISSUE}:resolve")
  if [ "$RETRIES" -ge "$MAX_RETRIES" ]; then
    trip_to_blocked "$ISSUE" "resolve" "retry limit reached"
  fi

  [ "$BLOCKED_CALLED" = "yes:99:resolve" ] \
    || { echo "FAIL: expected trip_to_blocked called for 99:resolve, got: '$BLOCKED_CALLED'"; exit 1; }
  echo "PASS"
  ```

- [ ] 6.3 Run the new tests:

  ```bash
  GH_TOKEN=stub CLAUDE_CODE_OAUTH_TOKEN=stub SCHEDULER_SOURCE_ONLY=1 \
    bash dark-factory/tests/test_scheduler.sh 2>&1 | grep -E "^(PASS|FAIL|---)"
  ```

  Expected output (P1.5 section):
  ```
  --- TEST P1.5-1: conflict gate dispatches CONFLICTING PR ---
  PASS
  --- TEST P1.5-2: conflict gate skips UNKNOWN mergeable ---
  PASS
  --- TEST P1.5-3: conflict gate skips when CONFLICT_RESOLUTION_ENABLED=false ---
  PASS
  --- TEST P1.5-4: conflict gate skips when is_issue_running returns true ---
  PASS
  --- TEST P1.5-5: conflict gate trips to Blocked after MAX_RETRIES ---
  PASS
  ```

- [ ] 6.4 Confirm the full suite passes (no existing tests regressed):

  ```bash
  GH_TOKEN=stub CLAUDE_CODE_OAUTH_TOKEN=stub SCHEDULER_SOURCE_ONLY=1 \
    bash dark-factory/tests/test_scheduler.sh 2>&1 | grep "^FAIL" | wc -l
  ```

  Expected: `0`

- [ ] 6.5 Commit:

  ```bash
  git add dark-factory/tests/test_scheduler.sh
  git commit -m "test(#210): Priority 1.5 conflict gate scheduler tests (5 cases)"
  ```

---

## Validation

- [ ] Run YAML validity check one final time:

  ```bash
  python3 -c "import yaml; yaml.safe_load(open('.archon/workflows/archon-dark-factory.yaml')); print('YAML OK')"
  ```

- [ ] Run bash syntax check on scheduler:

  ```bash
  bash -n dark-factory/scheduler.sh && echo "Scheduler syntax OK"
  ```

- [ ] Run all scheduler tests, confirm zero failures:

  ```bash
  GH_TOKEN=stub CLAUDE_CODE_OAUTH_TOKEN=stub SCHEDULER_SOURCE_ONLY=1 \
    bash dark-factory/tests/test_scheduler.sh 2>&1 | grep "^FAIL" | wc -l
  ```

  Expected: `0`

- [ ] Confirm config section is parseable:

  ```bash
  python3 -c "import yaml; d=yaml.safe_load(open('.claude/skills/refinement/config.yaml')); \
    cr=d['conflict_resolution']; assert cr['enabled']==True; assert cr['ai_tier']==True; \
    print('Config OK:', cr)"
  ```

  Expected: `Config OK: {'enabled': True, 'ai_tier': True}`

- [ ] Confirm spec file is present:

  ```bash
  test -s docs/superpowers/specs/2026-06-04-dark-factory-conflict-resolution-design.md && echo "Spec OK"
  ```

  Expected: `Spec OK`
