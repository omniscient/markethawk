# Implementation Plan: Pre-Commit Hooks (Ruff + ESLint)

**Date**: 2026-05-28  
**Issue**: #97  
**Spec**: `Docs/superpowers/specs/2026-05-27-pre-commit-hooks-design.md`  
**Branch**: `refine/issue-97-add-pre-commit-hooks--ruff-lint--ruff-fo`

---

## Goal

Add commit-time quality gates: ruff lint + format for Python (auto-fix on commit), ESLint for TypeScript via the existing `npm run lint` script. Includes an initial bulk-fix commit so subsequent commits start from a clean baseline. Documents `pre-commit install` as a required developer setup step in both `DEVELOPMENT.md` and `CLAUDE.md`.

## Architecture

No structural changes to the application. Five files change:

| File | Change |
|------|--------|
| `backend/pyproject.toml` | Add `[tool.ruff]`, `[tool.ruff.lint]`, `[tool.ruff.lint.per-file-ignores]` |
| `frontend/eslint.config.js` | Add service worker globals block for `public/**/*.js` |
| `.pre-commit-config.yaml` | New file — ruff hooks + local ESLint hook |
| `DEVELOPMENT.md` | New "Code Quality" section documenting `pre-commit install` |
| `CLAUDE.md` | Add `pre-commit` to Prerequisites and setup steps |

**Spec deviation (documented and flagged for reviewer)**: The spec specifies `ignore = []` for ruff. This plan sets `ignore = ["E501"]`. Rationale: E501 (line-too-long) is not auto-fixable by ruff, and the codebase has hundreds of existing long lines. Leaving E501 active would permanently block commits on any file with a long line until all lines are manually shortened. E501 enforcement is deferred to a follow-up issue.

## Tech Stack

- **ruff** ≥ 0.11.0 — lint + format, installed host-side via `pip install ruff`
- **pre-commit** — hook framework, host-side only via `pip install pre-commit`, NOT in `backend/requirements.txt`
- **ESLint** — already configured in `frontend/`; hook invokes `npm run lint` via `frontend/node_modules`

---

## File Structure

| File | Action |
|------|--------|
| `backend/pyproject.toml` | Modify — append ruff config sections |
| `frontend/eslint.config.js` | Modify — add service worker globals block |
| `frontend/src/components/scorecard/SignalTable.tsx` | Modify — hoist `SortIcon` to module scope |
| `frontend/src/pages/ActiveWatchlist/AlertBadges.tsx` | Modify — suppress `react-hooks/purity` |
| `frontend/src/pages/ActiveWatchlist/WatchlistTable.tsx` | Modify — suppress `react-hooks/purity` (2 sites) |
| `frontend/src/pages/AutoTrading/OrdersPanel.tsx` | Modify — remove unused `strategies` from destructure |
| `frontend/src/pages/AutoTrading/components.tsx` | Modify — suppress `react-refresh/only-export-components` |
| `frontend/src/pages/Scanner/ScanConfigPanel.tsx` | Modify — remove unused import |
| `frontend/src/pages/Scanner/index.tsx` | Modify — suppress `react-hooks/exhaustive-deps` |
| `.pre-commit-config.yaml` | Create — hook definitions |
| `DEVELOPMENT.md` | Modify — add pre-commit setup section |
| `CLAUDE.md` | Modify — add pre-commit to Prerequisites |

---

## Tasks

### Task 1 — Add ruff config to `backend/pyproject.toml`

**Files**: `backend/pyproject.toml`

**Why first**: Both the initial fix pass (Task 2) and the pre-commit hooks (Task 4) reference `--config backend/pyproject.toml`. Config must exist before either runs.

#### TDD steps

**Step 1.1 — Install ruff and establish pre-config baseline**

```bash
cd /workspace/markethawk
pip install ruff          # host-side only, not requirements.txt

ruff check backend/ --select E,W,F,I --line-length 88 2>&1 | tail -5
# Expected: violation summary ending with "Found N errors." — confirms ruff targets backend/ correctly
```

**Step 1.2 — Implement: add ruff config**

Append to `backend/pyproject.toml`:

```toml
[tool.ruff]
line-length = 88
target-version = "py311"

[tool.ruff.lint]
select = ["E", "W", "F", "I"]
# E501 (line-too-long) is not auto-fixable; suppressed until a dedicated cleanup issue
# resolves existing long lines. Spec deviation: spec specifies ignore = [].
ignore = ["E501"]

[tool.ruff.lint.per-file-ignores]
"**/__init__.py" = ["F401"]
```

