# Dark Factory — Agent Memory for Subagent Self-Improvement

**Date:** 2026-06-01
**Issue:** #149
**Component:** `.archon/commands/`, `.archon/memory/`, `dark-factory/entrypoint.sh`
**Approach:** File-based, repo-committed memory store read at agent load time and updated post-run

## Problem

The dark factory's subagents (implement, refine, plan, validate) start every run with zero institutional knowledge. Each run re-discovers the same codebase patterns, makes the same avoidable mistakes, and sometimes needs `continue` cycles to fix issues that a more experienced agent would have avoided. There is no feedback loop between completed runs and future runs.

Symptoms:
- Repeated `continue` cycles fixing the same class of errors (e.g., missing `__init__.py` import for a new model, forgetting `alembic upgrade head` after a migration, incorrect FastAPI response model shapes).
- Each new agent reads the same boilerplate from CLAUDE.md but has no awareness of what *actually* tripped up recent runs in this specific codebase.
- Lessons learned from debugging are lost when the container exits.

The issue asks for the process to "self improve" — capturing what the subagent pipeline learns from each run so future runs benefit from it.

## Requirements

1. **Global memory file** — A markdown file (`.archon/memory/codebase-patterns.md`) maintained in the repo. Contains categorized, concrete lessons learned from past runs: patterns that work, anti-patterns to avoid, and corrective actions for common failures.

2. **Per-area memory** — Supplementary memory files indexed by codebase area:
   - `.archon/memory/backend-patterns.md` — SQLAlchemy models, Alembic, FastAPI conventions
   - `.archon/memory/frontend-patterns.md` — React Query, TypeScript, component structure
   - `.archon/memory/dark-factory-ops.md` — infrastructure patterns (Docker, seed data, preview stack)

3. **Agent read injection** — Every command's Phase 1 (LOAD) reads the relevant memory files before exploring the codebase. Memory is loaded as passive context — the agent does not need to do anything special; the files are just read.

4. **Post-run memory update** — After each successful `validate` or `report` phase, the implement agent appends new learnings to the memory files. Learnings are extracted from: (a) the diff between the initial `$ARTIFACTS_DIR/plan.md` and what was actually committed, (b) any test failures encountered and how they were fixed, (c) patterns discovered during codebase exploration that were not in the existing memory.

5. **Memory format** — Each entry is a short, actionable bullet:
   - Category header (e.g., `## Backend: Models`)
   - Bullet per lesson: `- [PATTERN|AVOID|FIX] <concise, actionable sentence>`
   - Source tag: `<!-- issue:#N date:YYYY-MM-DD -->` (machine-readable, for deduplication)

6. **Deduplication** — Before appending, the agent checks whether a semantically equivalent lesson already exists (simple string match on the core sentence). No duplicates are added.

7. **Memory commit** — Memory updates are committed to the refine/feature branch alongside the implementation. The memory files live in `.archon/memory/` and are tracked in git, so they accumulate cross-run.

8. **Memory is advisory, not authoritative** — Agents are instructed to apply memory lessons as strong hints, not hard rules. Memory that conflicts with CLAUDE.md or ARCHITECTURE.md is ignored in favour of those documents.

9. **Refinement agent reads memory** — The `dark-factory-refine` and `dark-factory-plan` commands also read `.archon/memory/codebase-patterns.md` and relevant area files, so the spec and plan benefit from accumulated knowledge (e.g., knowing that a certain pattern is consistently problematic avoids specifying it).

10. **No external dependencies** — Memory is plain markdown files committed to the repo. No vector database, no embedding model, no additional services. Fully readable by humans and agents alike.

## Architecture

### Memory Store Layout

```
.archon/memory/
├── codebase-patterns.md       # Global lessons applicable to any change
├── backend-patterns.md        # Backend-specific (SQLAlchemy, FastAPI, Alembic, Celery)
├── frontend-patterns.md       # Frontend-specific (React Query, TypeScript, Tailwind)
└── dark-factory-ops.md        # Dark factory infrastructure (Docker, seed, preview, CI)
```

