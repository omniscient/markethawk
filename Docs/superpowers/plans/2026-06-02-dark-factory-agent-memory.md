# Dark Factory — Agent Memory Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

## Goal

Dark factory subagents currently start every run with zero institutional knowledge, repeatedly re-discovering the same codebase patterns and making the same avoidable mistakes. This plan implements a file-based, repo-committed memory store — five markdown files in `.archon/memory/` — that the implement, refine, and plan agents read at load time, write to after each run, and that the architect subagent uses to flag plan steps that violate accumulated AVOID entries. Success means a completed run leaves at least one committed memory entry on the branch and a future run on a related issue demonstrably benefits from that entry without needing a `continue` cycle to fix a known class of error.

## Architecture

**What changes:**
- 5 new markdown files created in `.archon/memory/` (bootstrapped with seed lessons)
- 3 command files edited: `.archon/commands/dark-factory-implement.md`, `.archon/commands/dark-factory-refine.md`, `.archon/commands/dark-factory-plan.md`
- 1 architect prompt file edited: `.claude/skills/refinement/architect-prompt.md`

**What does NOT change:** no DB migrations, no new Docker services, no Python code, no TypeScript code, no `docker-compose.yml`, no `CLAUDE.md` sections (memory is a separate concern from developer-facing docs).

## Tech Stack

Markdown / Git / Bash only. All memory files are plain `.md` committed to the repo. No vector database, no embedding model, no external services.

## File Structure

| File | Status | Purpose |
|------|--------|---------|
| `.archon/memory/codebase-patterns.md` | NEW | Global lessons applicable to any change — commit workflow, model checklist, frontend type-check |
| `.archon/memory/architecture.md` | NEW | Architectural decisions from Q&A written by the refine agent (PATTERN+AVOID pairs) |
| `.archon/memory/backend-patterns.md` | NEW | SQLAlchemy models, Alembic, FastAPI routers, rate limiter import, async session rules |
| `.archon/memory/frontend-patterns.md` | NEW | React Query conventions, TypeScript no-any, component vs page split, Tailwind-only, routing |
| `.archon/memory/dark-factory-ops.md` | NEW | Preview port formula, container root, seed file naming, ENV_VARIABLES.md requirement |
| `.archon/commands/dark-factory-implement.md` | MODIFY | Add Phase 1 memory reads (steps 5-9) and new Phase 5 MEMORY UPDATE; rename old Phase 5 to Phase 6 |
| `.archon/commands/dark-factory-refine.md` | MODIFY | Add Phase 1 memory reads (steps 7-9) and Phase 5 step 6 memory write |
| `.archon/commands/dark-factory-plan.md` | MODIFY | Add Phase 1 memory reads (steps 6-8) and Phase 3 $MEMORY_CONTEXT build before architect spawn |
| `.claude/skills/refinement/architect-prompt.md` | MODIFY | Insert new Section 5 "Memory Patterns"; renumber old Section 5 to Section 6 |

---

## TASKS

---

### Task 1: Bootstrap `.archon/memory/` directory with seed lessons

**Files:**
- Create: `.archon/memory/codebase-patterns.md`
- Create: `.archon/memory/architecture.md`
- Create: `.archon/memory/backend-patterns.md`
- Create: `.archon/memory/frontend-patterns.md`
- Create: `.archon/memory/dark-factory-ops.md`

- [ ] **Step 1: VERIFY BEFORE — confirm the directory does not yet exist**

```bash
ls /workspace/markethawk/.archon/memory 2>/dev/null && echo PRESENT || echo ABSENT
```

Expected output: `ABSENT` (or an error listing no such directory).

- [ ] **Step 2: IMPLEMENT — create the directory and write all five files**

```bash
mkdir -p /workspace/markethawk/.archon/memory
```

Write `.archon/memory/codebase-patterns.md`:

```markdown
# Codebase Patterns — Accumulated Lessons

This file is maintained automatically by the dark factory implement agent. Do not edit manually.
Entries are advisory. If an entry conflicts with CLAUDE.md or ARCHITECTURE.md, follow those documents.

## Commit Workflow

- [PATTERN] Before committing backend changes: confirm the backend reloaded (`docker-compose logs backend --tail=10`), then hit new/changed endpoints with `curl` to verify correct responses. Only then commit. <!-- bootstrap date:2026-06-02 expires:2026-12-02 source:implement -->

- [PATTERN] Before committing frontend changes: run `cd frontend && npx tsc --noEmit` and confirm zero type errors. For UI behaviour changes also verify in the browser. <!-- bootstrap date:2026-06-02 expires:2026-12-02 source:implement -->

## New Model Checklist

- [PATTERN] When adding a SQLAlchemy model: (1) create the file in `backend/app/models/`, (2) import and add it to `backend/app/models/__init__.py`, (3) run `python -m alembic revision --autogenerate -m "description"`, (4) run `python -m alembic upgrade head`. Skipping any step silently breaks the schema or migration. <!-- bootstrap date:2026-06-02 expires:2026-12-02 source:implement -->

## Frontend Type Safety

- [PATTERN] Run `cd frontend && npx tsc --noEmit` after every frontend change before staging the commit. A clean tsc output is required — CI will reject type errors. <!-- bootstrap date:2026-06-02 expires:2026-12-02 source:implement -->
```