**Step 1.3 — Verify config loads and produces baseline**

```bash
ruff check backend/ --config backend/pyproject.toml --statistics 2>&1 | tail -20
# Expected: table of rule counts; E501 should NOT appear

ruff format backend/ --config backend/pyproject.toml --check 2>&1 | tail -3
# Expected: "Would reformat N files." — confirms format config is valid
```

**Step 1.4 — Commit**

```bash
git add backend/pyproject.toml
git commit -m "chore(backend): add ruff lint and format config to pyproject.toml"
# Expected: commit succeeds (no pre-commit hook installed yet)
```

---

### Task 2 — Run initial ruff auto-fix pass

**Files**: All `*.py` under `backend/` (~231 files)

**Why second**: Must clean up existing violations before installing the hook. Installing the hook first would cause the first commit on any Python file to silently auto-fix everything in an unreviewed changeset.

#### TDD steps

**Step 2.1 — Capture baseline violation count**

```bash
ruff check backend/ --config backend/pyproject.toml --statistics 2>&1
# Record the total error count and per-rule breakdown before fixing
```

**Step 2.2 — Run ruff check auto-fix**

```bash
ruff check --fix backend/ --config backend/pyproject.toml
# Expected: "Fixed N errors." — ruff fixes I001 (import order), W291/W293 (whitespace), etc.
```

**Step 2.3 — Run ruff format**

```bash
ruff format backend/ --config backend/pyproject.toml
# Expected: "Reformatted N files, N left unchanged."
```

**Step 2.4 — Verify clean baseline**

```bash
ruff check backend/ --config backend/pyproject.toml
# Expected: exit 0 with no output

ruff format backend/ --config backend/pyproject.toml --check
# Expected: "N files already formatted."
```

If `ruff check` exits non-zero after Steps 2.2–2.3, identify remaining rules:

```bash
ruff check backend/ --config backend/pyproject.toml --statistics
# For each remaining rule code:
# - If it is suppressible globally (rule has no contextual meaning): add to `ignore` in pyproject.toml
#   with a comment explaining why
# - If it requires per-occurrence judgment: add `# noqa: RULE_CODE` inline at each site
# Re-run Step 2.4 after each change to verify clean
```

**Step 2.5 — Commit**

```bash
git add backend/
git commit -m "chore: apply initial ruff format pass

