# CI Extension: Frontend Checks, Migration Validation, Dependency Audit

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the existing CI pipeline to catch TypeScript errors, broken builds, and security vulnerabilities before merge. Adds a parallel `frontend` job (tsc, build, lint advisory, npm audit) and extends the `test` job with `pip-audit` and `alembic check`. Both jobs become required PR status checks.

**Architecture:** Two parallel GitHub Actions jobs on PR to `main`. The existing `test` job gains two steps after pytest. A new `frontend` job runs independently on the same trigger. Branch protection requires both jobs to pass before merge.

**Tech Stack:** GitHub Actions (YAML), TypeScript (`npx tsc --noEmit`), Vite (`npm run build`), ESLint, npm audit, pip-audit, Alembic

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `frontend/src/api/scanner.ts` | Modify | Add `StopSyncResponse` interface; type `stopSync` return |
| `frontend/src/pages/Settings.tsx` | Modify | Remove unnecessary `@ts-ignore` at line 96 |
| `.github/workflows/ci.yml` | Modify | Add `pip-audit` + `alembic check` to `test` job; add new `frontend` job |

---

### Task 1: Fix @ts-ignore in Settings.tsx

**Files:**
- Modify: `frontend/src/api/scanner.ts` (line 434)
- Modify: `frontend/src/pages/Settings.tsx` (line 96)

The `@ts-ignore` at `Settings.tsx:96` is a code quality cleanup. Because `tsconfig.json` has `strict: false`, TypeScript does not error on `res.message` even without the suppression comment (`res` is typed `any`). The fix correctly removes dead suppression and adds an explicit response interface, but it does not change the tsc exit code — both before and after the fix, `npx tsc --noEmit` exits 0.

- [ ] **Step 1: Verify the current type-check baseline**

```bash
cd frontend && npx tsc --noEmit && echo "tsc: OK (exits 0 before fix)"
```

Expected: `tsc: OK (exits 0 before fix)` — this is the baseline. The fix does not change the exit code; it improves type safety.

- [ ] **Step 2: Add `StopSyncResponse` interface to the type definitions block in `scanner.ts`**

The type definitions block is at the top of `frontend/src/api/scanner.ts` (line 3: `// ---- Types ---`). Add the new interface after `RefreshUniverseResponse` (lines 184–189), before `SyncAggregatesOptions`:

```typescript
// Before (lines 189–191):
}

export interface SyncAggregatesOptions {

// After:
}

export interface StopSyncResponse {
  message: string;
}

export interface SyncAggregatesOptions {
```

Then update the `stopSync` function (line 434) to use the new type — only the return type signature changes:

```typescript
// Before:
export const stopSync = async (): Promise<any> => {
  const response = await apiClient.post('/universe/sync/stop');
  return response.data;
};

// After:
export const stopSync = async (): Promise<StopSyncResponse> => {
  const response = await apiClient.post('/universe/sync/stop');
  return response.data;
};
```

- [ ] **Step 3: Remove the `@ts-ignore` from `Settings.tsx`**

In `frontend/src/pages/Settings.tsx`, replace lines 95–97:

```typescript
// Before:
      const res = await stopSync();
      // @ts-ignore
      alert(res.message);

// After:
      const res = await stopSync();
      alert(res.message);
```

- [ ] **Step 4: Verify type check passes**

```bash
cd frontend && npx tsc --noEmit
```

Expected: exits 0, no errors referencing `Settings.tsx` or `scanner.ts`.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api/scanner.ts frontend/src/pages/Settings.tsx
git commit -m "fix(frontend): type stopSync response, remove @ts-ignore in Settings.tsx"
```

---

### Task 2: Extend test job with pip-audit and alembic check

**Files:**
- Modify: `.github/workflows/ci.yml`

Adds two steps after `Upload coverage report` in the existing `test` job:
1. `pip-audit` — scans installed packages for CVEs at any severity (fails the build if any are found; `pip-audit` has no built-in severity threshold flag)
2. `python -m alembic upgrade head && python -m alembic check` — verifies no model changes lack a migration

The alembic step needs `DATABASE_URL` pointing to the same ephemeral postgres service that pytest uses.

- [ ] **Step 1: Verify current CI YAML is valid**

```bash
python3 -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml'))" && echo "YAML OK"
```

Expected: `YAML OK`

- [ ] **Step 2: Add pip-audit and alembic check steps to ci.yml**

In `.github/workflows/ci.yml`, insert the following three steps immediately after the `Upload coverage report` step (after the `path: backend/coverage.xml` line, before the end of the `test` job). The current `test` job ends at line 49 — add after that line:

The full `test` job after edit (steps listed in order):

```yaml
      - name: Install pip-audit
        run: pip install pip-audit

      - name: Python dependency audit
        run: pip-audit

      - name: Check migration sync
        working-directory: backend
        env:
          DATABASE_URL: postgresql://test:test@localhost:5432/markethawk_test
        run: python -m alembic upgrade head && python -m alembic check
```

These three steps append after the existing `Upload coverage report` step. The `Upload coverage report` step and all prior steps remain unchanged.

- [ ] **Step 3: Verify updated YAML is valid**

```bash
python3 -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml'))" && echo "YAML OK"
```

Expected: `YAML OK`

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: add pip-audit and alembic check steps to test job"
```

