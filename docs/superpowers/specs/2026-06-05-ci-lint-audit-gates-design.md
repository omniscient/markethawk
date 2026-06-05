# CI Lint/Audit Gates — Design Spec

**Date:** 2026-06-05
**Issue:** #197 — [arch-v2][MED] CI lint/audit gates are non-enforcing
**Status:** Spec generated — pending review
**Author:** MarketHawk Refinement Pipeline

---

## Overview

The ESLint TypeScript recommended ruleset has never loaded in this project because `@typescript-eslint` v8 changed `configs['flat/recommended']` from a single config object to an **array**. Spreading `array.rules` evaluates to `undefined` and silently spreads nothing. As a result, 125+ `any` usages pass lint cleanly and `--max-warnings 0` is theater. Separately, both dependency audit steps (`pip-audit`, `npm audit`) use `|| true`, meaning security findings never fail CI even if `--audit-level=high` is set.

This spec describes the minimum changes to make CI "honest": lint and audit gates must fire on real violations.

---

## Requirements

1. The TypeScript ESLint recommended ruleset (`no-explicit-any`, `ban-ts-comment`, `no-unused-vars`, etc.) must load and evaluate against all `src/**/*.{ts,tsx}` files.
2. Existing `any` usages (≈128 sites) must not immediately break CI — they are pre-existing debt tracked in a follow-on issue. `no-explicit-any` is downgraded to `warn` for now.
3. `npm run lint` in `package.json` stays strict (`--max-warnings 0`) for local dev / pre-commit; CI uses a separate invocation that tolerates warnings but blocks on errors.
4. The `npm run lint || true` CI step must be replaced with a blocking call.
5. `npm audit --audit-level=high` must block on new high-severity findings; current known findings are allow-listed with dated comments.
6. `pip-audit` must block on new findings; current known findings are added to the `--ignore-vuln` list and `|| true` is dropped.

---

## Approach

### 1. Fix `eslint.config.js` — spread the `flat/recommended` array correctly

**Problem:** `tsPlugin.configs['flat/recommended']` in `@typescript-eslint` v8 returns an **array** of config objects (plugin registration, parser, rules). The current `...tsPlugin.configs['flat/recommended'].rules` extracts `.rules` from the array object itself (always `undefined`), loading zero TS rules.

**Fix:** Restructure the export to spread the array directly at the top level, then add a separate block for custom overrides:

```js
export default [
  { ignores: ['dist/**', 'node_modules/**'] },

  // Service worker context
  {
    files: ['public/**/*.js'],
    languageOptions: { globals: { ...globals.browser, ...globals.serviceworker } },
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

  // Regression guard: ban raw /api/ strings outside the api/ layer
  {
    files: ['src/**/*.{ts,tsx}'],
    ignores: ['src/api/**'],
    rules: {
      'no-restricted-syntax': [
        'error',
        {
          selector: "Literal[value=/^\\/api\\//]",
          message: "Raw /api/ string detected outside src/api/**. Use wsUrl() or apiClient instead.",
        },
        {
          selector: "TemplateLiteral > TemplateElement[value.raw=/^\\/api\\//]",
          message: "Raw /api/ in template literal outside src/api/**. Use wsUrl() or apiClient instead.",
        },
      ],
    },
  },
]
```

**Why not `tsPlugin.configs['flat/recommended'].rules` with a loop?** Spreading the array directly is the v8-idiomatic pattern and ensures plugin registration, parser config, and rules all load. Extracting `.rules` alone would miss the plugin/parser entries.

### 2. CI lint step — drop `|| true`, remove `--max-warnings 0` from CI only

The CI `npm run lint || true` step (line 98) must become a blocking call. However, `npm run lint` runs `eslint . --max-warnings 0`, which would fail on all 128 `no-explicit-any` warnings. To keep local dev strict while letting CI tolerate pre-existing warnings:

**Change CI step from:**
```yaml
- name: Lint
  working-directory: frontend
  run: npm run lint || true
```

**To:**
```yaml
- name: Lint
  working-directory: frontend
  run: npx eslint . --report-unused-disable-directives-severity error
```

This invocation: fails on `error`-level rules (broken), passes on `warn`-level rules (pre-existing `any`), and still flags unused `eslint-disable` comments as errors. `package.json` lint script stays strict for local use.

### 3. CI `npm audit` — drop `|| true`

**Current (line 102):**
```yaml
run: npm audit --audit-level=high || true
```

**Target:**
```yaml
run: npm audit --audit-level=high
```

