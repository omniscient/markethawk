# Docs/ → docs/ Casing Fix Design Spec

**Issue**: #171 — docs: fix Docs/ vs docs/ casing collision (breaks links in Linux dark factory)
**Date**: 2026-06-04
**Component**: `Docs/**`, `CLAUDE.md`, `.archon/commands/`, `.claude/skills/`

## Summary

Rename the capital-D `Docs/` tree to lowercase `docs/` so that all existing lowercase `docs/` references in `CLAUDE.md` and `Docs/agents/domain.md` resolve correctly on Linux (case-sensitive) where dark-factory containers run. Update the one capital-D `Docs/database-schema.md` reference in `CLAUDE.md` and all `Docs/` references in operational agent command/skill files.

## Problem

Git tracks both `Docs/` (capital D — 48 files) and `docs/` (lowercase — `codeindex-hotspots.md`). Six links in `CLAUDE.md` already use lowercase `docs/` but point at files that live under the capital-D `Docs/`, so they silently 404 inside Linux dark-factory containers. `Docs/agents/domain.md` has the same problem.

## Requirements

- Move all contents of `Docs/` into `docs/` using `git mv` (merge, not replace, since `docs/codeindex-hotspots.md` must survive).
- `Docs/` must not exist after the migration; `docs/` contains all 49 files.
- `CLAUDE.md:305` — change `Docs/database-schema.md` to `docs/database-schema.md`.
- All 9 capital-D `Docs/` references in `.archon/commands/*.md` updated to `docs/`.
- All 4 capital-D `Docs/scanner-validation/` references in `.claude/skills/validate-scanner/SKILL.md` updated to `docs/scanner-validation/`.
- The `Docs/superpowers/specs/` reference in `.claude/skills/refinement/orchestrator-prompt.md` updated to `docs/superpowers/specs/`.
- `docs/agents/domain.md` (post-rename) — already uses lowercase `docs/`; no edit needed.
- No backend or frontend code changes.
- No database migrations.

## Architecture

**Rename strategy**: `docs/` already exists, so `git mv Docs/ docs/` would fail. Instead, move each subdirectory and loose file individually: `git mv Docs/adr docs/adr`, `git mv Docs/agents docs/agents`, `git mv Docs/superpowers docs/superpowers`, `git mv Docs/scanner-validation docs/scanner-validation`, `git mv Docs/presentations docs/presentations`, then move the loose files (`database-schema.md`, `database-schema.html`, `Diagram.md`). Git tracks renames as moves, preserving history.

**Post-rename reference audit**: Every file outside `Docs/` that hard-codes `Docs/` must be updated. Relative links inside `Docs/` (e.g. `../specs/`, `../../adr/`) are path-relative and continue working after the directory rename.

## Alternatives Considered

**One-step `git mv Docs docs` (no capital)**: Only works on a case-sensitive filesystem. The Windows dev checkout would need a two-step rename (Docs → Docs_tmp → docs). The per-file approach works on both platforms.

**Keep capital-D Docs/ and fix all lowercase references**: Would require changing 6+ CLAUDE.md lines and domain.md. Unconventional — lowercase `docs/` is the Linux standard. The issue recommends lowercase.
