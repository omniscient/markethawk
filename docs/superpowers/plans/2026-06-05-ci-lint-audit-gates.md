# CI Lint/Audit Gates — Implementation Plan

**Goal:** Make CI lint and audit gates enforcing. Fix the ESLint TypeScript recommended ruleset that has silently never loaded (because `@typescript-eslint` v8 changed `flat/recommended` to an array and `.rules` on an array is `undefined`). Remove `|| true` from both `pip-audit` and `npm audit` CI steps after baselining current known findings. No app code changes — this is a pure tooling/config fix.

**Architecture:** Pure tooling and CI config change. Touches `frontend/eslint.config.js`, `.github/workflows/ci.yml`, `frontend/package.json` (dependency bumps), and `backend/requirements.txt` (optional package bumps). No SQLAlchemy models, no API routes, no migrations.

**Tech Stack:** ESLint v9 flat config, `@typescript-eslint` v8, GitHub Actions CI, `pip-audit`, `npm audit`.

---

## File Structure

| File | Change |
|------|--------|
| `frontend/eslint.config.js` | Restructure: spread `tsPlugin.configs['flat/recommended']` array at top level; add custom override block |
| `.github/workflows/ci.yml` | Line 98: replace `npm run lint \|\| true` with blocking ESLint invocation; line 102: drop `\|\| true` from npm audit; line 58: drop `\|\| true` from pip-audit |
| `frontend/package.json` | Bump `axios` (`1.15.0 → 1.17.0`) and `react-router-dom` (`7.14.0 → 7.17.0`) to resolved versions |
| `frontend/package-lock.json` | Auto-updated by `npm install` |
| `backend/requirements.txt` | Bump `starlette`, `python-multipart`, `python-jose` if fixed versions are available and compatible |

---

## Task 1: Fix `eslint.config.js` — spread the TS recommended array correctly

**Files:** `frontend/eslint.config.js`

**Context:** `tsPlugin.configs['flat/recommended']` in `@typescript-eslint` v8 is an **array** of config objects (plugin registration entry, parser entry, rules entry). The current code at line 45 does `...tsPlugin.configs['flat/recommended'].rules` — `.rules` on an array object is `undefined`, so the spread silently loads zero TS rules. All 128 `any` usages pass lint as a result; `--max-warnings 0` is theater.

Memory patterns applied:
- `[AVOID]` Do not call `.rules` on `tsPlugin.configs['flat/recommended']` — in v8 the value is an array, so `.rules` is `undefined`.
- `[PATTERN]` Spread `...tsPlugin.configs['flat/recommended']` directly at the top level of the export array; add custom overrides in a separate block after the spread.
- `[PATTERN]` For CI to tolerate pre-existing `warn`-level findings while still blocking on `error`-level: keep `--max-warnings 0` in `package.json` for local dev; in CI call `npx eslint . --report-unused-disable-directives-severity error`.

**TDD Steps:**

1. **Write failing test** — confirm the bug: TS rules are not loading (no `any` findings on a file known to have `any`):
   ```bash
   cd frontend
   npx eslint src/api/scanner.ts --format=compact 2>&1 | grep "no-explicit-any" \
     || echo "CONFIRMED: no-explicit-any not loading (bug present)"
   ```
   Expected output: `CONFIRMED: no-explicit-any not loading (bug present)`

2. **Verify fail** — the test confirms zero TS rule findings, proving the spread loads nothing.

