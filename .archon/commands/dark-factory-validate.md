---
description: Validate the implementation against the running preview stack
argument-hint: (no arguments - reads from workflow context)
---

# Dark Factory — Validate

**Workflow ID**: $WORKFLOW_ID

---

## Phase 1: LOAD

Read the implementation context:
- Read `$ARTIFACTS_DIR/implementation.md` for what was implemented
- Read `CLAUDE.md` for validation rules

## Phase 2: VALIDATE

Run the full validation suite against the preview stack:

### Backend validation
```bash
cd backend && python -m pytest -v
```

### Frontend validation (if frontend was modified)
```bash
cd frontend && npx tsc --noEmit
```

### Endpoint validation against preview
For each new or changed endpoint identified in the implementation:
```bash
curl -sf http://localhost:${PREVIEW_PORT}/api/<endpoint> | python -m json.tool
```

Record all results — passes and failures.

### PHASE_2_CHECKPOINT
- [ ] pytest results recorded
- [ ] tsc results recorded (if applicable)
- [ ] Endpoint curl tests recorded
- [ ] All results written to `$ARTIFACTS_DIR/validation.md`

## Phase 3: FIX (if needed)

If any validation fails:
1. Fix the issue
2. Re-run the failing test
3. Commit the fix
4. Re-validate

Repeat until all validations pass.

## Phase 4: REPORT

Write validation results to `$ARTIFACTS_DIR/validation.md`:
- Pass/fail status for each check
- Specific error details for any failures
- Final status: PASS or FAIL
