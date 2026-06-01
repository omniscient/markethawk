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
   - Source tag: `<!-- issue:#N date:YYYY-MM-DD expires:YYYY-MM-DD source:implement|refine -->` (machine-readable, for deduplication and expiry)

6. **Deduplication** — Before appending, the agent checks whether a semantically equivalent lesson already exists (simple string match on the core sentence). No duplicates are added.

7. **Memory commit** — Memory updates are committed to the refine/feature branch alongside the implementation. The memory files live in `.archon/memory/` and are tracked in git, so they accumulate cross-run.

8. **Memory is advisory, not authoritative** — Agents are instructed to apply memory lessons as strong hints, not hard rules. Memory that conflicts with CLAUDE.md or ARCHITECTURE.md is ignored in favour of those documents.

9. **Refinement agent reads memory** — The `dark-factory-refine` and `dark-factory-plan` commands also read `.archon/memory/codebase-patterns.md` and relevant area files, so the spec and plan benefit from accumulated knowledge (e.g., knowing that a certain pattern is consistently problematic avoids specifying it).

10. **No external dependencies** — Memory is plain markdown files committed to the repo. No vector database, no embedding model, no additional services. Fully readable by humans and agents alike.

11. **Refine pipeline writes memory** — After committing the spec (Phase 5 of `dark-factory-refine.md`), the refine agent appends memory entries for: (a) architectural decisions from Q&A where a trade-off was explicitly weighed — written as PATTERN/AVOID pairs to `.archon/memory/architecture.md`; (b) codebase conventions discovered during Phase 3 context assembly that are absent from CLAUDE.md or ARCHITECTURE.md — written as PATTERN entries to the relevant area file. Raw codebase patterns that are already documented must not be duplicated. Entries are tagged `source:refine` to distinguish design-time observations from runtime-proven ones. Memory is committed before Phase 6 (publish) so it is persisted even if label commands fail.

12. **Memory expiry** — Every memory entry carries an `expires` field in its source tag. The default TTL is 6 months from the date of writing. Before appending any new entries in Phase 5 (both implement and refine), the agent reads the target memory file, drops all entries whose `expires` date is in the past, then appends new entries with a freshly computed `expires` date. A per-entry `ttl:Nd` override (e.g., `ttl:30d`) is supported for highly volatile patterns. Expiry is enforced by date comparison only — no git log queries, no path resolution, no semantic reasoning.

