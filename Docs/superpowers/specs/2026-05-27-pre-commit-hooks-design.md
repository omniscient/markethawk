# Pre-Commit Hooks Design (Ruff + ESLint)

**Date**: 2026-05-27  
**Status**: Draft  
**Scope**: Add pre-commit hooks enforcing ruff lint, ruff format, and ESLint on every commit. Includes initial auto-fix pass and developer setup documentation.

---

## Overview

No commit-time quality gates exist for the codebase. Python has no linter or formatter configured (ruff cache is gitignored but no config exists). ESLint is configured for the frontend but not enforced before commits. This allows style inconsistencies and lint violations to accumulate silently. This spec adds a `.pre-commit-config.yaml` at the repo root, ruff config in `backend/pyproject.toml`, a one-time auto-fix commit, and a `DEVELOPMENT.md` update documenting the host-side setup step.

---

## Requirements

- Pre-commit framework installed and configured for the repo (`pre-commit install`)
- Every Python file change triggers ruff lint + ruff format (auto-fix on commit)
- Every TypeScript/JavaScript file change triggers ESLint via the existing `npm run lint` script
- Ruff configured with: line length 88, rules E/W/F/I, `F401` suppressed in `__init__.py` files only
- An initial auto-fix commit cleans up all existing violations so subsequent commits start clean
- `DEVELOPMENT.md` documents `pre-commit install` as a required setup step
- `pre-commit` is documented as a host-side tool, not added to `backend/requirements.txt`

---

## Architecture / Approach

### Approach Chosen: Comprehensive setup with local ESLint hook

**`.pre-commit-config.yaml`** at repository root:

```yaml
repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.11.0   # pin to latest stable at implementation time
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
        files: \.(ts|tsx|js|jsx)$
```

Key decisions:
- `--fix` on the ruff lint hook means the hook auto-corrects fixable violations and re-stages the file, rather than blocking the commit.
- `--config backend/pyproject.toml` for both ruff hooks since all Python tooling config lives there.
- `local` hook for ESLint uses the project's installed `node_modules` — avoids ESLint 9 flat-config compatibility issues with `pre-commit/mirrors-eslint`.
- `pass_filenames: false` on the ESLint hook because `npm run lint` scans the full `frontend/src` tree via the script's own glob.

**`backend/pyproject.toml`** additions:

```toml
[tool.ruff]
line-length = 88
target-version = "py311"

[tool.ruff.lint]
select = ["E", "W", "F", "I"]
ignore = []

[tool.ruff.lint.per-file-ignores]
"**/__init__.py" = ["F401"]
```

Rule rationale:
- **E/W** (pycodestyle): style and whitespace
- **F** (pyflakes): unused imports, undefined names
- **I** (isort): import ordering — 33+ files have stdlib imports interleaved after third-party imports
- **F401 in `__init__.py`**: model/schema init files import names for re-export; suppressing avoids false positives

**Initial format pass** (one-time commit):
Run `ruff check --fix backend/ && ruff format backend/` from the repo root before installing the hook. Commit as a single "chore: apply initial ruff format pass" commit. This ensures subsequent commits start from a clean baseline.

---

## Alternatives Considered

### Option A: `mirrors-eslint` pre-commit hook
Use `repo: https://github.com/pre-commit/mirrors-eslint` with `additional_dependencies` listing all frontend plugins. Rejected because `mirrors-eslint` installs ESLint in an isolated pre-commit environment; ESLint 9 flat config requires the config file to be reachable from the install location, and the three project plugins (`@typescript-eslint`, `react-hooks`, `react-refresh`) must be version-pinned to match `package.json` exactly. This is fragile and duplicates version tracking.

### Option B: Root-level `ruff.toml`
Create a `ruff.toml` at the repo root instead of adding `[tool.ruff]` to `backend/pyproject.toml`. Rejected because the existing Python tooling config (pytest, coverage) lives in `backend/pyproject.toml`. Splitting config between a root `ruff.toml` and `backend/pyproject.toml` fragments the tooling story without benefit.

### Option C: CI enforcement only (no pre-commit hook)
Add a GitHub Actions lint step instead of pre-commit hooks. Rejected as out of scope — CI enforcement is complementary but does not provide the local fast-feedback loop the issue is targeting. Pre-commit hooks catch violations before the push happens.

---

## Open Questions

- Should a minimum ruff version be pinned in DEVELOPMENT.md? (non-blocking — the pre-commit hook pins via `rev:`)
- Should `mypy` or `pyright` type checking be added to the hook? (out of scope for this issue — type checking is a separate concern)

---

## Assumptions

- **(flagged)** Node.js and npm are available on developer host machines. The ESLint local hook runs `npm run lint`; if `node_modules` are not installed in `frontend/`, the hook will fail. The `DEVELOPMENT.md` setup section already includes `npm install` under "Frontend (manual)" — this assumption holds for any developer who has run local setup.
- **(flagged)** Ruff version `v0.11.x` (latest stable as of 2026-05-27) supports `[tool.ruff]` in `pyproject.toml` with `--config` flag. This has been the case since ruff 0.1.0.
- The initial format pass will not change any runtime behavior — ruff format is a pure whitespace/style formatter and ruff's auto-fixes for E/W/F/I rules do not affect logic.
- All Python source files live under `backend/`. There are no Python files at the repo root that need linting (the root `run.py` is a thin entrypoint — confirm at implementation time).
