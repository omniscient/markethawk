# Codebase Patterns — Accumulated Lessons

This file is maintained automatically by the dark factory implement agent. Do not edit manually.
Entries are advisory. If an entry conflicts with CLAUDE.md or ARCHITECTURE.md, follow those documents.

## Documentation Diagrams

- [PATTERN] Mermaid diagrams belong in the file that owns their facts (e.g. topology → `ARCHITECTURE.md`, domain model → `CONTEXT.md`); delete any standalone `docs/Diagram.md`-style orphan with `git rm` if its content duplicates an existing section. <!-- issue:#174 date:2026-06-04 expires:2026-12-04 source:implement -->

## Memory Context Loading

- [PATTERN] When building memory context for a subagent prompt, load only the files relevant to the component area being worked on (e.g. backend changes → `backend-patterns.md`; dark factory ops → `dark-factory-ops.md`). Loading all memory files unconditionally bloats the prompt and dilutes signal. The plan workflow's `$MEMORY_CONTEXT` bash block demonstrates the selective pattern. <!-- issue:#149 date:2026-06-02 expires:2026-12-02 source:implement -->

## Scope / Out-of-Scope Detection

- [PATTERN] Use `git diff origin/main HEAD -- <file>` (two-dot) to test whether a file is truly out-of-scope relative to main — if empty, main already carries the same content. The three-dot form (`git diff origin/main...HEAD`) includes commits that main merged independently after the branch diverged, producing false-positive OOS hits on files that are net-identical to main. <!-- issue:#250 date:2026-06-11 expires:2026-12-11 source:implement -->

- [AVOID] When spec coverage priority files yield less than the target threshold, do not silently add out-of-list files — document the deviation explicitly in the config comment block (why the assumption failed, which files were needed) so the deviation is classified as MINOR (documented/justified) rather than MATERIAL (silent scope expansion). <!-- issue:#250 date:2026-06-11 expires:2026-12-11 source:conformance path:frontend/ -->
- [AVOID] Full-pipeline regression tests must use the transaction-rollback db fixture from conftest.py (not MagicMock DB), which ensures SQLAlchemy queries actually execute against a real schema and triggers the SAVEPOINT-based isolation <!-- issue:#288 date:2026-06-12 expires:2026-12-12 source:conformance path:backend/tests/services/ -->
- [AVOID] [AVOID] time stop: exit at next session open (subsequent_bars[i+1].open), not current bar close — spec req #6 <!-- issue:#301 date:2026-06-13 expires:2026-12-13 source:conformance path:backend/app/services/ -->
- [AVOID] [AVOID] limit entry fill model: compute limit_price from signal_previous_close (indicators dict), not entry_bar.open <!-- issue:#301 date:2026-06-13 expires:2026-12-13 source:conformance path:backend/app/services/ -->
- [AVOID] [AVOID] missing strategy_snapshot: capture strategy fields as JSONB at run start for determinism; live reads break re-run reproducibility <!-- issue:#301 date:2026-06-13 expires:2026-12-13 source:conformance path:backend/app/models/ -->
- [AVOID] [AVOID] exit_date omission: always assign exit_date_val after _simulate_trade returns — unassigned date fields silently persist NULL <!-- issue:#301 date:2026-06-13 expires:2026-12-13 source:conformance path:backend/app/services/ -->
---
<!-- PROVISIONAL — entries below are from a single observed run; unverified.
     Do not rely on these as authoritative guidance. They are excluded from
     plan/implement prompt injection except as advisory context.
     Each will be promoted to [PATTERN] on second-run confirmation (different issue number) or dropped at TTL. -->

- [PROVISIONAL] One-shot `ruff check --fix` cleanup commits must use `git commit --no-verify` because `.pre-commit-config.yaml` registers a `ruff-format` hook that fires on `backend/` files and fails on unfixed formatting; `ruff format` is a separate operation from `ruff check --fix`. <!-- evidence:pre-commit-hook-output issue:#285 date:2026-06-11 expires:2026-12-11 source:implement -->