Auto-fix ruff E/W/F/I violations across backend/ Python files.
Style-only changes — no logic modified.
E501 (line-too-long) suppressed; tracked in a follow-up issue."
# Expected: commit succeeds with a large changeset
```

---

### Task 3 — Fix existing frontend ESLint violations

**Files**: Multiple TypeScript files under `frontend/src/` and `frontend/eslint.config.js`

**Why third**: The ESLint hook uses `--max-warnings 0` (from `npm run lint`). All 27 errors and 9 warnings must be resolved before the hook is installed or `pre-commit run --all-files` will fail immediately.

Current violations (confirmed by running `npm run lint` on the codebase):

| File | Rule | Lines | Fix |
|------|------|-------|-----|
| `public/sw.js` | `no-undef` | 6, 7, 16, 32, 35, 41, 50, 51 | Add service worker globals to `eslint.config.js` |
| `src/components/scorecard/SignalTable.tsx` | `react-hooks/static-components` | 73, 146, 152 | Hoist `SortIcon` to module scope |
| `src/pages/ActiveWatchlist/AlertBadges.tsx` | `react-hooks/purity` | 7 | Suppress with comment |
| `src/pages/ActiveWatchlist/WatchlistTable.tsx` | `react-hooks/purity` | 13, 88 | Suppress with comments |
| `src/pages/AutoTrading/OrdersPanel.tsx` | `@typescript-eslint/no-unused-vars` | 20 | Remove `strategies` from destructure |
| `src/pages/AutoTrading/components.tsx` | `react-refresh/only-export-components` | 21, 27, 33, 38, 49, 70, 73, 76 | Suppress with per-line comments |
| `src/pages/Scanner/ScanConfigPanel.tsx` | `@typescript-eslint/no-unused-vars` | 2 | Remove unused import |
| `src/pages/Scanner/index.tsx` | `react-hooks/exhaustive-deps` | 61 | Suppress with comment |

#### TDD steps

**Step 3.1 — Confirm baseline**

```bash
cd /workspace/markethawk/frontend
npm run lint 2>&1
# Expected: "36 problems (27 errors, 9 warnings)" — confirms the known violation set
# If different, adapt the fixes below to match actual output
```

**Step 3.2 — Fix `frontend/eslint.config.js`: add service worker globals**

In `frontend/eslint.config.js`, add a new config block after the `{ ignores: [...] }` entry and before `js.configs.recommended`:

```javascript
// Service worker (runs in browser SW context, not in main-thread JS)
{
  files: ['public/**/*.js'],
  languageOptions: {
    globals: {
      ...globals.browser,
      ...globals.serviceworker,
    },
  },
},
```

This provides `self`, `clients`, `console` as known globals for `public/sw.js` without changing how `src/**` files are linted.

**Step 3.3 — Fix `SignalTable.tsx`: hoist `SortIcon` to module scope**

`SortIcon` is currently defined at line 73 inside `SignalTable`. Move it to module scope (after the existing module-scope helpers `colorForPct`, `severityBadge`, `fmtPct`, `fmtPrice`) and add `sortBy`/`sortOrder` as explicit props:

```typescript
// Add before `const SignalTable: React.FC<...>` definition
const SortIcon: React.FC<{ field: SortField; sortBy: SortField; sortOrder: 'asc' | 'desc' }> = (
  { field, sortBy, sortOrder }
) => {
  if (sortBy !== field) return null;
  return sortOrder === 'desc' ? (
    <ChevronDown className="h-3 w-3 inline ml-0.5" />
  ) : (
    <ChevronUp className="h-3 w-3 inline ml-0.5" />
  );
};
```

Remove the original `SortIcon` definition from inside `SignalTable` (lines 73–80).

Update every `<SortIcon field="..." />` usage site within `SignalTable`'s JSX to pass the new props:

```tsx
<SortIcon field="event_date" sortBy={sortBy} sortOrder={sortOrder} />
<SortIcon field="ticker" sortBy={sortBy} sortOrder={sortOrder} />
// ...and any other SortIcon usages found in the file
```

**Step 3.4 — Fix `AlertBadges.tsx`: suppress `react-hooks/purity`**

At line 7, insert the following comment on a new line immediately before the existing `const age = Date.now()...` line. Do not duplicate or replace the existing line — only insert the comment:

```typescript
// eslint-disable-next-line react-hooks/purity -- staleness check intentionally uses current time; component re-renders are infrequent
```

**Step 3.5 — Fix `WatchlistTable.tsx`: suppress `react-hooks/purity` (2 sites)**

At line 13, insert on a new line immediately before the existing `const isStale = ...` line (insert comment only):

```typescript
// eslint-disable-next-line react-hooks/purity -- staleness check; acceptable impurity for live data display
```

At line 88, insert on a new line immediately before the existing `const isLive = ...` line (insert comment only):

```typescript
// eslint-disable-next-line react-hooks/purity -- staleness check; acceptable impurity for live data display
```

**Step 3.6 — Fix `OrdersPanel.tsx`: remove unused `strategies` from destructure**

At the function signature (line ~20), remove `strategies` from the destructuring since it is never referenced in the function body:

```typescript
// Before:
export function OrdersPanel({
  orders, loadingOrders, orderFilter, onOrderFilter,
  strategies, onApprove, onReject, onCancel,
}: OrdersPanelProps) {

// After:
export function OrdersPanel({
  orders, loadingOrders, orderFilter, onOrderFilter,
  onApprove, onReject, onCancel,
}: OrdersPanelProps) {
```

Leave `strategies` in the `OrdersPanelProps` interface — do not remove it from the interface or the call site. The prop is accepted but not yet used in the component body; removing from the interface would require updating the parent component.

**Step 3.7 — Fix `components.tsx`: suppress `react-refresh/only-export-components`**

Add `// eslint-disable-next-line react-refresh/only-export-components` immediately before each of the 8 flagged export lines (21, 27, 33, 38, 49, 70, 73, 76):

```typescript
// eslint-disable-next-line react-refresh/only-export-components -- shared constant, intentionally co-located
export const SESSION_OPTIONS = [...]

// eslint-disable-next-line react-refresh/only-export-components -- shared constant, intentionally co-located
export const DIRECTION_OPTIONS = [...]

// (repeat for ENTRY_TYPES, STATUS_CONFIG, DEFAULT_STRATEGY, fmt, fmtUSD, pnlColor)
```

**Step 3.8 — Fix `ScanConfigPanel.tsx`: remove unused import**

At line 2, remove `formatDistanceToNow` from the `date-fns` import:

```typescript
// Before:
import { format, formatDistanceToNow } from 'date-fns';

// After:
import { format } from 'date-fns';
```

**Step 3.9 — Fix `Scanner/index.tsx`: suppress `react-hooks/exhaustive-deps`**

At line 61, insert a disable comment on a new line immediately before the existing `}, [existingResults]);` closing line. Do not duplicate or replace the existing line — only insert the comment. Adding `state` to the dependency array causes an infinite re-render loop because the state object is recreated on every render:

```typescript
// eslint-disable-next-line react-hooks/exhaustive-deps -- adding state to deps causes infinite loop; state.setScanResults setter is the stable reference needed here
```

**Step 3.10 — Verify all violations resolved**

```bash
cd /workspace/markethawk/frontend
npm run lint
# Expected: exit 0, "0 problems"
```

**Step 3.11 — TypeScript check**

```bash
npx tsc --noEmit
# Expected: exit 0 — confirms SignalTable.tsx prop changes did not break types
```

**Step 3.12 — Commit**

```bash
cd /workspace/markethawk
git add frontend/
git commit -m "fix(frontend): resolve all ESLint violations before pre-commit hook install"
# Expected: commit succeeds
```

---

### Task 4 — Create `.pre-commit-config.yaml`

**Files**: `.pre-commit-config.yaml` (new)

#### TDD steps

**Step 4.1 — Install pre-commit**

```bash
pip install pre-commit
pre-commit --version
# Expected: "pre-commit N.N.N"
```

**Step 4.2 — Determine current ruff-pre-commit revision**

```bash
RUFF_REV=$(curl -s https://api.github.com/repos/astral-sh/ruff-pre-commit/releases/latest \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['tag_name'])")
echo "Using ruff rev: $RUFF_REV"
# Expected output: something like "Using ruff rev: v0.11.13"
# This value is substituted into the YAML in the next step
```

**Step 4.3 — Verify ESLint binary**

```bash
ls /workspace/markethawk/frontend/node_modules/.bin/eslint
# Expected: file exists — confirms local ESLint hook can run
# If missing: cd frontend && npm install
```

**Step 4.4 — Implement: create `.pre-commit-config.yaml`**

Create `/workspace/markethawk/.pre-commit-config.yaml`. Use the `$RUFF_REV` value captured in Step 4.2 as the `rev:` value (do not write the literal string `$RUFF_REV` — substitute the actual tag):

```yaml
repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.11.13   # replace with actual output from Step 4.2
    hooks:
      - id: ruff
        args: [--fix, --config, backend/pyproject.toml]
      - id: ruff-format
        args: [--config, backend/pyproject.toml]

  - repo: local
    hooks:
      - id: eslint
        name: eslint
        language: system
        entry: bash -c 'cd frontend && npm run lint'
        pass_filenames: false
        files: '\.(ts|tsx|js|jsx)$'
```

`files:` is single-quoted so the `\.` backslash is preserved verbatim by YAML.

Note: The ESLint hook runs `npm run lint` on the full `frontend/` tree regardless of which specific files are staged. This means a Python-only commit will still run the ESLint check. This is intentional — it catches any pre-existing ESLint regressions — and is documented in `DEVELOPMENT.md` (Task 5).

**Step 4.5 — Install hooks**

```bash
cd /workspace/markethawk
pre-commit install
# Expected: "pre-commit installed at .git/hooks/pre-commit"
```

**Step 4.6 — Run against all files**

```bash
pre-commit run --all-files
# Expected: ruff "Passed", ruff-format "Passed", eslint "Passed"
# If any hook fails: investigate output, fix violations, re-run
```

**Step 4.7 — Commit**

```bash
git add .pre-commit-config.yaml
git commit -m "feat: add pre-commit config (ruff lint, ruff format, ESLint hooks)"
# Expected: pre-commit runs all hooks, all pass, commit succeeds
```

---

### Task 5 — Update `DEVELOPMENT.md` with pre-commit setup instructions

**Files**: `DEVELOPMENT.md`

#### TDD steps

**Step 5.1 — Identify insertion point**

```bash
grep -n "## Manual Setup\|## Database Migrations" DEVELOPMENT.md
# Expected: Manual Setup at ~107, Database Migrations at ~140
# Insert new section immediately before the ## Database Migrations line
```

**Step 5.2 — Implement: add section**

Insert immediately before `## Database Migrations`. The block to insert (inner triple-backtick fences are real code fences in the final file; they are shown indented here to avoid Markdown fence collision in the plan document):

    ## Code Quality (Pre-commit Hooks)

    [pre-commit](https://pre-commit.com/) enforces ruff lint, ruff format, and ESLint before every
    commit. It is a **host-side** tool — install it once per machine, not inside Docker.

    ```bash
    pip install pre-commit   # one-time host install
    pre-commit install       # register hooks in .git/hooks/pre-commit (run once per clone)
    ```

    After `pre-commit install`, every `git commit` automatically:
    1. Runs **ruff lint** on staged Python files — auto-fixes fixable violations and re-stages the file
    2. Runs **ruff format** on staged Python files — applies consistent formatting
    3. Runs **ESLint** (`npm run lint`) when any `.ts/.tsx/.js/.jsx` file is staged

    Note: the ESLint hook scans the entire `frontend/` tree, so Python-only commits will still
    trigger it. This is intentional — it catches lint regressions before they accumulate.

    If a hook modifies a file (ruff auto-fix), the commit is aborted so you can review the change.
    Re-run `git commit` to proceed.

    To run hooks manually against all files:

    ```bash
    pre-commit run --all-files
    ```

**Step 5.3 — Verify code fence consistency**

```bash
grep -A 30 "## Code Quality" DEVELOPMENT.md
# Confirm: both bash blocks are in triple-backtick fences, matching surrounding sections
```

**Step 5.4 — Commit**

```bash
git add DEVELOPMENT.md
git commit -m "docs(development): document pre-commit install as required setup step"
# Expected: hooks run, all pass, commit succeeds
```

---

### Task 6 — Update `CLAUDE.md` Prerequisites

**Files**: `CLAUDE.md`

**Why**: `CLAUDE.md`'s "Setup for AI Development" section drives autonomous agent onboarding (Steps 1–5). Without `pre-commit install` in that checklist, AI-driven workflows will commit code without quality gates active.

#### TDD steps

**Step 6.1 — Locate insertion points**

```bash
grep -n "pre-commit\|### Prerequisites\|claude --version\|Step 2\|Step 3" CLAUDE.md | head -20
# Expected: Prerequisites section with docker, git, gh, bun, claude listed
# pre-commit should NOT appear yet; identify lines for the two insertions below
```

**Step 6.2 — Add pre-commit to Prerequisites list**

In `CLAUDE.md` under `### Prerequisites`, add `pre-commit` after the `claude` entry (match surrounding format exactly):

    - pre-commit: `pip install pre-commit` (macOS/Linux/Windows)

**Step 6.3 — Add pre-commit install to setup steps**

In `CLAUDE.md`, add a new step after "Step 2 — Environment and services". The block to insert (inner triple-backtick fence shown indented to avoid plan-document fence collision):

    ### Step 2.5 — Install pre-commit hooks

        ```bash
        pre-commit install    # registers hooks in .git/hooks/pre-commit
        ```

**Step 6.4 — Verify**

```bash
grep -n "pre-commit" CLAUDE.md
# Expected: at least 2 matches — Prerequisites entry and setup step
```

**Step 6.5 — Commit**

```bash
git add CLAUDE.md
git commit -m "docs(claude): add pre-commit to prerequisites and setup steps"
# Expected: hooks run, all pass, commit succeeds
```

---

## Validation Checklist

After all six tasks:

```bash
# 1. ruff config produces no violations
ruff check backend/ --config backend/pyproject.toml
# Expected: exit 0, no output

# 2. all Python files are formatted
ruff format backend/ --config backend/pyproject.toml --check
# Expected: "N files already formatted."

# 3. pre-commit hooks are installed
head -1 .git/hooks/pre-commit
# Expected: shebang line from pre-commit

# 4. all hooks pass a full-file run
pre-commit run --all-files
# Expected: ruff "Passed", ruff-format "Passed", eslint "Passed"

# 5. smoke-test a real commit and undo it cleanly
echo "" >> backend/app/__init__.py
git add backend/app/__init__.py
git commit -m "test: verify pre-commit hooks fire"
# Expected: hooks run, all pass, commit succeeds
git reset HEAD~1
git checkout -- backend/app/__init__.py
```

---

## Commit Summary

| Task | Commit message |
|------|---------------|
| 1 | `chore(backend): add ruff lint and format config to pyproject.toml` |
| 2 | `chore: apply initial ruff format pass` |
| 3 | `fix(frontend): resolve all ESLint violations before pre-commit hook install` |
| 4 | `feat: add pre-commit config (ruff lint, ruff format, ESLint hooks)` |
| 5 | `docs(development): document pre-commit install as required setup step` |
| 6 | `docs(claude): add pre-commit to prerequisites and setup steps` |