---

### Task 3: Add parallel frontend CI job

**Files:**
- Modify: `.github/workflows/ci.yml`

Appends a new `frontend` job to the workflow. It runs in parallel with `test` (no `needs:` dependency). Steps: checkout → setup-node 20 with npm cache → `npm ci` → `npx tsc --noEmit` → `npm run build` → `npm run lint || true` (advisory) → `npm audit --audit-level=high`.

> **Note on tsc redundancy:** `npm run build` runs `tsc && vite build`, so TypeScript is checked twice (once explicitly, once inside build). This is intentional — the explicit step produces a clearer CI step name when types fail, and matches the spec architecture diagram.

- [ ] **Step 1: Add the frontend job to ci.yml**

In `.github/workflows/ci.yml`, after the closing of the `test` job (after the last step under `test:`), append:

```yaml

  frontend:
    runs-on: ubuntu-latest

    steps:
      - uses: actions/checkout@v4

      - name: Set up Node.js
        uses: actions/setup-node@v4
        with:
          node-version: "20"
          cache: npm
          cache-dependency-path: frontend/package-lock.json

      - name: Install dependencies
        working-directory: frontend
        run: npm ci

      - name: TypeScript type check
        working-directory: frontend
        run: npx tsc --noEmit

      - name: Production build
        working-directory: frontend
        run: npm run build

      - name: Lint (advisory)
        working-directory: frontend
        run: npm run lint || true

      - name: npm dependency audit
        working-directory: frontend
        run: npm audit --audit-level=high
```

- [ ] **Step 2: Verify the full updated YAML is valid**

```bash
python3 -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml'))" && echo "YAML OK"
```

Expected: `YAML OK`

- [ ] **Step 3: Confirm both jobs appear in the workflow**

```bash
python3 -c "
import yaml
wf = yaml.safe_load(open('.github/workflows/ci.yml'))
print('Jobs:', list(wf['jobs'].keys()))
print('Frontend steps:', [s.get('name', s.get('uses')) for s in wf['jobs']['frontend']['steps']])
"
```

Expected output:
```
Jobs: ['test', 'frontend']
Frontend steps: ['actions/checkout@v4', 'Set up Node.js', 'Install dependencies', 'TypeScript type check', 'Production build', 'Lint (advisory)', 'npm dependency audit']
```

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: add parallel frontend job (tsc, build, lint advisory, npm audit)"
```

---

### Task 4: Configure branch protection required status checks

**Files:** None (GitHub API call — no local file change)

Makes both `test` and `frontend` required status checks on the `main` branch. After this step, a PR cannot merge unless both jobs pass.

- [ ] **Step 1: Confirm gh CLI is authenticated**

```bash
gh auth status
```

Expected: `Logged in to github.com as <user>`

- [ ] **Step 2: Check whether branch protection is available on this plan**

```bash
gh api repos/omniscient/markethawk/branches/main/protection 2>&1 | head -5
```

If the response contains `"Upgrade to GitHub Pro"` or HTTP 403, branch protection is not available on the current plan for a private repository. **Skip to Step 4 and open a follow-up issue instead.**

- [ ] **Step 3: Apply branch protection with required status checks** *(skip if Step 2 returned 403)*

**Important:** The `PUT` endpoint replaces the entire protection config. Before running the command below, check whether Step 2 returned a 200 with existing rules (e.g. `required_pull_request_reviews`, `restrictions`):

- **If Step 2 returned 404 (no existing protection):** Use the payload below as-is.
- **If Step 2 returned 200 with existing rules:** Copy the values for `required_pull_request_reviews`, `restrictions`, and `enforce_admins` from Step 2's output and merge them into the payload below before running, so existing rules are preserved.

```bash
gh api repos/omniscient/markethawk/branches/main/protection \
  --method PUT \
  -H "Accept: application/vnd.github+json" \
  --input - <<'EOF'
{
  "required_status_checks": {
    "strict": false,
    "contexts": ["test", "frontend"]
  },
  "enforce_admins": false,
  "required_pull_request_reviews": null,
  "restrictions": null
}
EOF
```

Expected: JSON response with `"url": "https://api.github.com/repos/omniscient/markethawk/branches/main/protection"` and `"contexts": ["test", "frontend"]` under `required_status_checks`.

Verify with:

```bash
gh api repos/omniscient/markethawk/branches/main/protection \
  --jq '.required_status_checks.contexts'
```

Expected: `["test","frontend"]`

- [ ] **Step 4: If branch protection unavailable — open a follow-up issue**

```bash
gh issue create \
  --title "Enable required status checks for CI jobs (needs GitHub Pro or public repo)" \
  --body "Branch protection (required status checks for \`test\` and \`frontend\` jobs) requires GitHub Pro or a public repository. Once the repo is eligible, run \`gh api repos/omniscient/markethawk/branches/main/protection --method PUT\` with contexts [\"test\",\"frontend\"]. Implemented in issue #88." \
  --label "needs-triage"
```

This documents the deferred step so it is not lost.