Write `.archon/memory/architecture.md`:

```markdown
# Architecture Decisions — Accumulated Lessons

This file is maintained automatically by the dark factory refine agent. Do not edit manually.
Entries represent design-time decisions (source:refine). Implement agents may treat source:implement
entries as higher-confidence than source:refine entries when the two conflict.

## State Storage

- [PATTERN] Use PostgreSQL for all durable application state — scanner events, memory, configs. The existing `AsyncSession` infrastructure handles connection pooling, migrations, and transactional safety. <!-- bootstrap date:2026-06-02 expires:2026-12-02 source:refine -->

- [AVOID] Do not introduce Redis for durable state — Redis is volatile (data lost on flush/restart) and not committed to git history. Reserve Redis for ephemeral queues and rate-limit counters only. <!-- bootstrap date:2026-06-02 expires:2026-12-02 source:refine -->

## Services Topology

- [PATTERN] Extend existing services rather than adding new Docker containers. The stack already runs postgres, redis, backend, frontend, celery-worker, celery-beat, seq, prometheus, grafana, and jaeger. Each new service adds operational overhead and a new port to document. <!-- bootstrap date:2026-06-02 expires:2026-12-02 source:refine -->

- [AVOID] Do not introduce a vector database, embedding model, or semantic search service for memory retrieval. At the scale of this codebase (< 200 memory entries) flat file reading is faster and more predictable than a retrieval pipeline. <!-- bootstrap date:2026-06-02 expires:2026-12-02 source:refine -->

## Agent Memory Design (issue #149)

- [PATTERN] Agent memory is stored as plain markdown files in `.archon/memory/`, committed to the repo. Files are read at Phase 1 load time and updated post-run. This keeps memory human-readable, version-controlled, and accessible to all agents without any extra tooling. <!-- bootstrap date:2026-06-02 expires:2026-12-02 source:refine -->

- [AVOID] Do not store agent memory in CLAUDE.md — that file is the primary developer reference and polluting it with machine-generated observations makes it harder to maintain. Memory files are the designated separation. <!-- bootstrap date:2026-06-02 expires:2026-12-02 source:refine -->
```

Write `.archon/memory/backend-patterns.md`:

```markdown
# Backend Patterns — Accumulated Lessons

This file is maintained automatically by the dark factory implement agent. Do not edit manually.
Entries are advisory. If an entry conflicts with CLAUDE.md or ARCHITECTURE.md, follow those documents.

## Backend: Models

- [PATTERN] Every new SQLAlchemy model must be imported in `backend/app/models/__init__.py` or it will not be included in `Base.metadata` and alembic will not generate a migration for it. <!-- bootstrap date:2026-06-02 expires:2026-12-02 source:implement -->

- [AVOID] Never use synchronous SQLAlchemy patterns (`session.query()`, sync `relationship()` lazy loads) — the app uses `AsyncSession` throughout. All queries use `select()` + `await session.execute()`. Sync lazy-loading raises `MissingGreenlet` in asyncpg. <!-- bootstrap date:2026-06-02 expires:2026-12-02 source:implement -->

## Backend: API Routes

- [PATTERN] New routers must be registered in `backend/app/main.py` via `app.include_router(router, prefix="/api/v1/<resource>")`. The router file itself should not set a prefix — it lives in the `include_router` call. <!-- bootstrap date:2026-06-02 expires:2026-12-02 source:implement -->

- [PATTERN] The SlowAPI `limiter` instance is in `app/core/rate_limits.py`, not `app/main.py`. Import from `core.rate_limits` to avoid the circular import that would arise if the limiter were in `main.py`. <!-- bootstrap date:2026-06-02 expires:2026-12-02 source:implement -->

## Backend: Migrations

- [PATTERN] After any model change: `cd backend && python -m alembic revision --autogenerate -m "description" && python -m alembic upgrade head`. Never skip the `upgrade head` step — the preview stack applies migrations at startup, but the local test suite does not. <!-- bootstrap date:2026-06-02 expires:2026-12-02 source:implement -->

- [FIX] If `alembic revision --autogenerate` produces an empty migration (no `op.` calls in the body), verify that the model is imported in `backend/app/models/__init__.py` and that `Base` is the same `DeclarativeBase` instance as in `backend/app/core/database.py`. <!-- bootstrap date:2026-06-02 expires:2026-12-02 source:implement -->
```