Live high-severity findings in `axios` and `react-router` ranges must be resolved first. For each unpatched finding, add an `npm audit --omit=prod` or version override entry, **or** bump the affected package to its fixed version within this PR. If a safe bump is available (check `npm outdated`), apply it. If the upgrade is a breaking major (e.g. react-router v6 → v7), add to an allow-listed advisory with a dated comment in a `.nsprc` / `npm-audit-allowlist.json`, and open a follow-on issue for the upgrade. Do not leave `|| true`.

### 4. CI `pip-audit` — extend allow-list, drop `|| true`

**Current (line 58):**
```yaml
run: pip-audit -r backend/requirements.txt --ignore-vuln PYSEC-2022-42969 || true
```

**Target:**
```yaml
run: pip-audit -r backend/requirements.txt \
  --ignore-vuln PYSEC-2022-42969 \
  --ignore-vuln <ID1> \  # starlette: <vuln> — dated YYYY-MM-DD, tracked in #NNN
  --ignore-vuln <ID2>    # python-multipart: <vuln> — dated YYYY-MM-DD
```

`pip-audit` has no `--fail-on HIGH` flag — it fails on any non-ignored finding. The implementer must run `pip-audit -r backend/requirements.txt` to enumerate current finding IDs, then either bump affected packages (`starlette ≥ 1.0.1`, `python-multipart ≥ 0.0.27`, `python-jose ≥ 3.4.0` if available and compatible) or add them to `--ignore-vuln` with dated comments. Either way, `|| true` is dropped.

---

## Alternatives Considered

### Alt A: `typescript-eslint` wrapper package

Install the `typescript-eslint` helper package (`npm install -D typescript-eslint`) and use `tseslint.config(tseslint.configs.recommended, ...)`. Cleaner API, handles array spreading internally. Rejected for now because it adds a dependency and a build step change for what is a one-line logic bug in the current config — iterating the existing array is simpler and keeps the dependency graph unchanged.

### Alt B: Fix all 125 `any` violations in this PR

Eliminates all warnings immediately, keeps `--max-warnings 0` in CI. Rejected: the issue is labeled `size: S` (< 1 hour); touching 125 sites across API types, hooks, and pages is clearly `size: M+` and buries the actual config/CI plumbing fix in type-system churn.

### Alt C: Drop `|| true` on audits without baselining current findings

Simplest change, but live high-severity findings in `axios`/`react-router`/`starlette` mean CI would immediately be red on the first run — not a tenable state for a PR-gating check. The allowlist/bump approach provides an honest gate that blocks *new* findings while documenting the known debt.

---

## Implementation Checklist

1. `frontend/eslint.config.js` — restructure to spread `tsPlugin.configs['flat/recommended']` array at top level; add custom override block with `'@typescript-eslint/no-explicit-any': 'warn'`
2. `.github/workflows/ci.yml` — lint step: `npx eslint . --report-unused-disable-directives-severity error` (drop `|| true`, drop `--max-warnings 0`)
3. `.github/workflows/ci.yml` — npm audit step: drop `|| true`; bump `axios` and `react-router` to fixed versions or add advisory allowlist file with dated comments
4. `.github/workflows/ci.yml` — pip-audit step: run `pip-audit` to enumerate current IDs; bump or extend `--ignore-vuln` list; drop `|| true`
5. Verify: `npm run lint` (local, strict) exits non-zero on current codebase (128 `any` warnings → fails at `--max-warnings 0`). This is expected and correct for local dev.
6. Verify: CI lint invocation exits 0 on current codebase (warnings tolerated), exits non-zero if an `error`-level rule is violated.
7. Open follow-on issue: "Eliminate `any` usages and re-enable `no-explicit-any: error` + CI `--max-warnings 0`."

---

## Open Questions (non-blocking)

- Is there a `.nsprc` or `npm-audit-allowlist.json` convention preferred in this project for allowlisting npm advisories? If not, inline `--ignore-vuln`-equivalent via `npm audit --ignore-vuln` is not supported natively; use `overrides` in `package.json` or `audit-ci` if the team wants structured allowlisting.
- Should the pip-audit step print the full finding table even for ignored vulns (`--desc` flag) for visibility in CI logs?

---

## Assumptions

- `@typescript-eslint` plugin v8 is what's installed (`package.json` confirms `^8.0.0`). The fix is specific to v8 flat config semantics.
- The `flat/recommended` array entries in v8 carry their own `files` patterns that cover `**/*.ts` and `**/*.tsx`. Spreading them globally (with `dist/**` and `node_modules/**` in ignores) is safe and covers the project's source.
- The size:S estimate remains valid for the ESLint + CI steps. Dependency bumps may be trivial (patch versions) or require a separate follow-on if breaking.
- A follow-on issue will track eliminating the ~128 `any` violations and re-promoting `no-explicit-any` to `error` with `--max-warnings 0` in CI.
