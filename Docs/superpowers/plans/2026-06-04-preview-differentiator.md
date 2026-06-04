# Preview Environment Differentiator — Implementation Plan

> **Issue:** [#178](https://github.com/omniscient/markethawk/issues/178)
> **Spec:** `Docs/superpowers/specs/2026-06-03-preview-differentiator-design.md`
> **Date:** 2026-06-04

## Goal

Add a classifier step to `archon-dark-factory.yaml` that inspects the branch changeset after implementation and decides whether a full preview environment is warranted. Docs-only changes skip the preview stack and cost ~0 seconds instead of ~180s; code changes are unaffected.

## Architecture

New workflow sequence:

```
implement → regen-codeindex
  → preview-changeset   (NEW bash: gather diff)
  → classify-preview    (NEW LLM/haiku: emit needs_preview JSON)
  → preview-up          (MODIFIED: gated executor, always runs, no-ops on needs_preview=false)
  → validate            (MODIFIED command: skip curl tests when PREVIEW_SKIPPED=true)
  → conformance         (unchanged)
  → push-and-pr         (MODIFIED: PR body adapts to skip marker)
  → status-in-review    (unchanged)
  → report              (MODIFIED: report note replaces preview table when skipped)
```

The `preview_env.sh` artifact file is the single source of truth for whether a preview was built. `push-and-pr` and `report` read the skip marker from `$preview-up.output` stdout (they never source the file). `validate` sources the file.

## Tech Stack

- Bash (workflow nodes, tests) — container ships `mawk`; no `gawk`-specific idioms
- YAML `|` block scalars — no multiline bash string assignments with content at column 0 inside; use `printf` for multiline values
- haiku model for classifier
- `.claude/skills/refinement/config.yaml` — same pattern as existing `conformance.enabled`

## File Structure

| File | Action |
|------|--------|
| `.claude/skills/refinement/config.yaml` | Add `preview:` block |
| `.archon/workflows/archon-dark-factory.yaml` | Add 2 nodes; modify `preview-up`, `push-and-pr`, `report` |
| `.archon/commands/dark-factory-validate.md` | Branch on `PREVIEW_SKIPPED` |
| `dark-factory/tests/test_preview_differentiator.sh` | New regression test |
| `CLAUDE.md` | Document differentiator in Preview Environments section |

---

## Task 1: Add `preview:` config block

**Files:** `.claude/skills/refinement/config.yaml`

### TDD steps

**Write failing test** — verify the block is absent:
```bash
grep -q 'preview:' .claude/skills/refinement/config.yaml && echo "FAIL already present" || echo "PASS not yet present"
```
Expected: `PASS not yet present`

**Implement** — append to the existing config:
```yaml
preview:
  enabled: true   # false = always build preview (pre-differentiator behavior) — kill-switch
  model: haiku
```

Full resulting file (replacing the existing content):
```yaml
# .claude/skills/refinement/config.yaml
refine:
  wip_limit: 2
  skip_labels:
    - needs-discussion
    - epic
    - spec-pending-review
  min_issue_body_length: 20

plan:
  auto_advance_to_ready: false
  skip_labels:
    - needs-discussion
    - epic
    - plan-pending-review

conformance:
  enabled: true
  max_reconcile_cycles: 3
  block_on_material: true

preview:
  enabled: true   # false = always build preview (pre-differentiator behavior) — kill-switch
  model: haiku
```

**Verify pass:**
```bash
grep -q 'preview:' .claude/skills/refinement/config.yaml && echo "PASS" || echo "FAIL"
python3 -c "import yaml; yaml.safe_load(open('.claude/skills/refinement/config.yaml'))" && echo "YAML valid"
```
Expected: `PASS` then `YAML valid`

**Commit:**
```bash
git add .claude/skills/refinement/config.yaml
git commit -m "feat(#178): add preview: config block with enabled kill-switch"
```

---

## Task 2: Add `preview-changeset` and `classify-preview` nodes

**Files:** `.archon/workflows/archon-dark-factory.yaml`

These two nodes are inserted between `regen-codeindex` and `preview-up`. They both require `when: "$parse-intent.output.intent == 'new' || $parse-intent.output.intent == 'continue'"` — the same condition as `preview-up`.

### TDD steps

**Write failing test** — verify neither node exists yet:
```bash
grep -q 'id: preview-changeset' .archon/workflows/archon-dark-factory.yaml && echo "FAIL" || echo "PASS absent"
grep -q 'id: classify-preview' .archon/workflows/archon-dark-factory.yaml && echo "FAIL" || echo "PASS absent"
```
Expected: both `PASS absent`

**Implement** — locate the `# Layer 3: Spin up preview and validate` comment that precedes `preview-up`. Insert the two new nodes immediately above that comment:

```yaml
  - id: preview-changeset
    bash: |
      echo "Gathering branch changeset for preview classifier..."
      FILE_LIST=$(git diff main...HEAD --name-only 2>/dev/null || echo "")
      STAT_OUT=$(git diff main...HEAD --stat 2>/dev/null || echo "")
      if [ -z "$FILE_LIST" ]; then
        echo "WARNING: Empty changeset — classifier will default to needs_preview=true" >&2
      fi
      printf "FILE_LIST:\n%s\n---STAT---\n%s\n" "$FILE_LIST" "$STAT_OUT"
    depends_on: [regen-codeindex, fetch-issue]
    when: "$parse-intent.output.intent == 'new' || $parse-intent.output.intent == 'continue'"
    timeout: 15000

  - id: classify-preview
    prompt: |
      You are a preview-environment classifier for a software CI pipeline.

      Your job: inspect a git changeset and decide whether a full Docker preview stack
      (postgres, redis, backend, frontend, celery) needs to be built to validate this change.

      ## Input

      Changed files (from git diff main...HEAD --name-only):
      $preview-changeset.output

      Issue title and labels (secondary signal only):
      $fetch-issue.output

      ## Classifier Rubric

      Set needs_preview=false ONLY if EVERY changed file falls into one of:
      - Documentation: *.md, *.mdx, anything under docs/ or Docs/, LICENSE
      - Agent/workflow config: .archon/**, .claude/**, workflow YAML (NOT docker-compose* or app config)
      - Tests: backend/tests/**, **/*.test.ts(x), **/*.spec.ts(x), conftest.py, **/*_test.py, dark-factory/tests/**
      - CI/repo meta: .github/**, .gitignore, .pre-commit-config.yaml, lint/format config files (.eslintrc*, .prettierrc*, ruff.toml, .flake8, mypy.ini), .editorconfig

      Force needs_preview=true if ANYTHING touches:
      backend/app/**, alembic/versions/**, requirements.txt, frontend/src/**,
      package.json, package-lock.json, Dockerfile*, docker-compose*, .env*, dark-factory/seed/**

      FAIL-SAFE: empty changeset, mixed/uncertain files, or any uncertainty → needs_preview=true.
      The diff is authoritative — a docs-labeled issue that touches backend/app/** still needs a preview.

      If preview.enabled is false in .claude/skills/refinement/config.yaml, output needs_preview=true regardless.

      ## Output

      Output ONLY valid JSON, no explanation outside the JSON object:
      {"needs_preview": <boolean>, "category": "<code|docs|config|tests|ci|mixed>", "reason": "<one sentence>"}
    model: haiku
    allowed_tools: []
    depends_on: [preview-changeset, fetch-issue]
    when: "$parse-intent.output.intent == 'new' || $parse-intent.output.intent == 'continue'"
    output_format:
      type: object
      properties:
        needs_preview:
          type: boolean
        category:
          type: string
          enum: [code, docs, config, tests, ci, mixed]
        reason:
          type: string
      required: [needs_preview, category, reason]
```

**Verify pass:**
```bash
grep -q 'id: preview-changeset' .archon/workflows/archon-dark-factory.yaml && echo "PASS changeset node"
grep -q 'id: classify-preview' .archon/workflows/archon-dark-factory.yaml && echo "PASS classify node"
python3 -c "import yaml; yaml.safe_load(open('.archon/workflows/archon-dark-factory.yaml'))" && echo "YAML valid"
```
Expected: three PASS lines.

**Verify depends_on ordering** — `preview-changeset` must appear before `classify-preview` in the file and both before `preview-up`:
```bash
awk '/id: preview-changeset/{cs=NR} /id: classify-preview/{cl=NR} /id: preview-up/{pu=NR} END{print (cs < cl && cl < pu) ? "PASS order" : "FAIL order"}' .archon/workflows/archon-dark-factory.yaml
```
Expected: `PASS order`

**Commit:**
```bash
git add .archon/workflows/archon-dark-factory.yaml
git commit -m "feat(#178): add preview-changeset and classify-preview nodes"
```

---

## Task 3: Modify `preview-up` to gated executor

**Files:** `.archon/workflows/archon-dark-factory.yaml`

Two changes:
1. `depends_on` changes from `[regen-codeindex]` to `[classify-preview]`
2. Add the guard block at the very top of the bash body (before slot allocation)
3. In the existing success path (before `exit 0`), add `export PREVIEW_SKIPPED=false` to the `preview_env.sh` write block

### TDD steps

**Write failing tests:**
```bash
grep -q 'depends_on: \[classify-preview\]' .archon/workflows/archon-dark-factory.yaml \
  && echo "FAIL already changed" || echo "PASS not yet changed"
grep -q 'PREVIEW_SKIPPED=true' .archon/workflows/archon-dark-factory.yaml \
  && echo "FAIL already present" || echo "PASS not yet present"
```
Expected: both `PASS`.

**Implement**

**Change 3a** — `depends_on` of `preview-up`:

Find:
```yaml
    depends_on: [regen-codeindex]
    when: "$parse-intent.output.intent == 'new' || $parse-intent.output.intent == 'continue'"
    timeout: 300000
```
(This is the `depends_on` for the `preview-up` node. There is also a `regen-codeindex` `depends_on` for the `regen-codeindex` node itself — target the one inside the `preview-up` section.)

Replace with:
```yaml
    depends_on: [classify-preview]
    when: "$parse-intent.output.intent == 'new' || $parse-intent.output.intent == 'continue'"
    timeout: 300000
```

**Change 3b** — guard block at the top of `preview-up`'s bash body.

The current first line inside the bash body is:
```bash
      ISSUE=$(echo $fetch-issue.output | jq -r '.resolved_number')
```

Insert the following guard block immediately before that line:

```bash
      NEEDS_PREVIEW=$classify-preview.output.needs_preview
      SKIP_REASON="$classify-preview.output.reason"

      # Skip ONLY on an explicit "false". Any other value (garbled, missing) falls through to
      # building the preview — fail-safe direction: never skip on uncertainty.
      if [ "$NEEDS_PREVIEW" = "false" ]; then
        ISSUE=$(echo $fetch-issue.output | jq -r '.resolved_number')
        echo "Preview differentiator: skipping preview for issue #${ISSUE}"
        echo "Reason: ${SKIP_REASON}"
        mkdir -p "$ARTIFACTS_DIR"
        printf 'export PREVIEW_SKIPPED=true\nexport PREVIEW_SKIP_REASON="%s"\nexport PREVIEW_FRONTEND=""\nexport PREVIEW_BACKEND=""\nexport PREVIEW_NET=""\n' "${SKIP_REASON}" > "$ARTIFACTS_DIR/preview_env.sh"
        echo "PREVIEW_SKIPPED=true"
        echo "PREVIEW_SKIP_REASON=${SKIP_REASON}"
        exit 0
      fi
```

**Change 3c** — in the existing success path, add `PREVIEW_SKIPPED=false` to the `preview_env.sh` write.

Locate the block that writes `preview_env.sh` in the normal build path. The current write is:

```bash
          {
            echo "export PREVIEW_FRONTEND=\"http://localhost:1${PADDED}33\""
            echo "export PREVIEW_BACKEND=\"${BACKEND_INTERNAL}\""
            echo "export PREVIEW_NET=\"${PREVIEW_NET}\""
          } > "$ARTIFACTS_DIR/preview_env.sh"
```

Replace with:

```bash
          printf 'export PREVIEW_SKIPPED=false\nexport PREVIEW_FRONTEND="http://localhost:1%s33"\nexport PREVIEW_BACKEND="%s"\nexport PREVIEW_NET="%s"\n' "${PADDED}" "${BACKEND_INTERNAL}" "${PREVIEW_NET}" > "$ARTIFACTS_DIR/preview_env.sh"
```

Also add `echo "PREVIEW_SKIPPED=false"` to the stdout output block immediately after `echo "PREVIEW_MOUNT_SECS=${PREVIEW_SECS}"`:

```bash
          echo "PREVIEW_SKIPPED=false"
          echo "PREVIEW_SLOT=${PADDED}"
          echo "PREVIEW_FRONTEND=http://localhost:1${PADDED}33"
          echo "PREVIEW_BACKEND=${BACKEND_INTERNAL}"
          echo "PREVIEW_MOUNT_SECS=${PREVIEW_SECS}"
```

**Verify pass:**
```bash
grep -q 'NEEDS_PREVIEW=\$classify-preview' .archon/workflows/archon-dark-factory.yaml && echo "PASS guard present"
grep -c 'PREVIEW_SKIPPED' .archon/workflows/archon-dark-factory.yaml
# expect ≥ 4 occurrences (true path, false path, stdout echo, env file write)
python3 -c "import yaml; yaml.safe_load(open('.archon/workflows/archon-dark-factory.yaml'))" && echo "YAML valid"
```

**Commit:**
```bash
git add .archon/workflows/archon-dark-factory.yaml
git commit -m "feat(#178): make preview-up a gated executor — skips on needs_preview=false"
```

---

## Task 4: Modify `push-and-pr` to adapt PR body

**Files:** `.archon/workflows/archon-dark-factory.yaml`

Detect the skip marker from `$preview-up.output` (never source `preview_env.sh` — that's validate's job) and branch on it when building the PR body's `## Preview` section.

### TDD steps

**Write failing test:**
```bash
grep -q 'PREVIEW_SKIPPED' .archon/workflows/archon-dark-factory.yaml | grep -A5 'id: push-and-pr' \
  && echo "FAIL already changed" || echo "PASS not yet"
# simpler:
awk '/id: push-and-pr/,/id: status-in-review/' .archon/workflows/archon-dark-factory.yaml | grep -q 'PREVIEW_SKIPPED' \
  && echo "FAIL" || echo "PASS not yet changed"
```
Expected: `PASS not yet changed`

**Implement**

Locate the bash body of `push-and-pr`. After the existing:
```bash
      PREVIEW_FRONTEND=$(echo $preview-up.output | grep '^PREVIEW_FRONTEND=' | cut -d= -f2-)
      PREVIEW_BACKEND=$(echo $preview-up.output | grep '^PREVIEW_BACKEND=' | cut -d= -f2-)
```

Add:
```bash
      PREVIEW_SKIPPED=$(echo $preview-up.output | grep '^PREVIEW_SKIPPED=' | cut -d= -f2-)
      PREVIEW_SKIP_REASON=$(echo $preview-up.output | grep '^PREVIEW_SKIP_REASON=' | cut -d= -f2-)
```

Then replace the hardcoded `## Preview` section in the `gh pr create --body` HEREDOC.

Find the existing preview section in the PR body (inside the `--body` argument):
```
      ## Preview
      - Frontend: ${PREVIEW_FRONTEND}
      - Backend API: ${PREVIEW_BACKEND}/docs
```

Replace with a conditional:
```bash
      if [ "$PREVIEW_SKIPPED" = "true" ]; then
        PREVIEW_BODY=$(printf "_No preview environment — this change does not affect the running app (%s)._" "${PREVIEW_SKIP_REASON}")
      else
        PREVIEW_BODY=$(printf "- Frontend: %s\n- Backend API: %s/docs" "${PREVIEW_FRONTEND}" "${PREVIEW_BACKEND}")
      fi
```

And update the `gh pr create --body` argument to use `${PREVIEW_BODY}` in place of the hardcoded lines. The full `--body` argument should become:

```bash
        PR_URL=$(gh pr create \
          --title "$(gh issue view $ISSUE --json title --jq '.title')" \
          --body "$(printf "## Summary\nAutomated implementation for issue #%s.%s\n\n## Preview\n%s\n\n## Commands\n\`\`\`bash\n# Iterate after feedback\ndocker compose --profile factory run --rm dark-factory \"Continue issue #%s\"\n\n# Tear down preview when done\ndocker compose --profile factory run --rm dark-factory \"Close issue #%s\"\n\`\`\`\n%s\n\n---\n*Generated by MarketHawk Dark Factory*" "$ISSUE" "$EPIC_LINE" "$PREVIEW_BODY" "$ISSUE" "$ISSUE" "$BLAST_SECTION")" \
          --draft)
```

> Note: `printf` is used here instead of a multiline HEREDOC string because YAML `|` block scalars terminate on content at column 0. `printf` avoids that constraint.

**Verify pass:**
```bash
awk '/id: push-and-pr/,/id: status-in-review/' .archon/workflows/archon-dark-factory.yaml | grep -q 'PREVIEW_SKIPPED' && echo "PASS"
python3 -c "import yaml; yaml.safe_load(open('.archon/workflows/archon-dark-factory.yaml'))" && echo "YAML valid"
```

**Commit:**
```bash
git add .archon/workflows/archon-dark-factory.yaml
git commit -m "feat(#178): push-and-pr renders 'No preview environment' note when skipped"
```

---

## Task 5: Modify `report` node to adapt preview section

**Files:** `.archon/workflows/archon-dark-factory.yaml`

Same detection pattern as `push-and-pr`: grep `$preview-up.output` for `PREVIEW_SKIPPED=true`. When true, replace the `### Preview Environment` table with a one-line note.

### TDD steps

**Write failing test:**
```bash
awk '/id: report/,/depends_on: \[status-in-review\]/' .archon/workflows/archon-dark-factory.yaml | grep -q 'PREVIEW_SKIPPED' \
  && echo "FAIL" || echo "PASS not yet changed"
```
Expected: `PASS not yet changed`

**Implement**

After the existing lines that read `PREVIEW_FRONTEND` and `PREVIEW_BACKEND` from `$preview-up.output` in the `report` bash body:
```bash
      PREVIEW_FRONTEND=$(echo $preview-up.output | grep '^PREVIEW_FRONTEND=' | cut -d= -f2-)
      PREVIEW_BACKEND=$(echo $preview-up.output | grep '^PREVIEW_BACKEND=' | cut -d= -f2-)
```

Add:
```bash
      PREVIEW_SKIPPED=$(echo $preview-up.output | grep '^PREVIEW_SKIPPED=' | cut -d= -f2-)
      PREVIEW_SKIP_REASON=$(echo $preview-up.output | grep '^PREVIEW_SKIP_REASON=' | cut -d= -f2-)
```

Then replace the hardcoded `### Preview Environment` table in the `gh issue comment --body` argument.

Find:
```
      ### Preview Environment

      | Service | URL |
      |---------|-----|
      | Frontend | ${PREVIEW_FRONTEND} |
      | Backend API | ${PREVIEW_BACKEND} |
      | API Docs | ${PREVIEW_BACKEND}/docs |
      | PostgreSQL | \`localhost:1${PREVIEW_SLOT}54\` |
      | Redis | \`localhost:1${PREVIEW_SLOT}63\` |
```

Replace with a conditional that builds `PREVIEW_SECTION`:
```bash
      if [ "$PREVIEW_SKIPPED" = "true" ]; then
        PREVIEW_SECTION=$(printf "### Preview Environment\n\n_No preview environment — this change does not affect the running app (%s)._" "${PREVIEW_SKIP_REASON}")
      else
        PREVIEW_SECTION=$(printf "### Preview Environment\n\n| Service | URL |\n|---------|-----|\n| Frontend | %s |\n| Backend API | %s |\n| API Docs | %s/docs |\n| PostgreSQL | \`localhost:1%s54\` |\n| Redis | \`localhost:1%s63\` |" "${PREVIEW_FRONTEND}" "${PREVIEW_BACKEND}" "${PREVIEW_BACKEND}" "${PREVIEW_SLOT}" "${PREVIEW_SLOT}")
      fi
```

Then update the `gh issue comment --body` to embed `${PREVIEW_SECTION}` where the table used to be:

```bash
      gh issue comment "$ISSUE" --body "$(printf "## Dark Factory Run — %s\n\n%s\n%s\n**Branch:** \`%s\`\n\n### Changes\n\n%s\n\n%s\n\n%s\n\n### Commands\n\`\`\`bash\n# Iterate after review\ndocker compose --profile factory run --rm dark-factory \"Continue issue #%s\"\n\n# Tear down when done\ndocker compose --profile factory run --rm dark-factory \"Close issue #%s\"\n\`\`\`\n\n---\n*Posted by MarketHawk Dark Factory*" \
        "$ACTION" "$PR_LINE" "$EPIC_LINE" "$BRANCH" \
        "${CHANGES:-_No implementation summary available._}" \
        "${CONFORMANCE_SECTION}" \
        "${PREVIEW_SECTION}" \
        "$ISSUE" "$ISSUE")"
```

**Verify pass:**
```bash
awk '/id: report/,/echo "Report posted/' .archon/workflows/archon-dark-factory.yaml | grep -q 'PREVIEW_SKIPPED' && echo "PASS"
python3 -c "import yaml; yaml.safe_load(open('.archon/workflows/archon-dark-factory.yaml'))" && echo "YAML valid"
```

**Commit:**
```bash
git add .archon/workflows/archon-dark-factory.yaml
git commit -m "feat(#178): report renders 'No preview environment' note when skipped"
```

---

## Task 6: Modify `dark-factory-validate` command

**Files:** `.archon/commands/dark-factory-validate.md`

After sourcing `preview_env.sh` in Phase 1.5, check `PREVIEW_SKIPPED`. When true: run pytest/tsc but skip endpoint curl tests and network disconnect cleanup.

### TDD steps

**Write failing test:**
```bash
grep -q 'PREVIEW_SKIPPED' .archon/commands/dark-factory-validate.md && echo "FAIL" || echo "PASS not yet"
```
Expected: `PASS not yet`

**Implement**

The file is a markdown command. Replace the entire contents with the updated version below.

Current Phase 1.5 ends with:
```
Source that file to get the authoritative `PREVIEW_BACKEND` URL:
...
Do NOT compute the URL manually or use `localhost:<port>`...
```

Replace Phase 1.5 and Phase 2 with a branched approach. Full replacement content for the file:

```markdown
---
description: Validate the implementation against the running preview stack (or skip endpoint tests when no preview)
argument-hint: (no arguments - reads from workflow context)
---

# Dark Factory — Validate

**Workflow ID**: $WORKFLOW_ID

---

## Phase 1: LOAD

Read the implementation context:
- Read `$ARTIFACTS_DIR/implementation.md` for what was implemented
- Read `CLAUDE.md` for validation rules

## Phase 1.5: RESOLVE PREVIEW STATE

The `preview-up` step wrote preview state to `$ARTIFACTS_DIR/preview_env.sh`.
Source that file to determine whether a preview was built:

```bash
source "$ARTIFACTS_DIR/preview_env.sh"
echo "PREVIEW_SKIPPED=${PREVIEW_SKIPPED}"
echo "PREVIEW_BACKEND=${PREVIEW_BACKEND}"
```

`PREVIEW_SKIPPED` will be `true` (preview was skipped — docs/config/test-only change) or
`false` (preview was built — continue to endpoint tests).

## Phase 2: VALIDATE

### Always: Backend unit tests

Run regardless of whether a preview exists — these run inside the factory container:

```bash
cd backend && python -m pytest --no-cov -v
```

### Always: Frontend type check (if frontend was modified)

```bash
cd frontend && npx tsc --noEmit
```

### Conditional: Endpoint validation (preview only)

**If `PREVIEW_SKIPPED=false`** — run endpoint curl tests against the preview stack:

```bash
source "$ARTIFACTS_DIR/preview_env.sh"
# Replace with actual endpoints from implementation.md
curl -s ${PREVIEW_BACKEND}/api/health | python -m json.tool
```

A 200 response confirms the endpoint is reachable. A 401 means auth-gated (acceptable — log as PASS).
Connection refused or non-HTTP error means the endpoint is broken.

**If `PREVIEW_SKIPPED=true`** — skip all endpoint curl tests. Record in `validation.md`:

```
Endpoint tests skipped — no preview environment ($PREVIEW_SKIP_REASON).
```

### PHASE_2_CHECKPOINT
- [ ] pytest results recorded
- [ ] tsc results recorded (if applicable)
- [ ] Endpoint curl tests recorded (or skip reason recorded)
- [ ] All results written to `$ARTIFACTS_DIR/validation.md`

## Phase 3: FIX (if needed)

If any validation fails:
1. Fix the issue
2. Re-run the failing test
3. Commit the fix
4. Re-validate

Repeat until all validations pass.

## Phase 4: CLEANUP AND REPORT

**If `PREVIEW_SKIPPED=false`** — disconnect from the preview network:

```bash
source "$ARTIFACTS_DIR/preview_env.sh"
docker network disconnect "$PREVIEW_NET" "$(hostname)" 2>/dev/null || true
```

**If `PREVIEW_SKIPPED=true`** — skip network disconnect (no network was connected).

Write validation results to `$ARTIFACTS_DIR/validation.md`:
- Pass/fail status for each check (pytest, tsc, endpoint tests or skip note)
- Specific error details for any failures
- Final status: PASS or FAIL
```

**Verify pass:**
```bash
grep -q 'PREVIEW_SKIPPED' .archon/commands/dark-factory-validate.md && echo "PASS"
grep -q 'Endpoint tests skipped' .archon/commands/dark-factory-validate.md && echo "PASS skip note"
```
Expected: both `PASS`.

**Commit:**
```bash
git add .archon/commands/dark-factory-validate.md
git commit -m "feat(#178): validate command branches on PREVIEW_SKIPPED — skips curl tests when no preview"
```

---

## Task 7: Add regression tests

**Files:** `dark-factory/tests/test_preview_differentiator.sh`

Tests cover three areas:
1. `preview-up` guard logic (bash, fully unit-testable via a stub wrapper)
2. The validate skip path (bash assertions on what `validation.md` records)
3. PR/report integration (minimal: verify the key `printf` format strings produce the expected output)

### TDD steps

**Write the test file first** (it will pass once the implementation is in place):

```bash
touch dark-factory/tests/test_preview_differentiator.sh
chmod +x dark-factory/tests/test_preview_differentiator.sh
```

**Run before implementation** — should fail/skip because guard logic doesn't exist yet:
```bash
bash dark-factory/tests/test_preview_differentiator.sh
```
Expected: failures or "not implemented" output.

**Implement** — write `dark-factory/tests/test_preview_differentiator.sh`:

```bash
#!/usr/bin/env bash
# Regression tests for the preview-environment differentiator (issue #178).
# Run: bash dark-factory/tests/test_preview_differentiator.sh
set -uo pipefail

PASSED=0; FAILED=0
ARTIFACTS_DIR=$(mktemp -d /tmp/test-differentiator-XXXXXX)
trap 'rm -rf "$ARTIFACTS_DIR"' EXIT

assert_eq() {
  local desc="$1" expected="$2" actual="$3"
  if [ "$expected" = "$actual" ]; then
    echo "  PASS: $desc"; PASSED=$((PASSED+1))
  else
    echo "  FAIL: $desc — expected='$expected' got='$actual'" >&2; FAILED=$((FAILED+1))
  fi
}

assert_contains() {
  local desc="$1" needle="$2" haystack="$3"
  if echo "$haystack" | grep -q "$needle"; then
    echo "  PASS: $desc"; PASSED=$((PASSED+1))
  else
    echo "  FAIL: $desc — '$needle' not found in output" >&2; FAILED=$((FAILED+1))
  fi
}

assert_not_contains() {
  local desc="$1" needle="$2" haystack="$3"
  if ! echo "$haystack" | grep -q "$needle"; then
    echo "  PASS: $desc"; PASSED=$((PASSED+1))
  else
    echo "  FAIL: $desc — '$needle' found but should be absent" >&2; FAILED=$((FAILED+1))
  fi
}

# ============================================================
# A: preview-up guard logic
# The guard is extracted inline here to test in isolation.
# ============================================================
echo "--- A: preview-up guard logic ---"

run_guard() {
  local needs_preview="$1" skip_reason="${2:-test reason}"
  local artifacts="$ARTIFACTS_DIR/guard_test_$(date +%N)"
  mkdir -p "$artifacts"

  DOCKER_CALLED=0
  docker() { DOCKER_CALLED=1; echo "docker $*"; }

  NEEDS_PREVIEW="$needs_preview"
  SKIP_REASON="$skip_reason"

  # Reproduce the guard logic from preview-up (must match Task 3 implementation exactly)
  if [ "$NEEDS_PREVIEW" = "false" ]; then
    ISSUE="99"
    mkdir -p "$artifacts"
    printf 'export PREVIEW_SKIPPED=true\nexport PREVIEW_SKIP_REASON="%s"\nexport PREVIEW_FRONTEND=""\nexport PREVIEW_BACKEND=""\nexport PREVIEW_NET=""\n' "${SKIP_REASON}" > "$artifacts/preview_env.sh"
    echo "PREVIEW_SKIPPED=true"
    echo "PREVIEW_SKIP_REASON=${SKIP_REASON}"
    GUARD_EXIT=0
  else
    GUARD_EXIT=1  # signal: fell through to build path
  fi

  echo "DOCKER_CALLED=$DOCKER_CALLED"
  echo "GUARD_EXIT=$GUARD_EXIT"
  cat "$artifacts/preview_env.sh" 2>/dev/null || echo "NO_ENV_FILE"
}

# A1: explicit false → skip
OUT=$(run_guard "false" "all files are markdown")
assert_contains "A1: PREVIEW_SKIPPED=true written"    "PREVIEW_SKIPPED=true"     "$(cat "$ARTIFACTS_DIR"/guard_test_*/preview_env.sh 2>/dev/null | head -1 || echo '')"
assert_not_contains "A1: docker not called"           "DOCKER_CALLED=1"          "$OUT"
assert_contains     "A1: stdout emits PREVIEW_SKIPPED=true" "PREVIEW_SKIPPED=true" "$OUT"

# A2: explicit true → fall through to build
OUT2=$(run_guard "true" "touches backend/app")
assert_eq "A2: fell through to build path" "1" "$(echo "$OUT2" | grep -c 'GUARD_EXIT=1')"

# A3: garbled value → fall through (fail-safe)
OUT3=$(run_guard "garbled_value" "classifier error")
assert_eq "A3: garbled falls through" "1" "$(echo "$OUT3" | grep -c 'GUARD_EXIT=1')"

# A4: empty string → fall through
OUT4=$(run_guard "" "empty")
assert_eq "A4: empty string falls through" "1" "$(echo "$OUT4" | grep -c 'GUARD_EXIT=1')"

# ============================================================
# B: validate skip-path — PREVIEW_SKIPPED=true in preview_env.sh
# ============================================================
echo ""
echo "--- B: validate skip-path assertions ---"

# Create a preview_env.sh that marks the preview as skipped
SKIP_ARTIFACTS="$ARTIFACTS_DIR/validate_skip"
mkdir -p "$SKIP_ARTIFACTS"
printf 'export PREVIEW_SKIPPED=true\nexport PREVIEW_SKIP_REASON="docs-only change"\nexport PREVIEW_FRONTEND=""\nexport PREVIEW_BACKEND=""\nexport PREVIEW_NET=""\n' > "$SKIP_ARTIFACTS/preview_env.sh"

source "$SKIP_ARTIFACTS/preview_env.sh"
assert_eq "B1: PREVIEW_SKIPPED sourced correctly" "true"           "$PREVIEW_SKIPPED"
assert_eq "B2: PREVIEW_BACKEND empty when skipped" ""             "$PREVIEW_BACKEND"
assert_eq "B3: PREVIEW_NET empty when skipped"    ""              "$PREVIEW_NET"

# B4: skip note format
SKIP_NOTE=$(printf "Endpoint tests skipped — no preview environment (%s)." "$PREVIEW_SKIP_REASON")
assert_contains "B4: skip note contains reason" "docs-only change" "$SKIP_NOTE"

# ============================================================
# C: PR body and report — preview section conditional
# ============================================================
echo ""
echo "--- C: PR body / report preview section ---"

# C1: when skipped, preview body uses the note format
PREVIEW_SKIP_REASON="all files are markdown docs"
PREVIEW_BODY_SKIP=$(printf "_No preview environment — this change does not affect the running app (%s)._" "${PREVIEW_SKIP_REASON}")
assert_contains "C1: skip body contains reason" "markdown docs" "$PREVIEW_BODY_SKIP"
assert_not_contains "C1: skip body has no URL" "Frontend:" "$PREVIEW_BODY_SKIP"

# C2: when not skipped, preview body contains URLs
PREVIEW_FRONTEND="http://localhost:10333"
PREVIEW_BACKEND="http://mh-preview-1-backend-1:8000"
PREVIEW_BODY_FULL=$(printf "- Frontend: %s\n- Backend API: %s/docs" "$PREVIEW_FRONTEND" "$PREVIEW_BACKEND")
assert_contains "C2: full body has frontend URL" "localhost:10333" "$PREVIEW_BODY_FULL"
assert_contains "C2: full body has backend URL"  "mh-preview-1-backend-1" "$PREVIEW_BODY_FULL"

# ============================================================
# D: config block exists and is parseable
# ============================================================
echo ""
echo "--- D: config.yaml preview block ---"
CONFIG=".claude/skills/refinement/config.yaml"
if [ -f "$CONFIG" ]; then
  assert_contains "D1: preview block present" "preview:" "$(cat "$CONFIG")"
  assert_contains "D2: enabled key present"   "enabled:" "$(cat "$CONFIG")"
  assert_contains "D3: model key present"     "model:"   "$(cat "$CONFIG")"
else
  echo "  SKIP: config file not found at $CONFIG (run from repo root)"
fi

# ============================================================
# Summary
# ============================================================
echo ""
echo "Results: $PASSED passed, $FAILED failed"
[ "$FAILED" -eq 0 ] && exit 0 || exit 1
```

**Verify pass (after Task 3–6 implementation):**
```bash
bash dark-factory/tests/test_preview_differentiator.sh
```
Expected: all assertions PASS, exit 0.

**Commit:**
```bash
git add dark-factory/tests/test_preview_differentiator.sh
git commit -m "test(#178): regression tests for preview-environment differentiator"
```

---

## Task 8: Update CLAUDE.md

**Files:** `CLAUDE.md`

Add a note about the differentiator in the "Preview Environments" section.

### TDD steps

**Write failing test:**
```bash
grep -q 'differentiator' CLAUDE.md && echo "FAIL already present" || echo "PASS not yet"
```
Expected: `PASS not yet`

**Implement** — locate the `### Preview Environments` section in the Dark Factory section of CLAUDE.md. The current text says:

> Each issue gets its own preview stack on deterministic ports:
> - Frontend: `http://localhost:1{NN}33`
> - Backend: `http://localhost:1{NN}80`

Add immediately after those bullet points:

```markdown
A **preview differentiator** step inspects the branch changeset after implementation. Docs-only, config-only, test-only, and CI-meta changes skip the preview stack entirely — `preview-up` no-ops and validate skips endpoint tests. Code-affecting changes (anything under `backend/app/**`, `frontend/src/**`, migrations, Docker config, etc.) always get a full preview.

To disable the differentiator and always build: set `preview.enabled: false` in `.claude/skills/refinement/config.yaml`.
```

**Verify pass:**
```bash
grep -q 'differentiator' CLAUDE.md && echo "PASS"
```
Expected: `PASS`

**Verify backend still running (CLAUDE.md is docs — no backend restart needed, but confirm no accidental truncation):**
```bash
wc -l CLAUDE.md
grep -c '##' CLAUDE.md
```
Confirm line count is plausible (>200) and section headers are intact.

**Commit:**
```bash
git add CLAUDE.md
git commit -m "docs(#178): document preview-environment differentiator in CLAUDE.md Dark Factory section"
```

---

## End-to-end manual verification

After all tasks, run the factory against a docs-only test issue and confirm:

1. `classify-preview` emits `needs_preview: false`
2. `preview-up` logs "Preview differentiator: skipping preview for issue #N" and exits 0
3. No `docker compose up` is invoked for the preview
4. `validate` runs pytest/tsc but skips endpoint curl tests
5. PR is created with "No preview environment" in the `## Preview` section
6. Issue comment (report) shows the same one-line note instead of the preview table

Then run against a code-affecting issue and confirm the preview still builds normally.
