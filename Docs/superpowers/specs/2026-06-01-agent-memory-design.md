---
# Agent Memory Design

**Date:** 2026-06-01

## Overview

Every invocation of the dark factory and refinement pipeline starts cold: each run re-reads the codebase and GitHub issue from scratch, with no knowledge of what prior runs discovered, what patterns worked, or what approaches were rejected. This means agents repeatedly rediscover the same codebase conventions, re-ask equivalent architectural questions, and occasionally reproduce bugs that prior runs already fixed. A file-based, repo-committed memory system gives agents cumulative, cross-run knowledge — letting each run build on the lessons of all prior runs rather than starting from zero.

## Requirements

- Agents must be able to read accumulated lessons from past runs before beginning any substantive work, so that known-good patterns are followed and known-bad patterns are avoided from the outset.
- Memory must be writable by dark factory implementation runs after a feature is complete, capturing any new patterns, anti-patterns, or corrective fixes discovered during that run.
- Memory must be scoped by area (global codebase, backend, frontend, infrastructure) so agents only load context relevant to the current issue, keeping prompt size bounded.
- Each memory entry must be tagged with a type (`[PATTERN]`, `[AVOID]`, or `[FIX]`) and annotated with its source issue and date, so entries are auditable and removable.
- Duplicate detection must be performed before writing: an agent must check whether a semantically equivalent entry already exists before appending a new one.
- Memory files must be committed to the repo (not stored in ephemeral container state) so they survive container restarts, scheduler crashes, and fresh dark factory clones.
- The refinement pipeline (refine and plan commands) must read memory before assembling the spec or plan, so spec decisions avoid approaches already marked `[AVOID]` in the codebase.
- The implementation command must read memory before Phase 2 (PLAN) so plan steps bake in known patterns explicitly rather than leaving them implicit.
- After implementation (Phase 4: DOCUMENT), the implementation command must write a MEMORY UPDATE phase that appends new insights and commits the updated memory files.
- Memory injection must require no new infrastructure — plain markdown files read with the existing `Read` tool are sufficient.

## Architecture

### Memory Storage

Memory lives in a directory committed to the repo:

```
.archon/memory/
  codebase-patterns.md     # Global lessons applicable to any change in this repo
  backend-patterns.md      # SQLAlchemy async, FastAPI routers, Alembic, Celery
  frontend-patterns.md     # React Query, TypeScript, Tailwind, component structure
  dark-factory-ops.md      # Docker Compose, seed data, preview stack, env vars
```

Files are plain markdown, human-readable, and version-controlled. No database, no new service, no new infrastructure. Agents read them with the `Read` tool at the start of each run and append to them at the end of implementation runs.

### Memory Types

Each entry follows the format:

```
- [TYPE] <concise, actionable sentence referencing specific paths/commands/functions> <!-- issue:#N date:YYYY-MM-DD -->
```

**[PATTERN]** — something that consistently works and should be repeated:
- Example: `[PATTERN] After any SQLAlchemy model change, import the model in backend/app/models/__init__.py before running alembic revision --autogenerate, or the migration will be empty. <!-- issue:#42 date:2026-05-10 -->`

**[AVOID]** — something that consistently fails or causes problems:
- Example: `[AVOID] Do not use synchronous SQLAlchemy sessions in FastAPI route handlers; the app uses async-only sessions via AsyncSession from sqlalchemy.ext.asyncio. <!-- issue:#67 date:2026-05-18 -->`

**[FIX]** — a corrective action for a known failure mode:
- Example: `[FIX] If alembic revision --autogenerate produces an empty migration, verify the model is imported in backend/app/models/__init__.py and that Base is the same DeclarativeBase instance used in database.py. <!-- issue:#71 date:2026-05-20 -->`

### Write Triggers

Exactly one trigger: **after Phase 4 (DOCUMENT) completes in the dark factory implementation command** (`dark-factory-implement.md`), before the final report.

