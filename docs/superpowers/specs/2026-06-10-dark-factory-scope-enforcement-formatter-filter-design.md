# Dark Factory Scope Enforcement — Formatter-Only Hunk Filter Design

**Date:** 2026-06-10
**Status:** Approved (design) — pending implementation plan
**Author:** Brainstormed with Claude (Opus 4.8)
**Issue:** #276

## Problem

The dark-factory conformance gate (`.archon/commands/dark-factory-conformance.md`, Phase 3)
over-reports formatter/linter reformatting of in-scope touched files as scope spillover,
creating backlog tickets for changes that are non-actionable by construction: `ruff` and
`ruff format` re-apply the same formatting on every subsequent commit, so excision "cannot
be sustained."

Documented instances — eight tickets closed and consolidated into #276:

| Ticket(s) | File | Formatter change | Source issue |
|-----------|------|------------------|--------------|
| #247, #263, #268, #269 | `backend/app/core/tracing.py` | Import order | #205 |
| #229 | `backend/app/main.py` | Import order | #192 |
| #231 | `backend/tests/api/test_metrics.py` | Import order | #194 |
| #252 | `backend/app/routers/scanner.py` | List-comprehension rewrap | #191 |
| #253 | `backend/app/routers/system.py` | `get_cached` rewrap | #191 |

All affected files also contained legitimate in-scope feature changes; the formatter noise
was interleaved with real work in the same commit, not isolated.

## Goal

Suppress formatter-only line changes in Python files from the diff fed to the conformance
reviewer, and add an explicit reviewer-prompt rule as a backstop. After this fix:

- No `[OOS]` bullet is emitted for ruff/isort output on an in-scope touched file.
- No Phase 3.6 excision is attempted for non-excisable formatter changes.
- No spillover ticket is filed for formatting noise.

## Non-Goals

- TypeScript / JavaScript — the frontend has no autoformatter (ESLint is lint-only,
  no Prettier); no TS/JS spillover has been observed. If Prettier is later adopted,
  file a follow-up to extend the filter with a TS-specific formatter step.
- Shell, YAML, SQL, or other non-Python files.
- Changes in files that are NOT already touched by in-scope feature work (i.e., if ruff
  reformats a file the feature never touched, that is a genuine OOS change and should
  remain visible).
- Plan conformance (ARTIFACT_KIND=PLAN) — the plan diff contains no `.py` source; the
  filter is a no-op there and requires no special handling.

## Architecture / Approach

Two coordinated layers, both required:

### Layer 1 — Deterministic pre-triage hunk filter (load-bearing fix)

**Location:** Phase 3, Step 3.0 of `.archon/commands/dark-factory-conformance.md` — the
existing pre-triage block that already strips lock files, markdown, and codeindex artifacts.

**Algorithm:**

For each `.py` file that appears in `git diff main...HEAD`:

1. **Get the base version** — `git show main:<file>` into a temp file
   (`/tmp/base_<hash>.py`). Never operate on the working-tree file.
2. **Run the formatter on the base** — apply `ruff format` then
   `ruff check --fix --select I` to a second temp copy (`/tmp/fmtd_<hash>.py`).
   Use the project's config from `backend/pyproject.toml` (line-length 88,
   select = E/W/F/I). This produces what the formatter alone would change.
