---
description: Validate the implementation against the running preview stack
argument-hint: (no arguments - reads from workflow context)
---

# Dark Factory — Validate

**Workflow ID**: $WORKFLOW_ID

---

## Phase 0: BLAST-RADIUS HARD GATE

Read `blast_radius.enabled` from `.claude/skills/refinement/config.yaml` (default: true).

```bash
BLAST_ENABLED=$(python3 -c "
import yaml, sys
d = yaml.safe_load(open('.claude/skills/refinement/config.yaml'))
print(str(d.get('blast_radius', {}).get('enabled', True)).lower())
" 2>/dev/null || echo "true")
```

Derive the issue number from the artifacts dir:

```bash
ISSUE_NUM=$(jq -r '.resolved_number' "$ARTIFACTS_DIR/issue.json")
```

If `BLAST_ENABLED=false`, write `STATUS: SKIPPED` to `$ARTIFACTS_DIR/blast.md` and skip the rest of Phase 0:

```bash
if [ "$BLAST_ENABLED" = "false" ]; then
  printf "STATUS: SKIPPED\nGATE_TYPE: blast\nFINDINGS_COUNT: 0\nSEVERITY: none\n---\nTRIGGER: none\n" \
    > "$ARTIFACTS_DIR/blast.md"
  BLAST_ENABLED=skip
fi

if [ "$BLAST_ENABLED" != "skip" ]; then

  # 1. Get changed files and real line count
  CHANGED=$(git diff main...HEAD --name-only 2>/dev/null || echo "")
  ADDED=$(git diff main...HEAD --shortstat 2>/dev/null | grep -oE '[0-9]+ insertion' | grep -oE '[0-9]+' || echo 0)
  DELETED=$(git diff main...HEAD --shortstat 2>/dev/null | grep -oE '[0-9]+ deletion' | grep -oE '[0-9]+' || echo 0)
  LINES=$((ADDED + DELETED))

  # 2. Run the blast-radius checker — pass real line count via --lines-changed
  echo "$CHANGED" | python3 dark-factory/scripts/gate_blast_radius.py \
    --changed-files-stdin \
    --lines-changed "$LINES" \
    --hotspots docs/codeindex-hotspots.md \
    --config .claude/skills/refinement/config.yaml \
    > "$ARTIFACTS_DIR/blast.md"

  # 3. Read verdict — guard with || true so grep's exit-1-on-no-match doesn't abort under set -e
  BLAST_STATUS=$(grep '^STATUS:' "$ARTIFACTS_DIR/blast.md" | cut -d' ' -f2 || true)
  BLAST_TRIGGER=$(grep '^TRIGGER:' "$ARTIFACTS_DIR/blast.md" | cut -d' ' -f2- || true)
  BLAST_FILES=$(grep '^\s*-' "$ARTIFACTS_DIR/blast.md" | head -10 || true)

  # 4. Block on HUMAN_REQUIRED
  if [ "$BLAST_STATUS" = "HUMAN_REQUIRED" ]; then
    gh issue comment "$ISSUE_NUM" --body "$(cat <<EOF
## Blast-Radius Gate — BLOCKED

The blast-radius gate has flagged this change as requiring human review before it can auto-merge.

**Trigger:** $BLAST_TRIGGER

**Triggered files:**
$BLAST_FILES

Remove the \`needs-discussion\` label after reviewing and approving the risk, then re-run validate:
\`\`\`
docker compose --profile factory run --rm dark-factory "Validate issue #$ISSUE_NUM"
\`\`\`
---
*Posted by MarketHawk Dark Factory*
EOF
)"
    gh issue edit "$ISSUE_NUM" --add-label needs-discussion
    # Move to Blocked on the project board
    ITEM_ID=$(gh project item-list 1 --owner omniscient --format json --limit 200 \
      | jq -r ".items[] | select(.content.number == $ISSUE_NUM and .content.type == \"Issue\") | .id")
    if [ -n "$ITEM_ID" ]; then
      gh project item-edit \
        --project-id PVT_kwHOAAFds84BWh4w \
        --id "$ITEM_ID" \
        --field-id PVTSSF_lAHOAAFds84BWh4wzhR1VaA \
        --single-select-option-id 93d87b2f
    fi
    exit 1
  fi

fi
```

## Phase 1: LOAD

Read the implementation context:
- Read `$ARTIFACTS_DIR/implementation.md` for what was implemented
- Read `CLAUDE.md` for validation rules

Load conformance memory (entries tagged `source:conformance` only — implementation reasoning
is excluded automatically):