- **Which agent performs the write**: The dark factory implementation agent (the same agent that ran Phases 1–4). It has full read/write access to the working tree.
- **What is written**: Zero or more new entries appended to the appropriate memory file(s). Each entry captures a pattern, anti-pattern, or corrective fix discovered during this implementation run that is not already present in the memory files.
- **Deduplication**: Before appending, the agent checks whether a semantically equivalent lesson already exists (simple string search of the core sentence). Entries already covered by CLAUDE.md are not duplicated into memory.
- **Commit**: If any entries were added, a single commit is created: `git commit -m "memory: lessons from issue #N"`.
- **Skip condition**: If no new insights were gained, no commit is created.

The refinement pipeline (refine and plan commands) does **not** write memory. Refinement agents observe and specify; they do not implement, so they do not discover new runtime lessons. This keeps the write path simple and attributable.

### Read and Injection Mechanism

Memory is injected as a **Phase 1 read step** in each agent command, immediately after reading `CLAUDE.md` and `ARCHITECTURE.md` and before any codebase exploration or work begins.

**Injection logic (applied identically in all three commands)**:

1. Always read `.archon/memory/codebase-patterns.md` (global, applies to every issue).
2. If the issue touches backend code (models, routers, services, tasks, migrations): read `.archon/memory/backend-patterns.md`.
3. If the issue touches frontend code (components, pages, hooks, API layer): read `.archon/memory/frontend-patterns.md`.
4. If the issue touches Docker, seed data, environment variables, or preview infrastructure: read `.archon/memory/dark-factory-ops.md`.

The agent applies entries as strong hints throughout its work. If a memory entry conflicts with `CLAUDE.md` or `ARCHITECTURE.md`, those authoritative documents take precedence.

**Why Phase 1 (not a separate tool or step)**: All three agent commands already have a Phase 1 LOAD step that reads project documents. Memory reads slot naturally into this phase — no new phase, no new tooling, no change to the prompt handoff mechanism. The agent's existing `Read` tool is sufficient.

**Refinement-specific note**: In `dark-factory-refine.md`, `[AVOID]` entries are flagged as especially relevant to spec decisions — agents are instructed not to specify approaches already known to fail in this codebase.

**Plan-specific note**: In `dark-factory-plan.md`, agents are instructed to bake memory lessons directly into plan task steps (e.g., "import model in `__init__.py`" becomes an explicit numbered step, not an implicit assumption).

### Integration Points

The following files are created or modified:

| File | Change |
|------|--------|
| `.archon/memory/codebase-patterns.md` | **New file** — global lessons, bootstrapped with known patterns from CLAUDE.md |
| `.archon/memory/backend-patterns.md` | **New file** — backend-specific lessons |
| `.archon/memory/frontend-patterns.md` | **New file** — frontend-specific lessons |
| `.archon/memory/dark-factory-ops.md` | **New file** — Docker/infra lessons |
| `.archon/commands/dark-factory-implement.md` | **Modified** — Phase 1 reads memory files; new Phase 5 MEMORY UPDATE added; old Phase 5 REPORT renumbered to Phase 6 |
| `.archon/commands/dark-factory-refine.md` | **Modified** — Phase 1 reads memory files after loading CLAUDE.md/ARCHITECTURE.md; `[AVOID]` entries highlighted for spec decisions |
| `.archon/commands/dark-factory-plan.md` | **Modified** — Phase 1 reads memory files; instruction to bake lessons into plan steps explicitly |

## Implementation Steps

1. **Create `.archon/memory/` directory** and bootstrap four memory files with initial entries derived from patterns already documented in `CLAUDE.md` and `ARCHITECTURE.md`. Bootstrapped entries use `<!-- bootstrap date:2026-06-01 -->` as the source annotation (no issue number, since they come from existing docs rather than a run).