Each file starts with a header explaining the format, followed by categorized sections.

### Memory Entry Format

```markdown
## Backend: Models

- [PATTERN] When adding a new SQLAlchemy model: create the file in `backend/app/models/`, import it in `backend/app/models/__init__.py`, then run `alembic revision --autogenerate`. Missing the `__init__.py` import causes `Base.metadata.create_all` to skip the table silently. <!-- issue:#42 date:2026-05-15 -->

- [AVOID] Do not use `relationship()` without `lazy="selectin"` on models read via async sessions — sync lazy-loading raises `MissingGreenlet` in asyncpg. <!-- issue:#67 date:2026-05-22 -->

- [FIX] If `alembic revision --autogenerate` produces an empty migration, verify the model is imported in `__init__.py` and that `Base` is the same `DeclarativeBase` instance as in `database.py`. <!-- issue:#78 date:2026-05-28 -->
```

### Agent Integration Points

**Phase 1 additions to `dark-factory-implement.md`:**

```markdown
## Phase 1: LOAD (additions)

After reading CLAUDE.md and ARCHITECTURE.md:
5. Read `.archon/memory/codebase-patterns.md` — global lessons from past runs
6. If the issue touches backend code: read `.archon/memory/backend-patterns.md`
7. If the issue touches frontend code: read `.archon/memory/frontend-patterns.md`
8. If the issue touches Docker/infrastructure: read `.archon/memory/dark-factory-ops.md`

Apply these lessons as strong hints throughout implementation. If a lesson conflicts
with CLAUDE.md or ARCHITECTURE.md, follow those documents instead and note the conflict.
```

**Phase 5 additions to `dark-factory-implement.md` (post-implementation):**

```markdown
## Phase 5: MEMORY UPDATE

After writing the implementation summary to `$ARTIFACTS_DIR/implementation.md`:

1. Review the run: what patterns did you discover, what mistakes did you fix, what
   gotchas did you encounter?
2. For each insight that is not already in the memory files (check with a simple
   string search of the core sentence):
   a. Determine the appropriate memory file (global, backend, frontend, or ops)
   b. Determine the type: PATTERN (something that consistently works), AVOID (something
      that consistently fails), or FIX (a corrective action for a known failure mode)
   c. Write a concise, actionable one-sentence bullet with the source tag
      `<!-- issue:#$ISSUE_NUM date:$(date +%Y-%m-%d) -->`
   d. Append it under the appropriate category section in the correct memory file
3. If you added any memory entries, commit the updated memory files:
   `git commit -m "memory: lessons from issue #$ISSUE_NUM"`
4. If no new insights were gained (everything was already in memory), skip this phase.

Memory quality rules:
- Entries must be concrete and actionable, not generic advice
- Reference specific file paths, function names, or commands where relevant
- Prefer short, dense entries over long explanations
- Do NOT add observations that are already covered by CLAUDE.md
```

**Phase 1 additions to `dark-factory-refine.md` and `dark-factory-plan.md`:**

```markdown
After reading CLAUDE.md and ARCHITECTURE.md:
5. Read `.archon/memory/codebase-patterns.md` — global lessons
6. Read area-specific memory files relevant to the issue's domain
```

### Memory Bootstrapping

The initial memory files are created with a small seed of known lessons extracted from the existing codebase documentation and past issues (identified from the git log). The bootstrap content is hand-curated once and lives in the repo from the first commit. Future runs append to it organically.

Example bootstrap entries for `backend-patterns.md`:

```markdown
# Backend Patterns — Accumulated Lessons

This file is maintained automatically by the dark factory. Do not edit manually.

## Backend: Models

- [PATTERN] Every new SQLAlchemy model must be imported in `backend/app/models/__init__.py` or it will not be included in `Base.metadata` and alembic will not generate a migration for it. <!-- bootstrap date:2026-06-01 -->