3. **Implement** — replace the entire contents of `frontend/eslint.config.js`:

   ```js
   import js from '@eslint/js'
   import globals from 'globals'
   import tsPlugin from '@typescript-eslint/eslint-plugin'
   import tsParser from '@typescript-eslint/parser'
   import reactHooks from 'eslint-plugin-react-hooks'
   import reactRefresh from 'eslint-plugin-react-refresh'

   export default [
     { ignores: ['dist/**', 'node_modules/**'] },

     // Service worker context
     {
       files: ['public/**/*.js'],
       languageOptions: {
         globals: {
           ...globals.browser,
           ...globals.serviceworker,
         },
       },
     },

     // Base JS rules
     js.configs.recommended,

     // TS recommended — flat/recommended is an array in @typescript-eslint v8; spread each entry
     ...tsPlugin.configs['flat/recommended'],

     // Custom overrides (applied after TS recommended so they win)
     {
       files: ['src/**/*.{ts,tsx}'],
       languageOptions: {
         parser: tsParser,
         parserOptions: { ecmaVersion: 'latest', sourceType: 'module' },
         globals: { ...globals.browser },
       },
       plugins: {
         '@typescript-eslint': tsPlugin,
         'react-hooks': reactHooks,
         'react-refresh': reactRefresh,
       },
       rules: {
         // Pre-existing any debt — tracked in follow-on cleanup issue; warn only for now
         '@typescript-eslint/no-explicit-any': 'warn',

         // React hooks
         ...reactHooks.configs['recommended-latest'].rules,
         'react-refresh/only-export-components': ['warn', { allowConstantExport: true }],

         // TypeScript handles unused-vars better than the base rule
         'no-unused-vars': 'off',
         '@typescript-eslint/no-unused-vars': ['error', { argsIgnorePattern: '^_', varsIgnorePattern: '^_' }],
       },
     },

     // Regression guard: ban raw /api/ strings outside the api/ layer.
     // All WS and HTTP URLs must go through wsUrl() or apiClient so a single
     // env-var change propagates everywhere.
     {
       files: ['src/**/*.{ts,tsx}'],
       ignores: ['src/api/**'],
       rules: {
         'no-restricted-syntax': [
           'error',
           {
             selector: "Literal[value=/^\\/api\\//]",
             message:
               "Raw /api/ string detected outside src/api/**. Use wsUrl() or apiClient instead.",
           },
           {
             selector: "TemplateLiteral > TemplateElement[value.raw=/^\\/api\\//]",
             message:
               "Raw /api/ in template literal outside src/api/**. Use wsUrl() or apiClient instead.",
           },
         ],
       },
     },
   ]
   ```

4. **Verify pass** — three checks:

   ```bash
   cd frontend

   # TS rules now load — should see @typescript-eslint/no-explicit-any warnings
   npx eslint src/api/scanner.ts --format=compact 2>&1 | grep "no-explicit-any" | head -3
   # Expected: 1+ warning lines like "src/api/scanner.ts: line N, col M, Warning - Unexpected any..."

   # CI invocation: exit 0 (warnings tolerated, no error-level violations)
   npx eslint . --report-unused-disable-directives-severity error; echo "CI lint exit: $?"
   # Expected: CI lint exit: 0

   # Local strict mode: exits 1 (--max-warnings 0 with ~128 warnings — expected, correct for local dev)
   npm run lint; echo "local lint exit: $?"
   # Expected: local lint exit: 1

   # TypeScript types still clean
   npx tsc --noEmit; echo "tsc exit: $?"
   # Expected: tsc exit: 0
   ```

5. **Commit:**
   ```bash
   git add frontend/eslint.config.js
   git commit -m "$(cat <<'EOF'
   fix(eslint): spread flat/recommended array in @typescript-eslint v8

   tsPlugin.configs['flat/recommended'] is an array of config objects in v8;
   calling .rules on it returns undefined and silently loads no TS rules.
   Spread the array directly at the top level and add a custom override block
   after it. Downgrade no-explicit-any to warn for pre-existing debt (128 sites,
   tracked in follow-on issue).

   Part of #197.
   EOF
   )"
   ```

---

## Task 2: Fix CI lint step — replace `npm run lint || true` with blocking invocation

**Files:** `.github/workflows/ci.yml`

**Context:** Line 98 is `run: npm run lint || true`. Two problems: (a) `npm run lint` invokes `eslint . --max-warnings 0`, which now fails on 128 `any` warnings after the Task 1 fix; (b) `|| true` swallows the result regardless. The fix calls ESLint directly without `--max-warnings 0`, so CI tolerates warnings but blocks on errors. `package.json` lint script stays unchanged (strict for local dev/pre-commit).

**TDD Steps:**

1. **Write failing test** — confirm non-blocking lint in CI:
   ```bash
   grep -n "run: npm run lint" .github/workflows/ci.yml
   # Expected: 98:        run: npm run lint || true
   ```

2. **Verify fail** — `|| true` is present; lint is non-blocking regardless of result.

