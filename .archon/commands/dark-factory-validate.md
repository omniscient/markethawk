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