- [AVOID] Never use synchronous SQLAlchemy patterns (`session.query()`, sync `relationship()` lazy loads) — the app uses `AsyncSession` throughout. All queries use `select()` + `await session.execute()`. <!-- bootstrap date:2026-06-01 -->

## Backend: API Routes

- [PATTERN] New routers must be registered in `backend/app/main.py` via `app.include_router(router, prefix="/api/v1/<resource>")`. The router file itself should not set a prefix — it lives in the `include_router` call. <!-- bootstrap date:2026-06-01 -->

- [PATTERN] The SlowAPI `limiter` instance is in `app/core/rate_limits.py`, not `app/main.py`. Import from `core.rate_limits` to avoid the circular import that would arise if the limiter were in `main.py`. <!-- bootstrap date:2026-06-01 -->

## Backend: Migrations

- [PATTERN] After any model change: `cd backend && python -m alembic revision --autogenerate -m "description" && python -m alembic upgrade head`. Never skip the `upgrade head` step — the preview stack applies migrations at startup, but the local test suite does not. <!-- bootstrap date:2026-06-01 -->
```

## Alternatives Considered

### A. PostgreSQL `agent_memory` table
Store memory as rows in a new `agent_memory` table with columns `(area, type, lesson, issue_num, created_at)`. Agents query via `psql` in Phase 1.

**Trade-off:** Requires a migration, a DB connection from the factory container during load, and extra infrastructure. Memory is not human-readable in the repo. More complex to bootstrap. Gains: structured queries (filter by area, type), timestamps. **Rejected** — the file-based approach is simpler, version-controlled, and readable by both agents and humans without any extra tooling.

### B. Redis cache for memory
Store memory as a Redis hash keyed by area. TTL-less entries persist across runs.

**Trade-off:** Not committed to the repo, so memory is lost if Redis is wiped. Not reviewable by humans. Not in git history. **Rejected** — memory should be durable and auditable.

### C. Vector-embedded memory with semantic search
Store lessons as embeddings; at load time, retrieve the top-K most similar lessons to the current issue.

**Trade-off:** Requires an embedding model (external API or self-hosted), adds latency, complex infrastructure. Semantic search is only useful at scale (thousands of entries); at the scale of this codebase (dozens to low hundreds of lessons), flat file reading is faster and more predictable. **Rejected** for now — could be revisited if the memory files grow unwieldy (> 200 entries).

### D. Lessons-in-CLAUDE.md
Append lessons directly to `CLAUDE.md` under a new `## Lessons Learned` section.

**Trade-off:** CLAUDE.md is the primary developer reference; polluting it with machine-generated observations would make it harder to maintain. Memory files are a cleaner separation. **Rejected**.

## Open Questions

- Should memory updates be committed to `main` directly (via PR from the refine branch), or only to the feature/refine branch and merged via the normal PR flow? Current approach: commit to the current branch; memory lands in `main` when the PR is merged. This means a lesson from issue #42 is only globally available after #42 merges. This is acceptable — memory accumulates gradually.

- Should the dark factory's validate phase also write memory (not just the implement phase)? Validate encounters test failures and fixes them — these are high-signal lessons. Future iteration.

## Assumptions

- Memory files are small enough (< 500 lines each) that reading them in full at agent load time does not meaningfully increase token consumption. At 500 lines of dense markdown, that is roughly 10K tokens — well within the context window.
- The `.archon/memory/` path does not conflict with existing Archon internals. Archon's own internal state lives in the Archon database, not in the project repo.
- Bootstrap entries are accurate enough to be immediately useful. They are derived from CLAUDE.md and the existing codebase patterns, so they should be.
- The agent is capable of reliably detecting whether an insight is already in memory via simple string matching. False negatives (duplicate entries added) are tolerated and can be cleaned up in a human review pass.