```bash
AFFECTED=$(git diff --name-only origin/main...HEAD 2>/dev/null || echo "")
REPO_ROOT=$(git rev-parse --show-toplevel)

MEMORY_CONTEXT=$(python3 "${REPO_ROOT}/dark-factory/scripts/memory_retrieve.py" \
  --phase validate \
  --files "$AFFECTED" \
  --issue "$ISSUE_NUM" \
  --memory-dir "${REPO_ROOT}/.archon/memory" 2>/dev/null || true)

mkdir -p "$ARTIFACTS_DIR"
printf '%s\n' "$MEMORY_CONTEXT" > "$ARTIFACTS_DIR/memory-context.md"
```

Include `$MEMORY_CONTEXT` as additional conformance context for this phase. If empty, proceed without memory context.

## Phase 1.5: RESOLVE PREVIEW STATE

The `preview-up` step wrote the preview URLs (and skip marker) to `$ARTIFACTS_DIR/preview_env.sh`.
Source that file to get all preview state variables:

```bash
source "$ARTIFACTS_DIR/preview_env.sh"
echo "PREVIEW_SKIPPED=$PREVIEW_SKIPPED"
echo "PREVIEW_BACKEND=$PREVIEW_BACKEND"
```

`PREVIEW_BACKEND` points to the backend container via its Docker network hostname
(e.g. `http://mh-preview-98-backend-1:8000`). This works because the dark-factory
container is kept connected to the preview network from the `preview-up` step.

Do NOT compute the URL manually or use `localhost:<port>` — the host-exposed port
is not reachable from inside the dark-factory container.

When `PREVIEW_SKIPPED=true` the preview stack was not built. In that case:
- Run pytest and tsc (they run inside the factory container and need no stack).
- **Skip** endpoint curl tests — there is no backend to hit.
- **Skip** the network disconnect cleanup — no network was connected.
- Record the skip reason in `$ARTIFACTS_DIR/validation.md`.

## Phase 2: VALIDATE

### Backend validation (always run)
```bash
cd backend && python -m pytest --no-cov -v
```

### Frontend validation (if frontend was modified — always run)
```bash
cd frontend && npx tsc -p tsconfig.app.json
```

> **Why `tsconfig.app.json` not `--noEmit`:** the root `tsconfig.json` only defines project references (`"files": []`) and checks nothing on its own. `tsconfig.app.json` applies the real compiler options including `noUnusedLocals`, `noUnusedParameters`, and `strict`, which is what `npm run build` uses. These flags catch errors that `npx tsc --noEmit` silently skips.

### Endpoint validation against preview (skip when PREVIEW_SKIPPED=true)

If `PREVIEW_SKIPPED=true`, record this in `validation.md`:
```
Endpoint tests skipped — no preview environment (<PREVIEW_SKIP_REASON>).
```
and proceed to Phase 4 without running any curl tests or network disconnect.

Otherwise, for each new or changed endpoint identified in the implementation, use
`$PREVIEW_BACKEND` (sourced from `$ARTIFACTS_DIR/preview_env.sh` above) as the base URL:

```bash
# Example — replace with actual endpoints from implementation.md
source "$ARTIFACTS_DIR/preview_env.sh"
curl -s ${PREVIEW_BACKEND}/api/health | python -m json.tool
curl -s ${PREVIEW_BACKEND}/api/v1/universe/list | python -m json.tool
```

A 200 response confirms the endpoint is reachable and returns valid JSON.
A 401 response means the endpoint is reachable but requires authentication — this is
acceptable for endpoints that are auth-gated; log it as PASS (endpoint exists and responds).
Connection refused or a non-HTTP error means the endpoint is broken.

Record all results — passes and failures.

### PHASE_2_CHECKPOINT
- [ ] pytest results recorded
- [ ] tsc results recorded (if applicable)
- [ ] Endpoint curl tests recorded (or skip reason noted if PREVIEW_SKIPPED=true)
- [ ] All results written to `$ARTIFACTS_DIR/validation.md`

## Phase 3: FIX (if needed)

If any validation fails:
1. Fix the issue
2. Re-run the failing test
3. Commit the fix
4. Re-validate

Repeat until all validations pass.

## Phase 4: CLEANUP AND REPORT

**Only when `PREVIEW_SKIPPED` is not `true`:** disconnect the dark-factory container
from the preview network (the preview-up step left it connected so we could run endpoint
tests):

```bash
source "$ARTIFACTS_DIR/preview_env.sh"
if [ "$PREVIEW_SKIPPED" != "true" ]; then
  docker network disconnect "$PREVIEW_NET" "$(hostname)" 2>/dev/null || true
fi
```

Write validation results to `$ARTIFACTS_DIR/validation.md`:
- Pass/fail status for each check
- Specific error details for any failures
- If preview was skipped: note `Endpoint tests skipped — no preview environment (<reason>).`
- Final status: PASS or FAIL