Write `.archon/memory/frontend-patterns.md`:

```markdown
# Frontend Patterns — Accumulated Lessons

This file is maintained automatically by the dark factory implement agent. Do not edit manually.
Entries are advisory. If an entry conflicts with CLAUDE.md or ARCHITECTURE.md, follow those documents.

## Frontend: Data Fetching

- [PATTERN] Use React Query (`useQuery` / `useMutation`) for all server state — never `useState` + `useEffect` + `fetch`. The existing query client is configured in `frontend/src/main.tsx`. <!-- bootstrap date:2026-06-02 expires:2026-12-02 source:implement -->

- [PATTERN] Query keys follow the format `['resource', id?]` — e.g. `['scanner-results']`, `['stock', ticker]`. Keep keys consistent across the file so React Query can cache and invalidate correctly. <!-- bootstrap date:2026-06-02 expires:2026-12-02 source:implement -->

## Frontend: TypeScript

- [AVOID] Do not use `any` in TypeScript — it defeats type-checking and will cause `tsc --noEmit` to fail in strict mode. Prefer `unknown` with narrowing, or derive types from the API response schema in `frontend/src/api/`. <!-- bootstrap date:2026-06-02 expires:2026-12-02 source:implement -->

- [PATTERN] Reuse API response types defined in `frontend/src/api/*.ts` rather than re-declaring interfaces in components. Type imports keep the schema as the single source of truth. <!-- bootstrap date:2026-06-02 expires:2026-12-02 source:implement -->

## Frontend: Component Structure

- [PATTERN] Pages (route-level views) live in `frontend/src/pages/`. Reusable UI pieces live in `frontend/src/components/`. A component that is only used by one page can live in a `components/` subdirectory named after the page. <!-- bootstrap date:2026-06-02 expires:2026-12-02 source:implement -->

- [PATTERN] Styling is Tailwind CSS utility classes only — no custom CSS files, no inline `style` objects. If a design requires a custom class, add it to `tailwind.config.js` as a theme extension. <!-- bootstrap date:2026-06-02 expires:2026-12-02 source:implement -->

## Frontend: Routing

- [PATTERN] New routes are registered in `frontend/src/App.tsx` using React Router `<Route>` elements. Match the existing pattern of lazy-loaded page components (`React.lazy` + `Suspense`). <!-- bootstrap date:2026-06-02 expires:2026-12-02 source:implement -->
```

Write `.archon/memory/dark-factory-ops.md`:

```markdown
# Dark Factory Ops — Accumulated Lessons

This file is maintained automatically by the dark factory implement agent. Do not edit manually.
Entries are advisory. If an entry conflicts with CLAUDE.md or ARCHITECTURE.md, follow those documents.

## Preview Stack

- [PATTERN] Preview ports follow the formula `1{ISSUE_NUM_PADDED}XX` where `ISSUE_NUM_PADDED` is zero-padded to two digits and XX is the service suffix (33=frontend, 80=backend, 54=postgres, 63=redis). Example: issue #3 → frontend `:10333`, backend `:10380`. <!-- bootstrap date:2026-06-02 expires:2026-12-02 source:implement -->

## Container Root and Mounts

- [PATTERN] The dark factory container runs as the `factory` user (uid 1000) with `/workspace` as the working directory. The repo is cloned to `/workspace/markethawk`. Paths inside the container that start with `/opt/` (e.g. `/opt/refinement-skills/`) are read-only mounts from the host and are not git-tracked by the cloned repo. <!-- bootstrap date:2026-06-02 expires:2026-12-02 source:implement -->

## Seed Files

- [PATTERN] Seed files in `dark-factory/seed/seed/` are named with a two-digit prefix (`00_`, `01_`, ...) so they apply in deterministic order. The next available slot for a new baseline module is determined by `ls dark-factory/seed/seed/ | sort | tail -1`. <!-- bootstrap date:2026-06-02 expires:2026-12-02 source:implement -->

- [AVOID] Do not embed data directly in Alembic migration files — migrations are schema-only. Feature-specific seed data goes in `dark-factory/seed/99_feature.sql` (idempotent, `ON CONFLICT DO NOTHING`). Data needed across multiple features goes in a new numbered baseline module. <!-- bootstrap date:2026-06-02 expires:2026-12-02 source:implement -->

## Environment and Credentials

- [PATTERN] Every new environment variable introduced by a feature must be documented in `ENV_VARIABLES.md` with its default value and a one-line description. CLAUDE.md references ENV_VARIABLES.md as the authoritative env var reference. <!-- bootstrap date:2026-06-02 expires:2026-12-02 source:implement -->

- [PATTERN] AI credentials (`CLAUDE_CODE_OAUTH_TOKEN` or `ANTHROPIC_API_KEY`) and `GH_TOKEN` belong in `.archon/.env`, not in `.env`. The `.archon/.env` file is gitignored to keep secrets out of the repo. <!-- bootstrap date:2026-06-02 expires:2026-12-02 source:implement -->
```

- [ ] **Step 3: VERIFY AFTER — confirm all five files exist**

```bash
ls /workspace/markethawk/.archon/memory/
```

Expected output:
```
architecture.md
backend-patterns.md
codebase-patterns.md
dark-factory-ops.md
frontend-patterns.md
```

- [ ] **Step 4: COMMIT**

```bash
cd /workspace/markethawk
git add .archon/memory/
git commit -m "$(cat <<'EOF'
feat: bootstrap .archon/memory/ with seed lessons for agent self-improvement

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: Update `dark-factory-implement.md` Phase 1 — memory reads

**Files:**
- Modify: `.archon/commands/dark-factory-implement.md`

- [ ] **Step 1: VERIFY BEFORE — confirm memory reads are not yet present**

```bash
grep -q "archon/memory" /workspace/markethawk/.archon/commands/dark-factory-implement.md && echo PRESENT || echo ABSENT
```

Expected output: `ABSENT`

- [ ] **Step 2: IMPLEMENT — convert Phase 1 bullets to numbered items and insert steps 5-9**

The existing Phase 1 uses three unnumbered bullet points. First convert them (and add ARCHITECTURE.md as step 4) to a numbered list, then append steps 5-9. This ensures the inserted memory-read steps have a coherent sequence rather than a gap where items 1-4 are missing.

In `.archon/commands/dark-factory-implement.md`, locate the entire Phase 1 LOAD block:

```
## Phase 1: LOAD

Read the project rules:
- Read `CLAUDE.md` for all development rules, architecture, and validation requirements.
- The issue context has been fetched by the workflow. It is available in the conversation.
- **Check the `intent` field** in the issue context: `"new"` or `"continue"`.
```

Replace it with:

```
## Phase 1: LOAD

Read the project rules:
1. Read `CLAUDE.md` for all development rules, architecture, and validation requirements.
2. Read `ARCHITECTURE.md` for service topology and module map.
3. The issue context has been fetched by the workflow. It is available in the conversation.
4. **Check the `intent` field** in the issue context: `"new"` or `"continue"`.
5. Read `.archon/memory/codebase-patterns.md` — global lessons from past runs.
6. Read `.archon/memory/architecture.md` — prior architectural decisions (if the file exists).
7. If the issue touches backend code (`backend/app/models/`, `routers/`, `services/`, `tasks/`): read `.archon/memory/backend-patterns.md`.
8. If the issue touches frontend code (`frontend/src/`): read `.archon/memory/frontend-patterns.md`.
9. If the issue touches Docker or infrastructure files (`docker-compose`, `Dockerfile`, `dark-factory/`): read `.archon/memory/dark-factory-ops.md`.

Apply these lessons as strong hints throughout implementation. If a lesson conflicts with `CLAUDE.md` or `ARCHITECTURE.md`, follow those documents instead and note the conflict in `$ARTIFACTS_DIR/implementation.md`.
```

- [ ] **Step 3: VERIFY AFTER — confirm five memory references are present**

```bash
grep -c "archon/memory" /workspace/markethawk/.archon/commands/dark-factory-implement.md
```

Expected output: `5`

- [ ] **Step 4: COMMIT**

```bash
cd /workspace/markethawk
git add .archon/commands/dark-factory-implement.md
git commit -m "$(cat <<'EOF'
feat(implement): Phase 1 reads .archon/memory/ files at load time

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: Update `dark-factory-implement.md` — add Phase 5 MEMORY UPDATE, rename REPORT to Phase 6

**Files:**
- Modify: `.archon/commands/dark-factory-implement.md`

- [ ] **Step 1: VERIFY BEFORE — confirm Phase 5 is currently REPORT**

```bash
grep "Phase 5" /workspace/markethawk/.archon/commands/dark-factory-implement.md
```

Expected output contains: `Phase 5: REPORT`

- [ ] **Step 2: IMPLEMENT — rename Phase 5 to Phase 6 and insert new Phase 5 MEMORY UPDATE**

In `.archon/commands/dark-factory-implement.md`, locate the current Phase 5 heading:

```
## Phase 5: REPORT
```

Replace **only the heading line** with the following block. The existing body content that follows `## Phase 5: REPORT` (the "Write a summary…" bullet points) is NOT touched — it automatically becomes the body of the renamed `## Phase 6: REPORT` heading that ends the replacement block.

Replace it with:

```
## Phase 5: MEMORY UPDATE

After Phase 4 DOCUMENT completes. Note on execution order: `$ARTIFACTS_DIR/implementation.md` is written during the Phase 3 IMPLEMENT checkpoint; Phase 4 DOCUMENT reads it; Phase 6 REPORT finalizes it. Phase 5 MEMORY UPDATE runs after Phase 4 and does not depend on Phase 6.

1. Review the run: what patterns did you discover, what mistakes did you fix, what gotchas did you encounter that are not already in the memory files?

2. Before appending any new entries, run expiry cleanup on the target memory file:
   - Read the file line by line.
   - For each line matching `expires:(\d{4}-\d{2}-\d{2})`, parse the date.
   - If the parsed date is strictly before today (`date +%Y-%m-%d`), drop the line.
   - Write the remaining lines back to the file.
   This runs with a simple shell loop — no Python required:
   ```bash
   TODAY=$(date +%Y-%m-%d)
   TARGET=".archon/memory/backend-patterns.md"  # replace with the actual target file
   awk -v today="$TODAY" '
     /expires:[0-9]{4}-[0-9]{2}-[0-9]{2}/ {
       match($0, /expires:([0-9]{4}-[0-9]{2}-[0-9]{2})/, arr)
       if (arr[1] < today) next
     }
     { print }
   ' "$TARGET" > "$TARGET.tmp" && mv "$TARGET.tmp" "$TARGET"
   ```

3. For each insight that is not already in the memory files (check with `grep -F "<core sentence>" .archon/memory/*.md`):
   a. Determine the appropriate memory file:
      - Global workflow or checklist lesson → `.archon/memory/codebase-patterns.md`
      - SQLAlchemy, Alembic, FastAPI, Celery → `.archon/memory/backend-patterns.md`
      - React Query, TypeScript, components, Tailwind → `.archon/memory/frontend-patterns.md`
      - Docker, preview stack, seed data, env vars → `.archon/memory/dark-factory-ops.md`
   b. Determine the entry type:
      - `[PATTERN]` — something that consistently works and should be repeated
      - `[AVOID]` — something that consistently fails or causes bugs
      - `[FIX]` — a corrective action for a known failure mode
   c. Write a concise, actionable one-sentence bullet under the appropriate category section:
      ```
      - [PATTERN|AVOID|FIX] <concise actionable sentence referencing specific paths, commands, or names where relevant> <!-- issue:#$ISSUE_NUM date:$(date +%Y-%m-%d) expires:$(date -d '+6 months' +%Y-%m-%d 2>/dev/null || date -v+6m +%Y-%m-%d) source:implement -->
      ```
      For volatile patterns (e.g., a third-party API quirk expected to change soon), shorten the window by appending `ttl:30d` before the closing `-->`.

4. If you added any memory entries, commit the updated memory files:
   ```bash
   git add .archon/memory/
   git commit -m "memory: lessons from issue #$ISSUE_NUM"
   ```

5. If no new insights were gained (everything was already in memory or the run produced no novel observations), skip the commit — do not create an empty commit.

**Memory quality rules:**
- Entries must be concrete and actionable, not generic advice ("always write good code" is not an entry).
- Reference specific file paths, function names, or CLI commands where relevant.
- Prefer short, dense entries over long explanations — one sentence per bullet.
- Do NOT add observations already covered by `CLAUDE.md` or `ARCHITECTURE.md`.
- Do NOT add entries to `architecture.md` from the implement agent — that file is written by the refine agent only.

## Phase 6: REPORT
```

- [ ] **Step 3: VERIFY AFTER — confirm both Phase 5 and Phase 6 are present**

```bash
grep "Phase [56]" /workspace/markethawk/.archon/commands/dark-factory-implement.md
```

Expected output contains both:
```
## Phase 5: MEMORY UPDATE
## Phase 6: REPORT
```

- [ ] **Step 4: COMMIT**

```bash
cd /workspace/markethawk
git add .archon/commands/dark-factory-implement.md
git commit -m "$(cat <<'EOF'
feat(implement): Phase 5 MEMORY UPDATE — extract and commit lessons post-run

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: Update `dark-factory-refine.md` Phase 1 — memory reads

**Files:**
- Modify: `.archon/commands/dark-factory-refine.md`

- [ ] **Step 1: VERIFY BEFORE — confirm memory reads are not yet present**

```bash
grep -q "archon/memory" /workspace/markethawk/.archon/commands/dark-factory-refine.md && echo PRESENT || echo ABSENT
```

Expected output: `ABSENT`

- [ ] **Step 2: IMPLEMENT — insert steps 7-9 after the existing step 6**

In `.archon/commands/dark-factory-refine.md`, locate the existing step 6:

```
6. Read `/opt/refinement-skills/config.yaml` for pipeline configuration
```

Replace it with:

```
6. Read `/opt/refinement-skills/config.yaml` for pipeline configuration
7. Read `.archon/memory/codebase-patterns.md` — global lessons from past runs.
8. Read `.archon/memory/architecture.md` — prior architectural decisions written by previous refine runs (if the file exists).
9. Read area-specific memory files relevant to the issue's domain: if the issue touches backend code read `.archon/memory/backend-patterns.md`; if it touches frontend code read `.archon/memory/frontend-patterns.md`; if it touches Docker or infrastructure read `.archon/memory/dark-factory-ops.md`.

`AVOID` entries are especially relevant to spec decisions — if a memory entry marks an approach as AVOID, do not specify that approach in the spec without an explicit justification.
```

- [ ] **Step 3: VERIFY AFTER — confirm at least three memory references are present**

```bash
grep -c "archon/memory" /workspace/markethawk/.archon/commands/dark-factory-refine.md
```

Expected output: `3` or higher.

- [ ] **Step 4: COMMIT**

```bash
cd /workspace/markethawk
git add .archon/commands/dark-factory-refine.md
git commit -m "$(cat <<'EOF'
feat(refine): Phase 1 reads .archon/memory/ files at load time

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: Update `dark-factory-refine.md` Phase 5 — memory write after spec commit

**Files:**
- Modify: `.archon/commands/dark-factory-refine.md`

- [ ] **Step 1: VERIFY BEFORE — confirm Phase 5 does not yet contain memory logic**

```bash
grep -A 40 "Phase 5" /workspace/markethawk/.archon/commands/dark-factory-refine.md | grep -q "archon/memory" && echo PRESENT || echo ABSENT
```

Expected output: `ABSENT`

- [ ] **Step 2: IMPLEMENT — insert step 6 into Phase 5, between the spec commit (step 5) and Phase 6**

In `.archon/commands/dark-factory-refine.md`, locate the existing step 5 in Phase 5:

```
5. Commit the spec
```

Replace it with:

```
5. Commit the spec

6. Append memory entries to `.archon/memory/`:

   **Expiry cleanup (run before appending to any file):**
   For each target memory file you are about to write, remove expired entries first:
   ```bash
   TODAY=$(date +%Y-%m-%d)
   TARGET=".archon/memory/architecture.md"  # replace with actual target file
   awk -v today="$TODAY" '
     /expires:[0-9]{4}-[0-9]{2}-[0-9]{2}/ {
       match($0, /expires:([0-9]{4}-[0-9]{2}-[0-9]{2})/, arr)
       if (arr[1] < today) next
     }
     { print }
   ' "$TARGET" > "$TARGET.tmp" && mv "$TARGET.tmp" "$TARGET"
   ```

   **What to write and where:**

   a. For each architectural decision made during Phase 4 Q&A where a trade-off was explicitly weighed (why approach X over approach Y): append a PATTERN+AVOID pair to `.archon/memory/architecture.md`:
      ```
      - [PATTERN] <the chosen approach and why it is correct> <!-- issue:#$ISSUE_NUM date:$(date +%Y-%m-%d) expires:$(date -d '+6 months' +%Y-%m-%d 2>/dev/null || date -v+6m +%Y-%m-%d) source:refine -->
      - [AVOID] <the rejected approach and the concrete reason it was rejected> <!-- issue:#$ISSUE_NUM date:$(date +%Y-%m-%d) expires:$(date -d '+6 months' +%Y-%m-%d 2>/dev/null || date -v+6m +%Y-%m-%d) source:refine -->
      ```

   b. For any codebase convention discovered during Phase 3 context assembly that is absent from `CLAUDE.md` and absent from `ARCHITECTURE.md`: append a `[PATTERN]` entry to the relevant area file (`backend-patterns.md`, `frontend-patterns.md`, or `dark-factory-ops.md`) with `source:refine`.

   c. Before appending any entry, check for duplicates: `grep -F "<core sentence of the new entry>" .archon/memory/architecture.md`. If a matching line exists, skip that entry.

   d. Do NOT write to `codebase-patterns.md` from the refine agent — that file is maintained by the implement agent for runtime-proven lessons only.

   e. If any entries were added, commit:
      ```bash
      git add .archon/memory/
      git commit -m "memory: architectural decisions from refine #$ISSUE_NUM"
      ```
      If no entries were added (Q&A produced no novel trade-offs and Phase 3 found nothing new), skip the commit.
```

- [ ] **Step 3: VERIFY AFTER — confirm at least six memory references are now present**

```bash
grep -c "archon/memory" /workspace/markethawk/.archon/commands/dark-factory-refine.md
```

Expected output: `6` or higher.

- [ ] **Step 4: COMMIT**

```bash
cd /workspace/markethawk
git add .archon/commands/dark-factory-refine.md
git commit -m "$(cat <<'EOF'
feat(refine): Phase 5 writes architectural decisions to .archon/memory/architecture.md

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

### Task 6: Update `dark-factory-plan.md` Phase 1 — memory reads

**Files:**
- Modify: `.archon/commands/dark-factory-plan.md`

- [ ] **Step 1: VERIFY BEFORE — confirm memory reads are not yet present**

```bash
grep -q "archon/memory" /workspace/markethawk/.archon/commands/dark-factory-plan.md && echo PRESENT || echo ABSENT
```

Expected output: `ABSENT`

- [ ] **Step 2: IMPLEMENT — insert steps 6-8 after the existing step 5**

In `.archon/commands/dark-factory-plan.md`, locate the existing step 5:

```
5. Read the spec file
```

Replace it with:

```
5. Read the spec file
6. Read `.archon/memory/codebase-patterns.md` — global lessons applicable to any change.
7. Read `.archon/memory/architecture.md` — prior architectural decisions (if the file exists). If a memory entry marks an approach as AVOID, do not plan steps that use that approach.
8. Read area-specific memory files based on the spec's `Component` field:
   - Component touches `backend/app/models/`, `routers/`, `services/`, or `tasks/` → read `.archon/memory/backend-patterns.md`
   - Component touches `frontend/src/` → read `.archon/memory/frontend-patterns.md`
   - Component touches `docker-compose`, `Dockerfile`, or `dark-factory/` → read `.archon/memory/dark-factory-ops.md`

Bake relevant memory lessons directly into the plan task steps — do not leave them as a separate advisory section. For example, if `backend-patterns.md` contains a `[PATTERN]` about the `__init__.py` import requirement, the plan's "add model" task must explicitly include an `__init__.py` import step.
```

- [ ] **Step 3: VERIFY AFTER — confirm at least four memory references are present**

```bash
grep -c "archon/memory" /workspace/markethawk/.archon/commands/dark-factory-plan.md
```

Expected output: `4` or higher.

- [ ] **Step 4: COMMIT**

```bash
cd /workspace/markethawk
git add .archon/commands/dark-factory-plan.md
git commit -m "$(cat <<'EOF'
feat(plan): Phase 1 reads .archon/memory/ files at load time

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

### Task 7: Update `dark-factory-plan.md` Phase 3 — pass selective memory context to architect subagent

**Files:**
- Modify: `.archon/commands/dark-factory-plan.md`

- [ ] **Step 1: VERIFY BEFORE — confirm MEMORY_CONTEXT is not yet present**

```bash
grep -q "MEMORY_CONTEXT" /workspace/markethawk/.archon/commands/dark-factory-plan.md && echo PRESENT || echo ABSENT
```

Expected output: `ABSENT`

- [ ] **Step 2: IMPLEMENT — insert the $MEMORY_CONTEXT build block before the "Spawn an architect subagent" line**

In `.archon/commands/dark-factory-plan.md`, locate the existing Phase 3 start:

```
## Phase 3: ARCHITECT REVIEW

Spawn an architect subagent using the Agent tool:
```

Replace it with:

```
## Phase 3: ARCHITECT REVIEW

Before spawning the architect subagent, build `$MEMORY_CONTEXT` by selecting the memory files whose area matches the spec's `Component` field:

```bash
MEMORY_CONTEXT=""

# architecture.md is always included if it exists
if [ -f ".archon/memory/architecture.md" ]; then
  MEMORY_CONTEXT="$MEMORY_CONTEXT\n\n### From .archon/memory/architecture.md\n$(cat .archon/memory/architecture.md)"
fi

# Backend area — extract the Component field from the spec file header
SPEC_COMPONENT=$(grep -m1 '^\*\*Component' "$SPEC_FILE" | sed 's/.*: //')
if echo "$SPEC_COMPONENT" | grep -qE "models/|routers/|services/|tasks/"; then
  MEMORY_CONTEXT="$MEMORY_CONTEXT\n\n### From .archon/memory/backend-patterns.md\n$(cat .archon/memory/backend-patterns.md)"
fi

# Frontend area
if echo "$SPEC_COMPONENT" | grep -q "frontend/src/"; then
  MEMORY_CONTEXT="$MEMORY_CONTEXT\n\n### From .archon/memory/frontend-patterns.md\n$(cat .archon/memory/frontend-patterns.md)"
fi

# Docker / infrastructure area
if echo "$SPEC_COMPONENT" | grep -qE "docker-compose|Dockerfile|dark-factory/"; then
  MEMORY_CONTEXT="$MEMORY_CONTEXT\n\n### From .archon/memory/dark-factory-ops.md\n$(cat .archon/memory/dark-factory-ops.md)"
fi
```

Prepend `$MEMORY_CONTEXT` to the architect prompt as a "## Memory: Accumulated Patterns" section immediately before the Spec and Plan content. If `$MEMORY_CONTEXT` is empty (no relevant files exist yet), omit the section entirely.

Spawn an architect subagent using the Agent tool:
- `description`: "Architect review: validate plan against spec"
- `prompt`: Content of `architect-prompt.md` with `$SPEC_CONTENT` and `$PLAN_CONTENT` replaced with the actual file contents, and with `$MEMORY_CONTEXT` prepended as shown:

  ```
  ## Memory: Accumulated Patterns
  $MEMORY_CONTEXT

  ---
  [architect-prompt.md content with $SPEC_CONTENT and $PLAN_CONTENT filled in]
  ```
```

- [ ] **Step 3: VERIFY AFTER — confirm MEMORY_CONTEXT appears at least three times**

```bash
grep -c "MEMORY_CONTEXT" /workspace/markethawk/.archon/commands/dark-factory-plan.md
```

Expected output: `3` or higher.

- [ ] **Step 4: COMMIT**

```bash
cd /workspace/markethawk
git add .archon/commands/dark-factory-plan.md
git commit -m "$(cat <<'EOF'
feat(plan): pass selective memory context to architect subagent

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

### Task 8: Update `.claude/skills/refinement/architect-prompt.md` — add Section 5 Memory Patterns

**Files:**
- Modify: `.claude/skills/refinement/architect-prompt.md`

**Note on file tracking:** `/opt/refinement-skills/architect-prompt.md` is a container-local path and is NOT tracked in git. The authoritative source file is `.claude/skills/refinement/architect-prompt.md` in the repo, which IS tracked in git (confirmed via `git ls-files .claude/skills/refinement/architect-prompt.md`). Edit the tracked source file — the container mounts or copies it into `/opt/refinement-skills/` at runtime. This change will persist when the PR is merged.

- [ ] **Step 1: VERIFY BEFORE — confirm "Memory Patterns" section does not yet exist**

```bash
grep -q "Memory Patterns" /workspace/markethawk/.claude/skills/refinement/architect-prompt.md && echo PRESENT || echo ABSENT
```

Expected output: `ABSENT`

- [ ] **Step 2: IMPLEMENT — insert new Section 5, renumber old Section 5 to Section 6**

In `.claude/skills/refinement/architect-prompt.md`, locate the existing Section 5 heading:

```
### 5. No Placeholders
Flag any: "TBD", "TODO", "implement later", "add appropriate error handling", "similar to Task N", or steps without code blocks.
```

Replace it with:

```
### 5. Memory Patterns

If the context provided to you contains a section titled `## Memory: Accumulated Patterns`, run this check:

For each `[AVOID]` or `[FIX]` entry in that section:
- Read the core anti-pattern described in the entry.
- Scan every task step and every code block in the plan for actions that would trigger that anti-pattern.
- If a violation is found: flag it as `[MEMORY-VIOLATION]` and quote the relevant memory entry in full.
- If no violations are found for a given entry: note "No memory violations found for: `<first 8 words of the entry>`".

If no `## Memory: Accumulated Patterns` section was provided in the context, skip this section entirely and note "No memory context provided".

### 6. No Placeholders
Flag any: "TBD", "TODO", "implement later", "add appropriate error handling", "similar to Task N", or steps without code blocks.
```

- [ ] **Step 3: VERIFY AFTER — confirm both Section 5 and Section 6 headings are present**

```bash
grep -F -e "### 5. Memory Patterns" -e "### 6. No Placeholders" /workspace/markethawk/.claude/skills/refinement/architect-prompt.md
```

Expected output:
```
### 5. Memory Patterns
### 6. No Placeholders
```

- [ ] **Step 4: COMMIT**

```bash
cd /workspace/markethawk
git add .claude/skills/refinement/architect-prompt.md
git commit -m "$(cat <<'EOF'
feat(architect): Section 5 Memory Patterns — flag AVOID violations from accumulated lessons

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Spec Requirements Coverage

The following table maps all 13 spec requirements to the tasks above:

| Req | Description | Task |
|-----|-------------|------|
| 1 | Global memory file `codebase-patterns.md` | Task 1 |
| 2 | Per-area memory files (backend, frontend, ops, architecture) | Task 1 |
| 3 | Agent read injection — Phase 1 reads in all three commands | Tasks 2, 4, 6 |
| 4 | Post-run memory update in implement agent | Task 3 |
| 5 | Memory entry format with PATTERN/AVOID/FIX and source tag | Tasks 1, 3, 5 |
| 6 | Deduplication before appending (string match on core sentence) | Tasks 3, 5 |
| 7 | Memory commit on feature branch alongside implementation | Tasks 3, 5 |
| 8 | Memory is advisory — conflicts defer to CLAUDE.md/ARCHITECTURE.md | Tasks 2, 3, 4, 5, 6 |
| 9 | Refine and plan agents read memory files | Tasks 4, 5, 6 |
| 10 | No external dependencies — plain markdown committed to repo | Task 1 (no services added) |
| 11 | Refine pipeline writes memory after spec commit (Phase 5 step 6) | Task 5 |
| 12 | Memory expiry — cleanup before appending, `expires` field, default 6-month TTL | Tasks 3, 5 |
| 13 | Architect receives selective memory; Section 5 "Memory Patterns" check | Tasks 7, 8 |
