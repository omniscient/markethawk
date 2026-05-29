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

## Phase 1.5: RESOLVE PREVIEW_BACKEND

The `preview-up` step wrote the preview URLs to `$ARTIFACTS_DIR/preview_env.sh`.
Source that file to get the authoritative `PREVIEW_BACKEND` URL:

```bash
source "$ARTIFACTS_DIR/preview_env.sh"
echo "PREVIEW_BACKEND=$PREVIEW_BACKEND"
```

`PREVIEW_BACKEND` points to the backend container via its Docker network hostname
(e.g. `http://mh-preview-98-backend-1:8000`). This works because the dark-factory
container is kept connected to the preview network from the `preview-up` step.

Do NOT compute the URL manually or use `localhost:<port>` — the host-exposed port
is not reachable from inside the dark-factory container.

## Phase 2: VALIDATE

Run the full validation suite against the preview stack:

### Backend validation
```bash
cd backend && python -m pytest --no-cov -v
```

### Frontend validation (if frontend was modified)
```bash
cd frontend && npx tsc --noEmit
```

### Endpoint validation against preview

For each new or changed endpoint identified in the implementation, use `$PREVIEW_BACKEND`
(sourced from `$ARTIFACTS_DIR/preview_env.sh` above) as the base URL:

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
- [ ] Endpoint curl tests recorded
- [ ] All results written to `$ARTIFACTS_DIR/validation.md`

## Phase 3: FIX (if needed)

If any validation fails:
1. Fix the issue
2. Re-run the failing test
3. Commit the fix
4. Re-validate

Repeat until all validations pass.

## Phase 4: CLEANUP AND REPORT

Disconnect the dark-factory container from the preview network (the preview-up step
left it connected so we could run endpoint tests):

```bash
source "$ARTIFACTS_DIR/preview_env.sh"
docker network disconnect "$PREVIEW_NET" "$(hostname)" 2>/dev/null || true
```

Write validation results to `$ARTIFACTS_DIR/validation.md`:
- Pass/fail status for each check
- Specific error details for any failures
- Final status: PASS or FAIL