3. **Implement** — edit `.github/workflows/ci.yml`, replace the Lint step:

   **Before (lines 96–98):**
   ```yaml
       - name: Lint
         working-directory: frontend
         run: npm run lint || true
   ```

   **After:**
   ```yaml
       - name: Lint
         working-directory: frontend
         run: npx eslint . --report-unused-disable-directives-severity error
   ```

4. **Verify pass:**
   ```bash
   grep -A 2 "name: Lint" .github/workflows/ci.yml
   # Expected:
   #     - name: Lint
   #       working-directory: frontend
   #       run: npx eslint . --report-unused-disable-directives-severity error

   # Confirm no remaining || true on the lint step
   grep -n "npm run lint" .github/workflows/ci.yml
   # Expected: (no output — line is gone)
   ```

5. **Commit:**
   ```bash
   git add .github/workflows/ci.yml
   git commit -m "$(cat <<'EOF'
   ci: replace non-blocking npm run lint with direct ESLint invocation

   Drop || true and invoke ESLint directly without --max-warnings 0 so CI
   blocks on error-level rules while tolerating the ~128 pre-existing any
   warnings. package.json lint script (--max-warnings 0) stays strict for
   local dev and pre-commit hooks.

   Part of #197.
   EOF
   )"
   ```

---

## Task 3: Fix CI npm audit — bump affected packages, drop `|| true`

**Files:** `frontend/package.json`, `frontend/package-lock.json`, `.github/workflows/ci.yml`

**Context:** Line 102 is `run: npm audit --audit-level=high || true`. Current high-severity packages with available fixes (confirmed via `npm audit --audit-level=high --json`):
- `axios`: installed 1.15.0 → fixed at 1.17.0 (within `^1.6.0` range in `package.json`)
- `react-router` / `react-router-dom`: installed 7.14.0 → fixed at 7.17.0 (within `^7.14.0` range)

Both bumps are within the existing semver constraints — no allowlist file needed.

**TDD Steps:**

1. **Write failing test** — confirm vulnerable versions and audit failure:
   ```bash
   cd frontend
   npm ls axios react-router-dom 2>/dev/null | grep -E "axios@|react-router-dom@"
   # Expected: axios@1.15.0, react-router-dom@7.14.0

   npm audit --audit-level=high 2>&1 | grep -c "high\|critical"
   # Expected: integer > 0 (findings present)
   ```

2. **Verify fail** — high-severity findings are present before bumps.

3. **Implement** — bump packages:
   ```bash
   cd frontend
   npm install axios@1.17.0 react-router-dom@7.17.0

   # Verify installed versions
   npm ls axios react-router-dom 2>/dev/null | grep -E "axios@|react-router-dom@"
   # Expected: axios@1.17.0, react-router-dom@7.17.0
   ```

   Edit `.github/workflows/ci.yml` — replace lines 100–102:

   **Before:**
   ```yaml
       - name: Dependency audit
         working-directory: frontend
         run: npm audit --audit-level=high || true
   ```

   **After:**
   ```yaml
       - name: Dependency audit
         working-directory: frontend
         run: npm audit --audit-level=high
   ```

4. **Verify pass:**
   ```bash
   cd frontend

   # npm audit exits 0 after bumps (no high-severity findings)
   npm audit --audit-level=high; echo "npm audit exit: $?"
   # Expected: npm audit exit: 0

   # TypeScript still compiles
   npx tsc --noEmit; echo "tsc exit: $?"
   # Expected: tsc exit: 0

   # CI file has no || true on the npm audit line
   grep "npm audit" ../.github/workflows/ci.yml
   # Expected: run: npm audit --audit-level=high  (no || true)
   ```

5. **Commit:**
   ```bash
   git add frontend/package.json frontend/package-lock.json .github/workflows/ci.yml
   git commit -m "$(cat <<'EOF'
   fix(deps): bump axios and react-router-dom to clear high-severity advisories

   axios 1.15.0→1.17.0 and react-router-dom 7.14.0→7.17.0 resolve all
   high-severity npm audit findings within existing semver constraints.
   Drop || true from CI audit step so future high-severity findings block
   the build.

   Part of #197.
   EOF
   )"
   ```

---

## Task 4: Fix CI pip-audit — enumerate findings, bump or allowlist, drop `|| true`

**Files:** `.github/workflows/ci.yml`, `backend/requirements.txt`

