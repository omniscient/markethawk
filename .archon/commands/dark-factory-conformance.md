---
description: Verify that the implementation conforms to its approved spec (Gate 2 — code vs spec)
argument-hint: (no arguments - reads issue context from workflow)
---

# Dark Factory — Conformance

**Workflow ID**: $WORKFLOW_ID

---

## Phase 1: LOAD

```bash
REPO_ROOT=$(git rev-parse --show-toplevel)
source "${REPO_ROOT}/dark-factory/scripts/gate_lib.sh"
AGENT_ID="${AGENT_ID_DECONFLICT}"
```

1. Read `.claude/skills/refinement/config.yaml` and extract the `conformance` block.
2. If `conformance.enabled` is `false`:
   - Write `$ARTIFACTS_DIR/conformance.md` with content: `STATUS: SKIPPED\nREASON: conformance.enabled=false`
   - Exit cleanly (proceed to push-and-pr)
3. Read `/opt/refinement-skills/conformance-reviewer-prompt.md`
4. Read `$ARTIFACTS_DIR/implementation.md` for what was implemented (may be missing if validate wrote nothing — continue anyway)
5. Extract `MAX_CYCLES` from `conformance.max_reconcile_cycles` (default: 3)
6. Extract `BLOCK_ON_MATERIAL` from `conformance.block_on_material` (default: true)
7. Extract `SCOPE_ENFORCEMENT` from `conformance.scope_enforcement` (default: true)
8. Extract `EXCISE_OOS` from `conformance.excise_out_of_scope` (default: true)
9. Extract `BACKLOG_LABEL` from `conformance.backlog_label` (default: `scope-spillover`)
10. Determine `ISSUE_NUM` from the workflow context (look at the issue context passed by the workflow, or run `git branch --show-current | grep -oP 'issue-\K\d+'`)

## Phase 2: LOCATE SPEC

Locate the approved spec using this priority order:

### 2a. Check the "Plan Generated" issue comment

```bash
gh issue view $ISSUE_NUM --json comments \
  | jq -r '[.comments[] | select(.body | test("Refinement Pipeline — Plan Generated"))] | last | .body // ""'
```

Parse the **Spec:** or **Plan:** line from that comment to find the spec file path. The Plan comment typically links the plan file; look for any linked file under `docs/superpowers/specs/`.

```bash
# Extract the first docs/superpowers/specs/ path from the "Plan Generated" comment
PLAN_COMMENT=$(gh issue view "$ISSUE_NUM" --repo omniscient/markethawk --json comments \
  | jq -r '[.comments[] | select(.body | test("Refinement Pipeline — Plan Generated"))] | last | .body // ""')
SPEC_FILE=$(printf '%s' "$PLAN_COMMENT" \
  | grep -oP 'docs/superpowers/specs/[^\s\])"]+' | head -1)
```

### 2b. Check $ARTIFACTS_DIR/refinement-status.md

```bash
cat "$ARTIFACTS_DIR/refinement-status.md" 2>/dev/null || true
```

Look for a `SPEC_PATH:` or `PLAN_PATH:` line that points to a spec.

```bash
SPEC_FILE=$(grep '^SPEC_PATH:' "$ARTIFACTS_DIR/refinement-status.md" 2>/dev/null \
  | sed 's/^SPEC_PATH: //' | head -1)
```

### 2c. Scan docs/superpowers/specs/

```bash
ls docs/superpowers/specs/ 2>/dev/null | sort -r | head -10
```

Look for a file whose name contains keywords from the issue title. Pick the most recently created file that matches.

```bash
ISSUE_KEYWORDS=$(gh issue view "$ISSUE_NUM" --repo omniscient/markethawk --json title \
  --jq '.title' | tr '[:upper:]' '[:lower:]' | tr ' ' '-')
SPEC_MATCH=$(ls docs/superpowers/specs/ 2>/dev/null | sort -r | head -10 \
  | grep -im1 "$(echo "$ISSUE_KEYWORDS" | cut -c1-20)" || true)
[ -n "$SPEC_MATCH" ] && SPEC_FILE="docs/superpowers/specs/$SPEC_MATCH" || SPEC_FILE=""
```

### 2d. No-spec fallback

If no spec file is found after all three steps:
- Set `NO_SPEC=true`
- The review will run against the issue body (advisory-only, never blocks)
- Fetch the issue body: `gh issue view $ISSUE_NUM --json body --jq '.body'`
- Log: "No spec found — running advisory-only review against issue body"