2. **Modify `.archon/commands/dark-factory-implement.md`**:
   - In Phase 1 (LOAD), after the existing CLAUDE.md read instruction, add four numbered steps that read the memory files conditionally based on issue area.
   - Add Phase 5 MEMORY UPDATE with full instructions: review the run, check for new insights, deduplicate, determine entry type, write entries with `[TYPE]` tags and source comments, commit if anything new.
   - Renumber old Phase 5 REPORT to Phase 6 REPORT.
   - Add PHASE_5_CHECKPOINT.

3. **Modify `.archon/commands/dark-factory-refine.md`**:
   - In Phase 1 (LOAD), after the existing orchestrator-prompt/product-owner-prompt/config reads, add four numbered steps that read the memory files conditionally.
   - Add a note that `[AVOID]` entries are especially relevant to spec decisions.

4. **Modify `.archon/commands/dark-factory-plan.md`**:
   - In Phase 1 (LOAD), after the existing CLAUDE.md and spec reads, add four numbered steps that read the memory files conditionally.
   - Add an instruction to incorporate relevant memory lessons as explicit numbered steps in plan tasks rather than leaving them implicit.

5. **Commit all new and modified files** with message: `feat: add file-based agent memory to dark factory and refinement pipeline`.

6. **Validate** by running a test dark factory implementation run and confirming: (a) memory files are read in Phase 1 logs, (b) a `memory:` commit is created at the end if new insights were found, (c) the updated memory file shows the new entry with correct format and source annotation.

## Alternatives Considered

**Option A: Extend `/root/.claude/projects/-workspace-markethawk/memory/`**
The Claude Code project memory directory exists at this path but is empty. Extending it would co-locate Claude Code session memory with pipeline agent memory. Rejected because: the directory is host-mounted at `/root/`, which the dark factory container may not have access to; memory stored there is not version-controlled and not reviewable in PRs; it would couple pipeline agents to the Claude Code session's memory format.

**Option B: PostgreSQL table for cross-referenced memory**
A new `agent_memory` table would enable SQL queries (e.g., "find all AVOID entries for backend"). Rejected because: it requires a schema migration, a new service dependency, and query logic in agent prompts; the volume of memory entries is small enough (tens to low hundreds) that plain markdown search is sufficient; it would also make memory inaccessible when the database is down or during cold dark factory clones.

**Option C: Memory write only (no read-back) as MVP**
Writing memory after each run without any read injection would prove the write path without changing agent behavior. Rejected in favor of full read+write because: write-only memory has zero value until read injection is also implemented, the two changes are coupled in the same three command files, and the incremental cost of adding the Phase 1 read steps is low once the memory files exist.

## Open Questions

- Should the refinement pipeline ever write memory? Currently only the implementation command writes. If refinement agents begin producing specs that correct previously-approved specs (e.g., discovering that a proposed architecture violates a codebase constraint), those insights could also be captured. Left as a future extension.
- Should memory entries have an explicit expiry mechanism? Entries could become stale if the codebase changes significantly. A periodic manual review pass (or a `[DEPRECATED]` tag) could handle this, but no automated mechanism is specified here.
- Should the architect subagent receive memory context? Currently the plan command loads memory and bakes lessons into plan steps; the architect subagent receives only `$SPEC_CONTENT` and `$PLAN_CONTENT`. Injecting a memory block into the architect prompt could reduce false-positive "Issues Found" verdicts. Left as a future extension.

## Assumptions

- The dark factory container clones the repo fresh per run, so memory files committed to the repo are automatically available in every run without any additional volume mounts or setup.
- Agents have write access to the `.archon/memory/` directory inside the container (they have write access to the entire working tree clone).
- The volume of memory entries will remain small enough (< 200 entries per file) that reading entire files in Phase 1 does not meaningfully expand prompt context beyond what is already loaded (CLAUDE.md, ARCHITECTURE.md, codebase files).
- Memory entries are written in English prose using the existing `Edit` tool (appending to a markdown file) — no custom tooling is required.
- Conflicting entries (e.g., a `[PATTERN]` that contradicts an `[AVOID]`) are resolved by human review on the PR that introduces them, since memory files are committed and diff-visible.