**Context:** Line 58 is `pip-audit -r backend/requirements.txt --ignore-vuln PYSEC-2022-42969 || true`. Current packages with known vulnerabilities: `starlette==1.0.0`, `python-multipart==0.0.26`, `python-jose[cryptography]==3.3.0`. `pip-audit` has no `--audit-level` flag — it fails on any non-ignored finding. The implementer must enumerate the current finding IDs, bump packages to fixed versions where available, and add remaining IDs to `--ignore-vuln` with dated comments before dropping `|| true`.

**TDD Steps:**

1. **Write failing test** — enumerate current findings inside Docker:
   ```bash
   docker-compose exec backend bash -c \
     "pip install pip-audit -q && pip-audit -r /app/requirements.txt 2>&1"
   # Note all PYSEC-XXXX-XXXXX IDs reported — you will need them in step 3.
   # Also note: the command exits non-zero, confirming || true is the only thing
   # keeping CI green.
   ```

   Confirm `|| true` is present in CI:
   ```bash
   grep -n "pip-audit" .github/workflows/ci.yml
   # Expected: 58:          pip-audit -r backend/requirements.txt --ignore-vuln PYSEC-2022-42969 || true
   ```

2. **Verify fail** — pip-audit exits non-zero without `|| true`; CI suppresses this today.

3. **Implement** — for each vulnerable package, attempt a compatible bump:

   **Check available versions inside Docker:**
   ```bash
   docker-compose exec backend bash -c "pip index versions starlette 2>/dev/null | head -1"
   # Bump target: starlette >= 1.0.1 (if available; otherwise allowlist its IDs)

   docker-compose exec backend bash -c "pip index versions python-multipart 2>/dev/null | head -1"
   # Bump target: python-multipart >= 0.0.27

   docker-compose exec backend bash -c "pip index versions 'python-jose[cryptography]' 2>/dev/null | head -1"
   # Bump target: python-jose >= 3.4.0 (if available)
   ```

   **Update `backend/requirements.txt`** for each package with a safe fixed version — replace the pinned versions:
   ```
   # Before:
   starlette==1.0.0
   python-multipart==0.0.26
   python-jose[cryptography]==3.3.0

   # After (substitute the actual latest fixed versions found above):
   starlette==<fixed-version>
   python-multipart==<fixed-version>
   python-jose[cryptography]==<fixed-version>
   ```

   **Verify no conflicts after bumps:**
   ```bash
   docker-compose exec backend bash -c "pip install -r /app/requirements.txt --dry-run 2>&1 | tail -10"
   # Expected: no "ERROR: Cannot install" lines
   ```

   **For any package that has no safe fixed version**, add its PYSEC ID(s) (from step 1 output) to the pip-audit invocation in `.github/workflows/ci.yml`:

   ```yaml
       - name: Dependency audit
         run: |
           pip install pip-audit
           pip-audit -r backend/requirements.txt \
             --ignore-vuln PYSEC-2022-42969 \
             --ignore-vuln <PYSEC-ID-for-unfixed-package>   # <package>: <vuln desc> — 2026-06-05, tracked in #<NNN>
   ```

   If all three packages can be bumped to clean versions, the CI step simplifies to:
   ```yaml
       - name: Dependency audit
         run: |
           pip install pip-audit
           pip-audit -r backend/requirements.txt --ignore-vuln PYSEC-2022-42969
   ```

4. **Verify pass:**
   ```bash
   # pip-audit exits 0 (all findings resolved or ignore-listed)
   docker-compose exec backend bash -c \
     "pip install pip-audit -q && pip-audit -r /app/requirements.txt \
      --ignore-vuln PYSEC-2022-42969 \
      [+ any additional --ignore-vuln flags you added]"
   echo "pip-audit exit: $?"
   # Expected: pip-audit exit: 0

   # Backend still starts after any version bumps (per CLAUDE.md: confirm reload before committing)
   docker-compose restart backend
   docker-compose logs backend --tail=10
   # Expected: no ImportError or version-conflict tracebacks; "Application startup complete."

   grep "pip-audit" .github/workflows/ci.yml
   # Expected: no || true on that line
   ```