```bash
SPEC_FILE=""
```

## Phase 3: PRE-TRIAGE AND CONFORMANCE REVIEW

### Step 3.0 — Pre-triage: strip housekeeping and formatter-only Python hunks

Before feeding the diff to the reviewer, strip noise that would pollute the out-of-scope analysis.

**3.0.1 — Get the raw diff (lock files, generated artifacts, and agent memory excluded):**

```bash
RAW_DIFF=$(git diff main...HEAD \
  -- ':!*.lock' ':!*.md' \
  ':!.archon/memory/**' \
  ':!codeindex.json' ':!symbolindex.json' \
  ':!docs/codeindex-hotspots.md' \
  ':!docs/database-schema.md' \
  2>/dev/null)
```

**3.0.2 — Strip formatter-only hunks from .py files (hunk-level, not file-level):**

For each `.py` file in the diff, the filter script fetches the base version from `main`,
applies `ruff format` + `ruff check --fix --select I` to a throwaway copy, computes the
formatter delta, and removes from the diff any hunk whose changed lines are a strict subset
of the formatter delta. Interleaved hunks (formatter noise and feature code share the same
hunk) are left intact — Layer 2 (reviewer prompt) handles the residual.

```bash
# Extract .py files touched by the branch (one per line)
PY_FILES=$(git diff main...HEAD --name-only -- '*.py' 2>/dev/null)

TRIAGED_DIFF="$RAW_DIFF"
FILTER_ANNOTATION=""

if [ -n "$PY_FILES" ]; then
  # Write inputs to temp files
  DIFF_TMP=$(mktemp /tmp/fmt_diff_XXXXXX.txt)
  FILES_TMP=$(mktemp /tmp/fmt_files_XXXXXX.txt)
  printf '%s' "$RAW_DIFF" > "$DIFF_TMP"
  printf '%s\n' $PY_FILES > "$FILES_TMP"

  # Run the hunk filter; on script error fall back to raw diff (fail-open)
  FILTER_OUT=$(python3 dark-factory/scripts/fmt_hunk_filter.py \
    "$DIFF_TMP" "$FILES_TMP" 2>/tmp/fmt_filter_err.txt) \
    && TRIAGED_DIFF="$FILTER_OUT" \
    || echo "pre-triage: fmt_hunk_filter.py failed — using raw diff ($(cat /tmp/fmt_filter_err.txt))"

  rm -f "$DIFF_TMP" "$FILES_TMP"

  # Extract the [Pre-triage] annotation line if present (first line of output)
  FILTER_ANNOTATION=$(printf '%s' "$TRIAGED_DIFF" | head -1 | grep '^\[Pre-triage\]' || true)
  if [ -n "$FILTER_ANNOTATION" ]; then
    echo "pre-triage: $FILTER_ANNOTATION"
  fi
fi
```

`$TRIAGED_DIFF` is the formatter-stripped diff (or the raw diff if no .py files or ruff is
absent). `$FILTER_ANNOTATION` is the one-line informational note (empty if no stripping).

> **Annotation ordering note:** `$FILTER_ANNOTATION` is extracted from `$TRIAGED_DIFF` at the
> `head -1 | grep '^[Pre-triage]'` line *before* the ranking step runs. After ranking,
> `$TRIAGED_DIFF` is overwritten with the ranked diff (which begins with `# [diff-rank: ...]`
> and does not contain the `[Pre-triage]` line). `$FILTER_ANNOTATION` retains its value from
> the fmt-filtered diff and is independently included in `$ARTIFACT_CONTENT` in Step 3.1.2.

```bash
# Rank and chunk the fmt-filtered diff (fail-open)
RANK_IN=$(mktemp /tmp/rank_in_XXXXXX.txt)
[ -f "$ARTIFACTS_DIR/token-opt-caps.env" ] && . "$ARTIFACTS_DIR/token-opt-caps.env" || true
printf '%s' "$TRIAGED_DIFF" > "$RANK_IN"
RANKED=$(python3 dark-factory/scripts/diff_rank.py \
  --diff "$RANK_IN" \
  --artifacts-dir "$ARTIFACTS_DIR" \
  --config ".claude/skills/refinement/config.yaml" \
  ${SPEC_FILE:+--spec-file "$SPEC_FILE"} \
  --hotspots "docs/codeindex-hotspots.md" \
  2>/tmp/diff_rank_err.txt) \
  && TRIAGED_DIFF="$RANKED" \
  || echo "diff_rank: ranking failed ($(cat /tmp/diff_rank_err.txt)) — using fmt-filtered diff"
rm -f "$RANK_IN"
```

