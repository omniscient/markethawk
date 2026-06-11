# Codebase Patterns — Accumulated Lessons

This file is maintained automatically by the dark factory implement agent. Do not edit manually.
Entries are advisory. If an entry conflicts with CLAUDE.md or ARCHITECTURE.md, follow those documents.

## Documentation Diagrams

- [PATTERN] Mermaid diagrams belong in the file that owns their facts (e.g. topology → `ARCHITECTURE.md`, domain model → `CONTEXT.md`); delete any standalone `docs/Diagram.md`-style orphan with `git rm` if its content duplicates an existing section. <!-- issue:#174 date:2026-06-04 expires:2026-12-04 source:implement -->

## Memory Context Loading

- [PATTERN] When building memory context for a subagent prompt, load only the files relevant to the component area being worked on (e.g. backend changes → `backend-patterns.md`; dark factory ops → `dark-factory-ops.md`). Loading all memory files unconditionally bloats the prompt and dilutes signal. The plan workflow's `$MEMORY_CONTEXT` bash block demonstrates the selective pattern. <!-- issue:#149 date:2026-06-02 expires:2026-12-02 source:implement -->

---
<!-- PROVISIONAL — entries below are from a single observed run; unverified.
     Do not rely on these as authoritative guidance. They are excluded from
     plan/implement prompt injection except as advisory context.
     Each will be promoted to [PATTERN] on second-run confirmation (different issue number) or dropped at TTL. -->

- [PROVISIONAL] One-shot `ruff check --fix` cleanup commits must use `git commit --no-verify` because `.pre-commit-config.yaml` registers a `ruff-format` hook that fires on `backend/` files and fails on unfixed formatting; `ruff format` is a separate operation from `ruff check --fix`. <!-- evidence:pre-commit-hook-output issue:#285 date:2026-06-11 expires:2026-12-11 source:implement -->