3. **Compute the formatter delta** — `diff -u /tmp/base_<hash>.py /tmp/fmtd_<hash>.py`
4. **Compute the actual delta** — extract the per-file hunk from the main diff for this
   file (already in memory from Step 3.0's `git diff main...HEAD -- <file>`).
5. **Subtract formatter hunks** — for each hunk in the formatter delta, if the actual
   diff contains an identical or subset hunk at the same line range, remove it from the
   diff fed to the reviewer.
6. **Safety guard — interleaved hunks:** If a hunk in the actual diff overlaps with a
   formatter hunk but also contains non-formatter lines (the feature edit and the
   formatter reflow share the same diff hunk), leave the entire hunk in the diff.
   Let Layer 2 (reviewer prompt) handle this residual case. Never widen to file-level
   exclusion on failure.

The filtered diff (base hunks stripped, feature hunks intact) replaces the raw
`git diff` output passed to `$ARTIFACT_CONTENT` in Step 3.1. A one-line annotation
is prepended to `$ARTIFACT_CONTENT`:

```
[Pre-triage] Formatter-only hunks stripped from X .py file(s): <file-list>
```

This annotation is informational; it tells both the reviewer and any human reading the
conformance output that the filter ran.

**Implementation note:** A short inline Python script embedded in the bash block is the
cleanest implementation for hunk-level diff manipulation. Shell tools (`diff`, `patch`)
are sufficient but complex at hunk granularity; Python's `difflib` operates cleanly on
the same data. Python 3 is always available in the factory container.

### Layer 2 — Reviewer prompt carve-out (backstop for interleaved hunks)

**Location:** `/workspace/markethawk/.claude/skills/refinement/conformance-reviewer-prompt.md`
(also baked into the container as `/opt/refinement-skills/conformance-reviewer-prompt.md`).

**Change:** Add the following rule to the `## Out-of-Scope Changes` section, immediately
before the `[OOS]` bullet format instruction:

> **Formatter / import-ordering exception:** Reformatting and import re-ordering produced by
> `ruff`, `ruff format`, or equivalent linters acting on a Python file that also contains
> in-scope changes is **not** an out-of-scope change. Do NOT emit an `[OOS]` bullet for
> whitespace rewraps, line-length splits, or isort import reorders in touched `.py` files.
> These changes are non-actionable housekeeping — the formatter re-applies them on every
> commit. Only flag as `[OOS]` if the reformatting appears in a file with no spec-required
> changes.

The current `## Out-of-Scope Changes` instruction (lines 51–57) broadly requires listing
"every change in the diff that is NOT (a) spec-named, (b) supporting housekeeping directly
backing an (a) change, or (c) strictly required for the in-scope work to compile/run." The
new rule explicitly carves ruff output on touched files out of that obligation.

## Alternatives Considered

**File-level exclusion (rejected):** If ruff would change anything in a file, exclude the
entire file from the diff. Simpler bash but wrong: every documented spillover case involved
a file that ALSO contained legitimate in-scope feature changes. Excluding the whole file hides
those changes from the reviewer, creating the opposite failure mode (real OOS changes become
invisible in a coincidentally-reformatted file).

**Reviewer-prompt-only (rejected as sole fix):** Updating the prompt without the diff filter
means the reviewer still receives formatter noise, processes it, and must exercise judgment to
suppress it. Judgment is less reliable than deterministic filtering; the current prompt
(clause b of the OOS rule) does not clearly exempt ruff output on touched files, which is why
the over-reporting exists today.

**ESLint / TypeScript extension (deferred):** The frontend has no autoformatter. No TS/JS
spillover tickets have been filed. Building a TS formatter filter now is speculative work
against tooling the repo does not run. If Prettier is added later, the pluggable per-language
structure in Step 3.0 makes it additive.

## Open Questions (non-blocking)

- `ruff` availability in the factory container: ruff is in `backend/requirements.txt`
  and used via pre-commit hooks; it should be present after `pip install -r requirements.txt`.
  The implementer should add a `command -v ruff` guard and log a warning (not abort) if ruff
  is absent — the filter degrades gracefully to "no stripping" in that case.
- `per-file-ignores` in `backend/pyproject.toml` exempts `tests/` from `E402/F811/F841` but
  not from `I` (import sort). The filter should apply to test files as documented (they are
  listed in the spillover examples: `test_metrics.py` was #231).

## Assumptions

- `ruff` is installed in the factory container after `pip install -r requirements.txt`
  (assumption; see Open Questions).
- The formatter delta computation runs against `main` (not a rolling rebase head), consistent
  with Step 3.0's existing `git diff main...HEAD` baseline.
- The pre-triage filter runs on IMPLEMENTATION conformance only — at plan time the diff
  contains no `.py` source, so the filter is a no-op (no `.py` files returned by
  `git diff --name-only main...HEAD -- '*.py'`).
- The container image rebuild (`docker compose --profile factory build dark-factory`) is
  required to propagate the updated conformance-reviewer-prompt.md to `/opt/refinement-skills/`.