Also check for an `out-of-scope.md` recorded by the implement agent (preserved from original Step 3.0):
```bash
OOS_LOG=""
if [ -f "$ARTIFACTS_DIR/out-of-scope.md" ]; then
  OOS_LOG=$(cat "$ARTIFACTS_DIR/out-of-scope.md")
fi
```

### Step 3.1 — Build artifact content and run review

1. Get the pre-triaged implementation diff (Step 3.0 above).
   Also read `$ARTIFACTS_DIR/implementation.md` for the implementation summary.

2. Build `$ARTIFACT_CONTENT`:
   ```
   ### Implementation Summary
   <contents of $ARTIFACTS_DIR/implementation.md, or "No implementation summary found.">

   ### Out-of-Scope Log (from implement agent)
   <contents of $ARTIFACTS_DIR/out-of-scope.md, or "None recorded.">

   ### Diff (pre-triaged, ranked by risk tier)
   $FILTER_ANNOTATION
   $TRIAGED_DIFF
   ```

3. Set `CONFORMANCE_CYCLE=0` and `CONFORMANCE_DIALOGUE=""`

4. Spawn a conformance reviewer subagent using the Agent tool:
   - `description`: "Conformance review: code vs spec"
   - `model`: `claude-opus-4-8` — **always** pin this subagent to Opus 4.8 (applies to every reconcile re-spawn in Phase 3.5 too; do not let it inherit the orchestrator's model)
   - `prompt`: Content of `/opt/refinement-skills/conformance-reviewer-prompt.md` with:
     - `$ARTIFACT_KIND` replaced with `IMPLEMENTATION`
     - `$SPEC_CONTENT` replaced with the spec file contents (or issue body if `NO_SPEC=true`)
     - `$ARTIFACT_CONTENT` replaced with the artifact content from Step 3.1

5. Append the subagent's output to `CONFORMANCE_DIALOGUE`

6. Parse the **`## Out-of-Scope Changes`** section from the reviewer output:
   - Extract each `[OOS]` bullet
   - If `SCOPE_ENFORCEMENT=true` and any `[OOS]` entries exist → go to Phase 3.6 (scope remediation) BEFORE processing the verdict
   - If `SCOPE_ENFORCEMENT=false` or no `[OOS]` entries → skip Phase 3.6

7. Parse the **Verdict** line:
   - `✅ Conforms` or `⚠️ Minor deviations` → go to Phase 4 (PASS)
   - `⛔ Material divergence`:
     - If `NO_SPEC=true` OR `BLOCK_ON_MATERIAL=false` → treat as advisory (`⚠️ Minor deviations`), go to Phase 4
     - Otherwise → go to Phase 3.5 (reconcile loop)

## Phase 3.6: SCOPE REMEDIATION (Out-of-scope changes only)

This phase runs when the reviewer found `[OOS]` entries and `SCOPE_ENFORCEMENT=true`.

### 3.6.0 — Documentation exemption (drop doc-file OOS entries first)

The factory maintains documentation as **in-scope housekeeping**: the implement agent's
Phase 4 DOCUMENT step is **required** to update the documentation map (`ARCHITECTURE.md`,
`PROJECT_STRUCTURE.md`, `ENV_VARIABLES.md`, `README.md`, `CLAUDE.md`, files under `docs/`) so it
tracks the files / endpoints / models the implementation added or changed. Those doc updates
are **never** out-of-scope and must **never** be excised or filed as backlog tickets — doing so
just churns the docs the implement agent correctly wrote (the exact failure that produced the
`scope-spillover` doc tickets this rule removes).

Before any excision (3.6.1) or ticketing (3.6.2), **drop every `[OOS]` entry whose file/area is
a documentation file** — its file/area (the text before the `—` separator) matching `.md` or
under `docs/`. Only non-doc (code / config / seed) OOS entries proceed to remediation. Log
each dropped doc entry:
`echo "scope-enforcement: doc change kept in-scope (not excised/ticketed): <entry>"`.

For each remaining (non-doc) `[OOS]` entry:

### 3.6.1 — Attempt excision (if `EXCISE_OOS=true`)

Try to revert the out-of-scope change from the branch:

```bash
# For a whole file change, restore from main:
git checkout main -- <file>
git add <file>
git commit -m "revert: excise out-of-scope change in <file> (scope enforcement)"

# For a partial hunk: apply a targeted reverse patch
# If excision cannot be applied cleanly (conflicts), fall back to Block (see below).
```

After excision:
- Re-run the in-scope tests to confirm the excision didn't break anything:
  ```bash
  cd backend && python -m pytest tests/ -x -q 2>/dev/null || true
  ```
- If tests pass → excision succeeded; continue to 3.6.2.
- If tests fail or revert won't apply cleanly → skip excision, note the failure, proceed to 3.6.2 anyway (backlog ticket is always created regardless of excision outcome).

### 3.6.2 — Create backlog ticket

Before filing tickets, deduplicate OOS entries against each other and against the
existing `scope-spillover` backlog.

**Populate `OOS_ENTRIES` array from `$CONFORMANCE_DIALOGUE`** (the accumulated reviewer output
set in Phase 3.1 step 5 and appended on each reconcile cycle):

```bash
OOS_ENTRIES=()
while IFS= read -r line; do
  stripped="${line#- }"
  [[ "$stripped" == \[OOS\]* ]] || continue
  # Documentation exemption (3.6.0): the factory maintains docs in-scope (implement Phase 4
  # DOCUMENT), so doc-map updates are never excised/ticketed. Match only the file/area
  # (before the em-dash) so a code finding that merely *mentions* a doc isn't dropped.
  area="${stripped%%—*}"
  if printf '%s' "$area" | grep -qiE '\.md([^a-z0-9]|$)|(^|[^a-z])docs/'; then
    echo "scope-enforcement: doc change kept in-scope (not excised/ticketed): $stripped"
    continue
  fi
  OOS_ENTRIES+=("$stripped")
done <<< "$CONFORMANCE_DIALOGUE"
```

Skip to 3.6.3 if `${#OOS_ENTRIES[@]} -eq 0`.

**Step A — Fetch existing open spillover issues:**

```bash
SPILLOVER_JSON=$(gh issue list \
  --repo omniscient/markethawk \
  --label "$BACKLOG_LABEL" \
  --state open \
  --json number,title,body \
  --limit 200 2>/dev/null || echo "[]")
```

**Step B — Build OOS JSON array and call `dedupe_oos.py` (fail-open):**

```bash
OOS_ENTRIES_JSON=$(python3 -c \
  "import json,sys; entries=sys.argv[1:]; print(json.dumps(entries))" \
  "${OOS_ENTRIES[@]}")

DEDUPE_OUT=$(python3 dark-factory/scripts/dedupe_oos.py \
  --oos "$OOS_ENTRIES_JSON" --spillovers "$SPILLOVER_JSON" 2>/tmp/dedupe_err.txt) \
  && ACTION_LIST="$DEDUPE_OUT" \
  || {
    echo "dedupe_oos.py failed ($(cat /tmp/dedupe_err.txt)) — falling back to create-per-finding"
    ACTION_LIST=$(echo "$OOS_ENTRIES_JSON" | python3 -c \
      "import json,sys; print(json.dumps([{'entry':e,'action':'create','key':''} for e in json.load(sys.stdin)]))")
  }
```

**Step C — Process actions (whether excision succeeded or not):**

Use process substitution so `SPILLOVER_TICKETS` mutations survive outside the loop:

```bash
SPILLOVER_TICKETS=""

while IFS='|' read -r ACTION ENTRY KEY; do
  case "$ACTION" in
    create)
      SPILLOVER_TITLE="<short title derived from ENTRY>"
      DEDUP_KEY_COMMENT="<!-- dedup-key: ${KEY} -->"
      SPILLOVER_BODY="## Scope spillover from #${ISSUE_NUM}

The dark factory noticed this pre-existing defect while implementing issue #${ISSUE_NUM} but did not fix it inline (scope enforcement).

**File/area:** <file from ENTRY>
**Defect:** <description from ENTRY>

${DEDUP_KEY_COMMENT}

---
*Automatically triaged by MarketHawk Dark Factory scope enforcement.*"

      SPILLOVER_URL=$(gh issue create \
        --repo omniscient/markethawk \
        --title "$SPILLOVER_TITLE" \
        --body "$SPILLOVER_BODY" \
        --label "needs-triage,${BACKLOG_LABEL}")
      SPILLOVER_NUM=$(basename "$SPILLOVER_URL")
      SPILLOVER_TICKETS="$SPILLOVER_TICKETS $SPILLOVER_NUM"
      echo "scope-enforcement: created new spillover #${SPILLOVER_NUM} (key: $KEY)"
      ;;
    comment:*)
      EXISTING_NUM="${ACTION#comment:}"
      gh issue comment "$EXISTING_NUM" \
        --repo omniscient/markethawk \
        --body "**Scope enforcement (re-observed):** This finding was re-surfaced while implementing issue #${ISSUE_NUM}.

**Entry:** ${ENTRY}

No new ticket created — deduped against this issue."
      echo "scope-enforcement: commented on existing spillover #${EXISTING_NUM} (key: $KEY)"
      ;;
    suppress)
      echo "scope-enforcement: suppressed non-actionable finding (key: $KEY): $ENTRY"
      ;;
  esac
done < <(echo "$ACTION_LIST" | python3 -c \
  "import json,sys; [print(r['action']+'|'+r['entry']+'|'+r.get('key','')) for r in json.load(sys.stdin)]")
```

Collect all created ticket numbers into `SPILLOVER_TICKETS` (space-separated list).

### 3.6.3 — Comment on origin issue

After all OOS entries are processed:

```bash
EXCISED_COUNT=<number of successfully excised changes>
TICKET_LIST=$(echo "$SPILLOVER_TICKETS" | tr ' ' '\n' | sed 's/^/#/' | tr '\n' ' ')
gh issue comment "$ISSUE_NUM" --body "**Scope enforcement:** excised ${EXCISED_COUNT} out-of-scope change(s) from this branch. Each unrelated defect has been filed as a linked backlog ticket: ${TICKET_LIST}

The branch is now clean. These tickets are ready for triage."
```

### 3.6.4 — Resume normal flow

After scope remediation (regardless of excision success/failure), re-run the conformance review with the updated diff (Step 3.1 again), then proceed to the verdict check (Step 3.1 step 7).

Store `SPILLOVER_TICKETS` so the `report` node can include it.

## Phase 3.5: RECONCILE LOOP (Material divergence only)

1. Increment `CONFORMANCE_CYCLE`
2. If `CONFORMANCE_CYCLE > MAX_CYCLES` → go to Phase 5 (BLOCKED)
3. Read the MATERIAL deviation descriptions from the conformance reviewer output
4. Fix the code to align with the spec:
   - Write a failing test that targets the missing/wrong behavior
   - Run the test to confirm it fails: `cd backend && python -m pytest <test_path> -x -v`
   - Implement the fix
   - Run the test to confirm it passes
   - Commit: `git add -A && git commit -m "fix: align implementation with spec (conformance cycle $CONFORMANCE_CYCLE)"`
5. Re-get the diff:
   ```bash
   git diff main...HEAD -- ':!*.lock' ':!*.md' 2>/dev/null | head -1000
   ```
6. Re-spawn the conformance reviewer subagent (same prompt format, updated diff)
7. Prepend `Cycle $CONFORMANCE_CYCLE:` header and append the new output to `CONFORMANCE_DIALOGUE` with a `---` separator
8. Parse verdict again → loop back to step 1

## Phase 4: PASS — Write attestation

Write the attestation to `$ARTIFACTS_DIR/conformance.md`:

```bash
{
  emit_verdict "conformance" "PASS" "${MATERIAL_COUNT:-0}" "none"
  printf "VERDICT: %s\nCYCLES: %s\nNO_SPEC: %s\nOOS_EXCISED: %s\nOOS_TICKETS: %s\n" \
    "${CONFORMANCE_VERDICT:-UNKNOWN}" "${CONFORMANCE_CYCLE:-0}" "${NO_SPEC:-false}" \
    "${OOS_EXCISED:-0}" "${OOS_TICKETS:-}"
  printf "\n---\n\n%s\n" "${CONFORMANCE_DIALOGUE}"
} > "$ARTIFACTS_DIR/conformance.md"
```

If `CONFORMANCE_CYCLE > 0` (MATERIAL violations were found and resolved in this run), extract
violation data from `$CONFORMANCE_DIALOGUE` and write memory entries:

```bash
# Memory write: only when MATERIAL violations were found and resolved (CONFORMANCE_CYCLE > 0)
# (route_memory_file and write_memory_entry are sourced from gate_lib.sh at Phase 1 LOAD)
if [ "${CONFORMANCE_CYCLE:-0}" -gt 0 ]; then

  # Extract (VIOLATION_FILE, VIOLATION_TEXT) pairs from $CONFORMANCE_DIALOGUE.
  # $CONFORMANCE_DIALOGUE is the free-form output of the conformance reviewer subagent.
  # Read /opt/refinement-skills/conformance-reviewer-prompt.md to understand the reviewer's
  # exact output format, then parse $CONFORMANCE_DIALOGUE to build BLOCKING_VIOLATIONS as
  # newline-separated "FILE|TEXT" pairs where:
  #   FILE — the file path of the violation (e.g. backend/app/routers/scanner.py)
  #   TEXT — a one-sentence [AVOID] lesson derived from the violation description
  # If the reviewer output does not include structured file paths, use the catch-all target
  # (codebase-patterns.md) with an empty FILE prefix.
  BLOCKING_VIOLATIONS="${BLOCKING_VIOLATIONS:-}"

  MEMORY_WRITTEN=0

  while IFS='|' read -r VIOLATION_FILE VIOLATION_TEXT; do
    [ -z "$VIOLATION_TEXT" ] && continue

    TARGET=$(route_memory_file "${VIOLATION_FILE:-}")
    PATH_PREFIX=""
    if [ -n "$VIOLATION_FILE" ]; then
      PATH_PREFIX=$(dirname "$VIOLATION_FILE")/
    fi

    write_memory_entry "$TARGET" "$PATH_PREFIX" "$VIOLATION_TEXT" conformance "${ISSUE_NUM:-unknown}"
    MEMORY_WRITTEN=$((MEMORY_WRITTEN + 1))
    echo "memory-write: wrote [AVOID] to $TARGET (path:$PATH_PREFIX)"

  done << EOF
$BLOCKING_VIOLATIONS
EOF

  if [ "$MEMORY_WRITTEN" -gt 0 ]; then
    git add .archon/memory/
    git commit -m "memory: conformance lesson from #${ISSUE_NUM:-unknown}"
    echo "memory-write: committed $MEMORY_WRITTEN new [AVOID] entr(ies)"
  else
    echo "memory-write: no novel entries — skipping commit"
  fi
fi
```

Exit `0`. The `push-and-pr` and `report` nodes will proceed normally.

## Phase 5: BLOCKED — Material divergence unresolved

This phase is only reached if reconcile failed after `MAX_CYCLES`.

1. Post a "Spec Conformance — Blocked" comment on the issue:
   ```bash
   gh issue comment $ISSUE_NUM --body "## Spec Conformance — Blocked

   The implementation has material divergences from the spec that could not be resolved in $MAX_CYCLES reconcile cycle(s).

   $CONFORMANCE_DIALOGUE

   ### Next Steps

   Review the deviations above and either:
   - Fix the implementation to match the spec, then re-run: \`docker compose --profile factory run --rm dark-factory \"Continue issue #$ISSUE_NUM\"\`
   - Update the spec to document the deviation as intentional, then re-run.
   - Add \`needs-discussion\` if the spec itself needs revisiting.

   ---
   *Posted by MarketHawk Dark Factory*"
   ```

2. Move the issue to **Blocked** on the project board:
   ```bash
   ITEM_ID=$(gh project item-list 1 --owner omniscient --format json --limit 200 \
     | jq -r ".items[] | select(.content.number == $ISSUE_NUM and .content.type == \"Issue\") | .id")
   if [ -n "$ITEM_ID" ]; then
     gh project item-edit \
       --project-id PVT_kwHOAAFds84BWh4w \
       --id "$ITEM_ID" \
       --field-id PVTSSF_lAHOAAFds84BWh4wzhR1VaA \
       --single-select-option-id 93d87b2f
   fi
   ```

3. Add `needs-discussion` label:
   ```bash
   gh issue edit $ISSUE_NUM --add-label needs-discussion
   ```

4. Write blocked status to `$ARTIFACTS_DIR/conformance.md`:
   ```bash
   {
     emit_verdict "conformance" "BLOCKED" "${MATERIAL_COUNT:-0}" "critical"
     printf "VERDICT: MATERIAL\nCYCLES: %s\n" "${CONFORMANCE_CYCLE:-0}"
     printf "\n---\n\n%s\n" "${CONFORMANCE_DIALOGUE}"
   } > "$ARTIFACTS_DIR/conformance.md"
   ```

5. Exit non-zero (`exit 1`) — this prevents `push-and-pr` and `status-in-review` from running.