13. **Architect receives selective memory** — When the plan agent spawns the architect subagent, it conditionally appends one or two memory files whose area matches the files touched by the issue (determined from the spec's components list). It does not pass all memory files — unrelated area files add noise. The architect prompt gains a fifth check section ("Memory Patterns") instructing it to flag any plan step that violates an AVOID entry from the provided memory files. Backend-only issues receive `backend-patterns.md`; frontend-only issues receive `frontend-patterns.md`; cross-cutting issues receive both. `dark-factory-ops.md` is included when Docker or infrastructure files are touched.

## Architecture

### Memory Store Layout

```
.archon/memory/
├── codebase-patterns.md       # Global lessons applicable to any change
├── architecture.md            # Architectural decisions from Q&A (written by refine)
├── backend-patterns.md        # Backend-specific (SQLAlchemy, FastAPI, Alembic, Celery)
├── frontend-patterns.md       # Frontend-specific (React Query, TypeScript, Tailwind)
└── dark-factory-ops.md        # Dark factory infrastructure (Docker, seed, preview, CI)
```

Each file starts with a header explaining the format, followed by categorized sections.

### Memory Entry Format

```markdown
## Backend: Models

- [PATTERN] When adding a new SQLAlchemy model: create the file in `backend/app/models/`, import it in `backend/app/models/__init__.py`, then run `alembic revision --autogenerate`. Missing the `__init__.py` import causes `Base.metadata.create_all` to skip the table silently. <!-- issue:#42 date:2026-05-15 expires:2026-11-15 source:implement -->

- [AVOID] Do not use `relationship()` without `lazy="selectin"` on models read via async sessions — sync lazy-loading raises `MissingGreenlet` in asyncpg. <!-- issue:#67 date:2026-05-22 expires:2026-11-22 source:implement -->

- [FIX] If `alembic revision --autogenerate` produces an empty migration, verify the model is imported in `__init__.py` and that `Base` is the same `DeclarativeBase` instance as in `database.py`. <!-- issue:#78 date:2026-05-28 expires:2026-11-28 source:implement -->
```

### Agent Integration Points

**Phase 1 additions to `dark-factory-implement.md`:**

```markdown
## Phase 1: LOAD (additions)

After reading CLAUDE.md and ARCHITECTURE.md:
5. Read `.archon/memory/codebase-patterns.md` — global lessons from past runs
6. Read `.archon/memory/architecture.md` — prior architectural decisions (if it exists)
7. If the issue touches backend code: read `.archon/memory/backend-patterns.md`
8. If the issue touches frontend code: read `.archon/memory/frontend-patterns.md`
9. If the issue touches Docker/infrastructure: read `.archon/memory/dark-factory-ops.md`

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
      `<!-- issue:#$ISSUE_NUM date:$(date +%Y-%m-%d) expires:<date+6mo> source:implement -->`
      (For volatile patterns add `ttl:Nd` to shorten the window, e.g. `ttl:30d`)
   d. Before appending, run expiry cleanup: remove any existing entry in the file whose
      `expires` date is past today (see Memory Expiry Mechanism for pseudocode)
   e. Append the new entry under the appropriate category section in the correct memory file
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
6. Read `.archon/memory/architecture.md` — prior architectural decisions (written by refine)
7. Read area-specific memory files relevant to the issue's domain
```

**Architect subagent invocation (in `dark-factory-plan.md`):**

The plan agent already reads the spec's `Component` field to know which codebase areas are touched. Before spawning the architect subagent, it selects the relevant memory files:

```markdown
## Architect Memory Context (conditional)

Before spawning the architect subagent, build $MEMORY_CONTEXT:
- Always include: .archon/memory/architecture.md (if it exists)
- If spec touches backend (models/, routers/, services/, tasks/): include backend-patterns.md
- If spec touches frontend (frontend/src/): include frontend-patterns.md
- If spec touches Docker/infra (docker-compose, Dockerfile, dark-factory/): include dark-factory-ops.md

Pass $MEMORY_CONTEXT files as additional context in the architect subagent prompt:

  prompt: |
    <architect-prompt-content>

    ## Memory: Accumulated Patterns
    <contents of each selected memory file>

    ---
    <spec and plan content>
```

The architect subagent prompt gains a fifth check:

```markdown
### Section 5: Memory Patterns

For each AVOID or FIX entry in the provided memory files:
- Scan every plan step for actions that would trigger the anti-pattern
- If found: flag it as [MEMORY-VIOLATION] with the relevant memory entry quoted
- If no violations: note "No memory violations found"

This check runs after Section 4 (Codebase Conventions) and before the verdict.
```

**Why the architect gets selective (not all) memory files:** passing all files to a backend-only issue would include irrelevant frontend patterns, adding noise to the architect's context with no benefit. The plan agent already has the spec's component list and can resolve which files are relevant in O(1) — the complexity cost of selectivity is negligible.

### Memory Bootstrapping

The initial memory files are created with a small seed of known lessons extracted from the existing codebase documentation and past issues (identified from the git log). The bootstrap content is hand-curated once and lives in the repo from the first commit. Future runs append to it organically.

Example bootstrap entries for `backend-patterns.md`:

```markdown
# Backend Patterns — Accumulated Lessons

This file is maintained automatically by the dark factory. Do not edit manually.

## Backend: Models

- [PATTERN] Every new SQLAlchemy model must be imported in `backend/app/models/__init__.py` or it will not be included in `Base.metadata` and alembic will not generate a migration for it. <!-- bootstrap date:2026-06-01 expires:2026-12-01 source:implement -->

- [AVOID] Never use synchronous SQLAlchemy patterns (`session.query()`, sync `relationship()` lazy loads) — the app uses `AsyncSession` throughout. All queries use `select()` + `await session.execute()`. <!-- bootstrap date:2026-06-01 expires:2026-12-01 source:implement -->

## Backend: API Routes

- [PATTERN] New routers must be registered in `backend/app/main.py` via `app.include_router(router, prefix="/api/v1/<resource>")`. The router file itself should not set a prefix — it lives in the `include_router` call. <!-- bootstrap date:2026-06-01 expires:2026-12-01 source:implement -->

- [PATTERN] The SlowAPI `limiter` instance is in `app/core/rate_limits.py`, not `app/main.py`. Import from `core.rate_limits` to avoid the circular import that would arise if the limiter were in `main.py`. <!-- bootstrap date:2026-06-01 expires:2026-12-01 source:implement -->

## Backend: Migrations

- [PATTERN] After any model change: `cd backend && python -m alembic revision --autogenerate -m "description" && python -m alembic upgrade head`. Never skip the `upgrade head` step — the preview stack applies migrations at startup, but the local test suite does not. <!-- bootstrap date:2026-06-01 expires:2026-12-01 source:implement -->
```

### Memory Expiry Mechanism

Entries expire by date. Each source tag includes an `expires` field set to the write date plus the TTL. The default TTL is **6 months**. For volatile patterns (e.g., a third-party API quirk likely to change soon), a per-entry `ttl:Nd` override shortens the window.

**Updated entry format:**

```markdown
- [PATTERN] <actionable sentence> <!-- issue:#N date:YYYY-MM-DD expires:YYYY-MM-DD source:implement|refine [ttl:Nd] -->
```

**Cleanup pseudocode (runs at the start of Phase 5 before any appends):**

```python
today = date.today()
lines = memory_file.read_lines()
kept = []
for line in lines:
    match = re.search(r'expires:(\d{4}-\d{2}-\d{2})', line)
    if match and date.fromisoformat(match.group(1)) < today:
        continue  # drop expired entry
    kept.append(line)
memory_file.write_lines(kept)
```

This runs in both the implement and refine agents — expired entries are removed before new ones are appended. Because refine always runs before a new implement cycle on the same repo state, readers (refine, plan, architect) never encounter expired entries.

**Why not other approaches:**
- Path-based TTL (invalidate when a referenced file changes): brittle — files get moved or renamed, causing false-positive removals.
- Semantic self-review loop: non-deterministic, expensive, prone to false-stale markings.
- Git history-based: requires `git log` queries against file paths that may not be stable.

### Refinement Pipeline Memory Write

The refine agent writes memory **after the spec is committed (Phase 5 step 5) and before Phase 6 (publish)**. By this point all Q&A answers are settled and the chosen approach is locked. Writing at Phase 6 adds no new information and risks being skipped if the label command fails.

**What refine writes and where:**

| Source | Content | Target file |
|--------|---------|-------------|
| Q&A architectural decisions | Trade-offs explicitly weighed (why approach X over Y) | `.archon/memory/architecture.md` |
| Phase 3 context assembly | Codebase conventions not already in CLAUDE.md or ARCHITECTURE.md | Area-specific file (e.g., `backend-patterns.md`) |

Refine does NOT write to `lessons-learned.md` (belongs to implement post-execution) or `avoid.md` (belongs to runtime mistakes, not design-time decisions).

**Concrete Phase 5 addition for `dark-factory-refine.md`** (after spec commit, before Phase 6):

```markdown
6. Append memory entries to .archon/memory/:
   a. Run expiry cleanup on each target file (see Memory Expiry Mechanism).
   b. For each architectural decision made in Q&A: append to architecture.md
      - [PATTERN] <decision> <!-- issue:#$ISSUE_NUM date:$(date +%Y-%m-%d) expires:<+6mo> source:refine -->
      - [AVOID] <rejected approach and why> <!-- issue:#$ISSUE_NUM date:$(date +%Y-%m-%d) expires:<+6mo> source:refine -->
   c. For any codebase convention discovered in Phase 3 not already in CLAUDE.md or ARCHITECTURE.md:
      append to the relevant area file as a PATTERN entry with source:refine.
   d. Commit: git commit -m "memory: lessons from refine #$ISSUE_NUM"
```

The `source:refine` tag signals to future agents that these entries carry design-time weight, not empirical/runtime proof. Implement agents may treat `source:implement` entries as higher-confidence than `source:refine` entries when the two conflict.

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
- A 6-month TTL is a reasonable half-life for scanner heuristics and implementation patterns. Domain rules that remain valid will be re-learned and re-written with a fresh expiry when a related issue runs through the pipeline. Highly volatile patterns can opt into a shorter TTL via the `ttl:Nd` override.
- The refine agent's `source:refine` entries carry design-time (not empirical) weight. Implement agents encountering a conflict between a `source:refine` entry and their runtime observations should prefer the runtime observation and update the entry.
- The plan agent can reliably identify which codebase areas an issue touches by reading the spec's `Component` field. This is sufficient for selecting which memory files to pass to the architect subagent.
- The architect subagent prompt at `/opt/refinement-skills/architect-prompt.md` can be extended with a fifth "Memory Patterns" check section without disrupting existing checks — the check is additive and runs after Section 4.