5. **Commit:**
   ```bash
   git add .github/workflows/ci.yml backend/requirements.txt
   git commit -m "$(cat <<'EOF'
   fix(deps): drop || true from pip-audit; bump or allowlist current findings

   Bump starlette/python-multipart/python-jose to patched versions where
   available. Add remaining unfixed PYSEC IDs to --ignore-vuln with dated
   comments. Drops || true so future pip-audit findings block CI.

   Part of #197.
   EOF
   )"
   ```

---

## Task 5: Open follow-on issue — eliminate `any` usages and restore strict CI lint

**Files:** (GitHub issue only — no file changes)

**Context:** ~128 `any` usages across the codebase are now tracked as `warn`-level ESLint findings. They pass CI because the CI lint step does not use `--max-warnings 0`. The follow-on cleans up the debt and re-enables the strict gate.

**Steps:**

1. **Open the follow-on issue:**
   ```bash
   FOLLOW_ON=$(gh issue create \
     --repo omniscient/markethawk \
     --title "Eliminate ~128 any usages and re-enable no-explicit-any: error in CI" \
     --label "frontend" \
     --label "size: M" \
     --label "priority: should-have" \
     --body "$(cat <<'BODY'
   ## Background

   PR for #197 fixed the ESLint config to correctly load the @typescript-eslint v8 recommended
   ruleset and downgraded \`no-explicit-any\` to \`warn\` to avoid breaking CI on ~128 pre-existing
   usages. CI lint now invokes \`npx eslint . --report-unused-disable-directives-severity error\`
   which tolerates warnings.

   ## Goal

   1. Eliminate all remaining \`any\` usages in \`frontend/src/\` — replace with proper types or
      \`unknown\` with narrowing. Prefer deriving types from API response schemas in \`frontend/src/api/*.ts\`.
   2. Promote \`@typescript-eslint/no-explicit-any\` back to \`error\` in \`frontend/eslint.config.js\`.
   3. Restore CI lint step to \`npm run lint\` (includes \`--max-warnings 0\`) for a fully strict gate.

   ## Acceptance Criteria

   - [ ] \`npm run lint\` exits 0 (no \`any\` violations, no warnings)
   - [ ] CI lint step uses \`npm run lint\` (or equivalent with \`--max-warnings 0\`)
   - [ ] \`npx tsc --noEmit\` exits 0

   ## References

   Follows up on #197.
   BODY
   )")
   echo "Follow-on issue: $FOLLOW_ON"
   ```

2. **Cross-reference on issue #197:**
   ```bash
   # Replace NNN with the number printed by the command above
   FOLLOW_ON_NUM=$(echo "$FOLLOW_ON" | grep -oE '[0-9]+$')
   gh issue comment 197 --repo omniscient/markethawk \
     --body "Follow-on issue opened: #${FOLLOW_ON_NUM} — Eliminate ~128 \`any\` usages and re-enable strict CI lint."
   ```

---

## Final Verification Checklist

Run before pushing (covers all 6 spec requirements):

```bash
cd frontend

# Req 1: TS recommended ruleset loads (any flagged as warning)
npx eslint src/api/scanner.ts --format=compact 2>&1 | grep "no-explicit-any" | head -3
# Expected: 1+ warning lines

# Req 2+3: local lint strict / CI lint permissive
npm run lint; echo "local lint exit: $?"
# Expected: 1 (128 any warnings trigger --max-warnings 0 — correct for local dev)
npx eslint . --report-unused-disable-directives-severity error; echo "CI lint exit: $?"
# Expected: 0

# Req 4: no || true on the lint step
grep "npm run lint" ../.github/workflows/ci.yml
# Expected: (no output)

# Req 5: npm audit clean at high severity
npm audit --audit-level=high; echo "npm audit exit: $?"
# Expected: 0

# TypeScript types clean (required by CLAUDE.md before committing frontend changes)
npx tsc --noEmit; echo "tsc exit: $?"
# Expected: 0
```

```bash
# Req 6: pip-audit clean (inside Docker)
docker-compose exec backend bash -c \
  "pip install pip-audit -q && pip-audit -r /app/requirements.txt \
   --ignore-vuln PYSEC-2022-42969 [+ any additional --ignore-vuln IDs]"
echo "pip-audit exit: $?"
# Expected: 0

# Backend reloaded cleanly (required by CLAUDE.md before committing backend changes)
docker-compose logs backend --tail=10
# Expected: "Application startup complete."
```
