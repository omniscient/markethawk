---
description: Implement a feature or fix from a GitHub issue inside the dark factory
argument-hint: (no arguments - reads issue context from workflow)
---

# Dark Factory — Implement

**Workflow ID**: $WORKFLOW_ID

---

## CRITICAL: Epic Guard

**NEVER implement an epic (issue with the `epic` label) as a monolithic change.** Each sub-issue
gets its own branch, PR, and preview stack. The workflow resolves epics to individual sub-issues
before reaching this command. If the issue context still has the `epic` label, STOP immediately
and exit with an error — the resolution should have happened upstream.

**NEVER work on multiple sub-issues in the same branch.** If the issue body references sibling
sub-issues, ignore them. Focus exclusively on the single resolved issue you were given.

## Phase 1: LOAD

Read the project rules:
1. Read `CLAUDE.md` for all development rules, architecture, and validation requirements.
2. Read `ARCHITECTURE.md` for service topology and module map.
3. The issue context has been fetched by the workflow. It is available in the conversation.
4. **Check the `intent` field** in the issue context: `"new"` or `"continue"`.
5. Compute the affected file set and define `load_memory` for path-tag filtering:

```bash
AFFECTED=$(git diff --name-only origin/main...HEAD 2>/dev/null || echo "")

REPO_ROOT=$(git rev-parse --show-toplevel)
source "${REPO_ROOT}/dark-factory/scripts/agent_roles.sh"
AGENT_ID="${AGENT_ID_IMPLEMENTATION}"

# load_memory: reads a memory file; project-tagged entries for other projects are excluded;
# path-tagged entries are filtered against AFFECTED; entries with neither tag are always included.
# When AFFECTED is empty (new branch), all path-tagged entries are included.
load_memory() {
  local MEMFILE=".archon/memory/$1"
  [ -f "$MEMFILE" ] || return
  while IFS= read -r line; do
    # Project filter: skip entries tagged for a different project.
    # Entries without any project: tag are always included (legacy backward compat).
    if echo "$line" | grep -q 'project:'; then
      if ! echo "$line" | grep -q "project:${MEMORY_PROJECT}"; then
        continue
      fi
    fi
    # Path filter: existing behavior unchanged.
    if echo "$line" | grep -q 'path:'; then
      PATH_TAG=$(echo "$line" | sed 's/.*path:\([^ >]*\).*/\1/')
      if [ -z "$AFFECTED" ] || echo "$AFFECTED" | grep -q "^${PATH_TAG}"; then
        echo "$line"
      fi
    else
      echo "$line"
    fi
  done < "$MEMFILE"
}
```

6. Run `load_memory codebase-patterns.md` and include its filtered output in context — global lessons from past runs.
7. Run `load_memory architecture.md` and include its filtered output in context — prior architectural decisions (if the file exists).
8. If the issue touches backend code (`backend/app/models/`, `routers/`, `services/`, `tasks/`): run `load_memory backend-patterns.md` and include its filtered output in context.
9. If the issue touches frontend code (`frontend/src/`): run `load_memory frontend-patterns.md` and include its filtered output in context.
10. If the issue touches Docker or infrastructure files (`docker-compose`, `Dockerfile`, `dark-factory/`): run `load_memory dark-factory-ops.md` and include its filtered output in context.

Apply these lessons as strong hints throughout implementation. If a lesson conflicts with `CLAUDE.md` or `ARCHITECTURE.md`, follow those documents instead and note the conflict in `$ARTIFACTS_DIR/implementation.md`.

When reading memory files, skip entries tagged `[PROVISIONAL]` and `[INVALID]` — they are
unverified or invalidated and must not be used as authoritative guidance. Treat the
`<!-- PROVISIONAL -->` fenced section as advisory context only, never as settled fact.

### If intent is "continue"

This is an iteration on existing work. **The latest comments on the issue and PR contain feedback that must drive your changes.** Do NOT re-implement from scratch. Instead:
1. Read the latest issue comments (bottom of the `comments` array) — these are the user's feedback
2. Read `pr_reviews` if present — top-level PR conversation and review summaries
3. Read `pr_inline_comments` if present — these are line-level code review comments with `path` and `line` pointing to exact locations
3. Review what was already implemented on this branch (`git log --oneline main..HEAD`, read changed files)
4. Focus exclusively on addressing the feedback

### If intent is "new"

This is a fresh implementation. Follow the issue description.

## Phase 2: PLAN

Based on the issue description (new) or feedback (continue) and codebase analysis:
1. Identify which files need to change (backend models, routers, services, frontend components, etc.)
2. Determine if database migrations are needed
3. Write a brief plan (10-20 lines) as a checklist in `$ARTIFACTS_DIR/plan.md`

### PHASE_2_CHECKPOINT
- [ ] Plan written to `$ARTIFACTS_DIR/plan.md`
- [ ] All affected files identified

### Scope Discipline

**Hard rule: fix only what the spec asks for.** This applies to every file you touch.

When you notice an unrelated defect while implementing — a pre-existing SQL bug, a typo in an unrelated file, a test failure you didn't cause — **do not fix it**. Instead:

1. Record it in `$ARTIFACTS_DIR/out-of-scope.md` (create if absent):
   ```
   ## Out-of-scope defects observed
   - <file>: <one-sentence description of the defect>
   ```
2. Leave the defect unfixed. The conformance gate reads this file and will convert each entry into a linked backlog ticket.

A change is **in-scope** only if it is:
- (a) **Spec-named** — explicitly required by the spec/issue,
- (b) **Supporting housekeeping** — docs-map, memory, tests, or migrations that *directly* back an (a) change, or
- (c) **Strictly required** — the in-scope work literally cannot ship without it (e.g. a broken import blocking compilation).

Fixing a pre-existing, unrelated defect — even a real one, even if it makes tests pass — is **out-of-scope**. The correct response is always a backlog entry, never an inline fix.

### Seed Data Awareness

Before implementing, check if the feature requires data that isn't in the baseline seed modules (`dark-factory/seed/`). The baseline covers: tickers, universes, scanner configs, scanner runs/events, stock aggregates (minute bars), watchlist, and system config.

If the feature touches pages or endpoints that need data **not in the baseline**:
1. Create `dark-factory/seed/99_feature.sql` with idempotent INSERT statements (`ON CONFLICT DO NOTHING`) for the **missing** data
2. If that data would benefit future features (not just this one), also add it to a new numbered baseline module (e.g. `05_trades.sql`, `06_journal.sql`) so it persists for future previews
3. Include the seed file(s) in your commits

**Do NOT edit existing numbered seed modules** (e.g. `01_scanner_configs.sql`) to fix pre-existing defects. If an existing seed file has a bug that predates this issue, record it in `out-of-scope.md` and leave it unchanged.

Tables NOT in baseline that commonly need seed data: `trades`, `trade_executions`, `journal_entries`, `tags`, `trading_strategies`, `news_articles`, `alert_rules`, `futures_aggregates`, `stock_metrics`.

## Phase 3: IMPLEMENT (TDD)

### Codeindex blast-radius guidance (advisory)

Before editing any file, call the `get_impact` MCP tool (from the `codeindex` MCP server) on that file's path. If the blast score is high (top-20 files in `codeindex.json`), take extra care: write a focused test covering the changed behaviour, confirm existing tests still pass, and note the high-blast file in your `implementation.md`.

Use `lookup_symbol` instead of grep when you need to find where a function or class is defined or imported.

For each change in the plan:

1. **Write the failing test first** — pytest for backend, type-check for frontend
2. **Run the test to confirm it fails** — `cd backend && python -m pytest tests/ -x -v` or `cd frontend && npx tsc --noEmit`
3. **Implement the minimal code to pass** — follow existing patterns in the codebase
4. **Run the test to confirm it passes**
5. **Commit** — small, focused commits with descriptive messages

If the change requires a new SQLAlchemy model:
1. Create the model file in `backend/app/models/`
2. Import it in `backend/app/models/__init__.py`
3. Generate migration: `cd backend && python -m alembic revision --autogenerate -m "description"`
4. Apply migration: `cd backend && python -m alembic upgrade head`

### PHASE_3_CHECKPOINT
- [ ] All tests pass: `cd backend && python -m pytest`
- [ ] Frontend type-checks: `cd frontend && npx tsc --noEmit` (if frontend changed)
- [ ] All changes committed
- [ ] Implementation summary written to `$ARTIFACTS_DIR/implementation.md`

## Phase 4: DOCUMENT

1. Read the file list from `$ARTIFACTS_DIR/implementation.md` (all files created/modified in Phase 3).
   Cross-check: `git diff main...HEAD --name-only` for completeness.
2. Classify each path against this mapping to produce the list of `(doc_file, section)` pairs to update:

   | Changed file pattern | Documentation target | Section |
   |---|---|---|
   | `backend/app/models/*.py` | `ARCHITECTURE.md` | Database Models table |
   | `backend/app/models/*.py` | `PROJECT_STRUCTURE.md` | `models/` directory entry |
   | `backend/app/routers/*.py` | `ARCHITECTURE.md` | Routers table |
   | `backend/app/routers/*.py` | `PROJECT_STRUCTURE.md` | `routers/` directory entry |
   | `backend/app/services/*.py` | `ARCHITECTURE.md` | Services table |
   | `backend/app/services/*.py` | `PROJECT_STRUCTURE.md` | `services/` directory entry |
   | `frontend/src/pages/*.tsx` | `ARCHITECTURE.md` | Pages table |
   | `.env.example` | `ENV_VARIABLES.md` | Relevant section |
   | `docker-compose.yml` (new service added/removed) | `ARCHITECTURE.md` | Service Topology section |
   | `CLAUDE.md`-affecting changes (new port, command, pattern) | `CLAUDE.md` | Relevant section |

   Rules:
   - If a path matches no pattern, skip it.
   - If a file was modified but nothing added/removed (e.g. only existing model fields changed), still read the current doc row and update it if the description is now inaccurate.
   - If a file was deleted, remove the corresponding doc row.
   - `CLAUDE.md` is only touched if the change adds/removes a developer-facing command, port, or architectural pattern. This is rare and requires explicit judgment.
   - `docs/database-schema.md` is auto-generated — never edit it.

3. If no pairs matched, skip this phase entirely (no docs commit needed).
4. For each `(doc_file, section)` pair:
   a. Read the current section in full
   b. Read the changed source file(s) that triggered this pair
   c. Write the updated section content: add a new row, update an existing row, or remove a deleted entry. Read surrounding entries and match their style (inline comments, column widths, etc.)
5. Commit all doc changes: `git commit -m "docs: update architecture map for <feature-slug>"` — derive `<feature-slug>` from the branch name (e.g. `feat/issue-12-new-router` → `new-router`).

### PHASE_4_CHECKPOINT
- [ ] `git diff main...HEAD --name-only` run and classified against the mapping table
- [ ] All matched doc sections updated
- [ ] `docs:` commit created (or phase explicitly skipped — no matches)

## Phase 5: MEMORY UPDATE

After Phase 4 DOCUMENT completes. Note: `$ARTIFACTS_DIR/implementation.md` is written during
Phase 3; Phase 4 reads it; Phase 6 finalizes it. Phase 5 runs after Phase 4 independently.

### Write bar — default to nothing

Before adding any entry, apply this filter in order and skip at the first "no":

1. **Decision-changing?** Would a future agent make a materially different decision because
   of this entry, compared to reading `CLAUDE.md` and `ARCHITECTURE.md` alone? If no → skip.
2. **Not factory trivia?** Shell compatibility quirks, environment-specific workarounds,
   container-local debugging steps → skip. These have no durability beyond the current image.
3. **Not a near-duplicate?** `grep -F "<core sentence>" .archon/memory/*.md` — if any match → skip.
4. **Not already in `CLAUDE.md` / `ARCHITECTURE.md`?** → skip.

Most runs add zero entries. That is the correct default.

### Entry types

| Tag | When to use |
|-----|-------------|
| `[PATTERN]` | Design pattern or step that consistently works and should be repeated |
| `[AVOID]` | Pattern that consistently fails or causes bugs |
| `[FIX]` | Corrective action for a known failure mode |
| `[PROVISIONAL]` | Runtime-behavior claim observed on this run only — goes in the provisional section |
| `[INVALID: <reason>]` | Formerly-promoted `[PATTERN]` proven wrong — tombstone only, do not delete |

### Target file

| Topic | File |
|-------|------|
| Global workflow / checklist lesson | `.archon/memory/codebase-patterns.md` |
| SQLAlchemy, Alembic, FastAPI, Celery | `.archon/memory/backend-patterns.md` |
| React Query, TypeScript, components, Tailwind | `.archon/memory/frontend-patterns.md` |
| Docker, preview stack, seed data, dark factory ops | `.archon/memory/dark-factory-ops.md` |
| Architectural trade-offs (**refine agent only**) | `.archon/memory/architecture.md` — **do not write here** |

### Expiry cleanup (run first, before appending to any file)

```bash
TODAY=$(date +%Y-%m-%d)
TARGET=".archon/memory/backend-patterns.md"  # replace with actual target file
awk -v today="$TODAY" '
  /expires:[0-9]{4}-[0-9]{2}-[0-9]{2}/ {
    found=match($0, /expires:[0-9]{4}-[0-9]{2}-[0-9]{2}/)
    if (found) { expiry_date=substr($0, RSTART+8, 10); if (expiry_date < today) next }
  }
  { print }
' "$TARGET" > "$TARGET.tmp" && mv "$TARGET.tmp" "$TARGET"
```

### Writing a `[PROVISIONAL]` entry (R2)

Any claim about runtime behavior (container behavior, CLI tool output, framework quirk) that
you observed on this run only must be provisional — NOT promoted directly to `[PATTERN]`:

1. Add it to the `<!-- PROVISIONAL -->` fenced section at the bottom of the relevant file.
   Create the section if it does not exist using this exact format:

   ```markdown
   ---
   <!-- PROVISIONAL — entries below are from a single observed run; unverified.
        Do not rely on these as authoritative guidance. They are excluded from
        plan/implement prompt injection except as advisory context.
        Each will be promoted to [PATTERN] on second-run confirmation (different issue number) or dropped at TTL. -->

   - [PROVISIONAL] <claim> <!-- evidence:<method> issue:#$ISSUE_NUM date:$(date +%Y-%m-%d) expires:$(date -d '+6 months' +%Y-%m-%d 2>/dev/null || date -v+6m +%Y-%m-%d) source:implement -->
   ```

   where `<method>` is how you observed the behavior: `docker-exec`, `curl-response`,
   `test-output`, `log-inspection`, etc.

2. Max 10 provisional entries per file. If already at 10, drop the oldest by date first.

**Promotion to `[PATTERN]`:** A subsequent run with a *different issue number* independently
observes the same behavior and adds its own `evidence:` comment. The promoting agent rewrites
the entry as `[PATTERN]` (moves it out of the PROVISIONAL section) and adds the second
evidence tag inline.

**Expiry:** Provisional entries not promoted within 6 months are dropped during the next
expiry cleanup. No manual review needed.

### Writing authoritative entries

Format:
```
- [PATTERN|AVOID|FIX] <concise actionable sentence, specific paths/commands/names where relevant> <!-- issue:#$ISSUE_NUM date:$(date +%Y-%m-%d) expires:$(date -d '+6 months' +%Y-%m-%d 2>/dev/null || date -v+6m +%Y-%m-%d) source:implement -->
```

**Append-only rule:** New memory entries must be written with shell appends:
  echo '- [PATTERN] ...' >> .archon/memory/backend-patterns.md
NEVER use the Write or Edit tool on a memory file to add new entries — doing so risks
regenerating the file from a stale in-context copy and silently dropping existing entries.

The ONLY operations permitted to remove or modify existing lines are:
  (a) the awk expiry-cleanup block (entries with a past `expires:` date)
  (b) R4 cap-drop (explicit drop of the oldest/lowest-signal entries when COUNT > 30)
  (c) R5 invalidation (rewrite `[PATTERN]` → `[INVALID: reason]` for a single entry)
Each of these operations must touch ONLY the targeted lines and leave all other lines verbatim.

### Per-file authoritative entry cap (R4)

After appending, count authoritative entries in the target file:

```bash
COUNT=$(grep -c '^\- \[PATTERN\]\|^\- \[AVOID\]\|^\- \[FIX\]' "$TARGET" || true)
if [ "$COUNT" -gt 30 ]; then
  echo "WARNING: $TARGET has $COUNT authoritative entries (cap: 30). Drop before committing."
  # Drop priority: (1) entries past TTL, (2) scope covered by a newer/broader entry,
  # (3) oldest by date field. Read the file, choose candidates, delete their lines.
fi
```

### Invalidating a wrong `[PATTERN]` (R5)

When this run proves an existing `[PATTERN]` is wrong:

1. Find the entry: `grep -n '^\- \[PATTERN\]' .archon/memory/<file>.md | grep "<phrase>"`
2. Replace `[PATTERN]` with `[INVALID: <one-phrase reason>]` — keep the full line including
   the inline comment, update only the tag.

Example:
```
- [INVALID: Caddy binds :80/:443 even when DOMAIN is unset] The --profile tls caddy command
  exits cleanly when DOMAIN is not set. <!-- issue:#202 date:2026-05-30 expires:2026-11-30 source:implement -->
```

The tombstone counts toward the 30-entry cap and expires on the original TTL. Do not delete
it — it prevents the same wrong claim from being re-added during the TTL window.

### Post-write verification backstop

Run this block after all R3/R4/R5 operations and before `git add .archon/memory/`:

```bash
# Memory write guard — detect unexpected deletions and restore (append-only; never reverts this run's new entries)
for MEM_FILE in .archon/memory/*.md; do
  [ -f "$MEM_FILE" ] || continue
  # Deleted content lines (diff marker '-'), excluding file-header markers
  DELETED=$(git diff "$MEM_FILE" | grep '^-' | grep -v '^---' | grep -v '^-#' | grep -v '^-<!--' || true)
  if [ -n "$DELETED" ]; then
    # Added content lines with the diff '+' marker stripped, for R5 body comparison
    ADDED=$(git diff "$MEM_FILE" | grep '^+' | grep -v '^+++' | sed 's/^+//')
    TODAY=$(date +%Y-%m-%d)
    UNEXPECTED=$(echo "$DELETED" | while IFS= read -r line; do
      # Strip the diff '-' marker to recover the file-content line
      CONTENT=$(printf '%s' "$line" | sed 's/^-//')
      # Legitimate expiry cleanup: an expires: date in the past
      if echo "$CONTENT" | grep -q 'expires:'; then
        EXPIRY=$(echo "$CONTENT" | sed 's/.*expires:\([0-9-]*\).*/\1/')
        [ "$EXPIRY" \< "$TODAY" ] && continue
      fi
      # Legitimate R5 invalidation: same body re-added with a changed tag.
      # Strip a leading "- [ANYTAG]" to get the bare body, then look for it among added lines.
      BODY=$(printf '%s' "$CONTENT" | sed 's/^- \[[^]]*\]//')
      if [ -n "$BODY" ] && printf '%s\n' "$ADDED" | grep -qF -- "$BODY"; then
        continue
      fi
      printf '%s\n' "$CONTENT"
    done)
    if [ -n "$UNEXPECTED" ]; then
      echo "MEMORY GUARD: unexpected deletion(s) in $MEM_FILE — re-appending to preserve them:"
      printf '%s\n' "$UNEXPECTED"
      # Append-only restore: re-append the deleted authoritative line(s). This preserves
      # this run's new entries (unlike a whole-file checkout) and is self-healing for R4
      # cap-drops (a re-appended over-cap entry is simply re-capped on the next run).
      printf '%s\n' "$UNEXPECTED" >> "$MEM_FILE"
    fi
  fi
done
```

### Commit

If any entries were added, updated, or invalidated:
```bash
git add .archon/memory/
git commit -m "memory: lessons from issue #$ISSUE_NUM"
```

If no changes were made: skip the commit. Do not create an empty commit.

**Memory quality rules:**
- One sentence per bullet — dense and actionable. Reference specific paths, commands, names.
- No generic advice.
- Do NOT duplicate `CLAUDE.md` or `ARCHITECTURE.md`.
- Do NOT write to `architecture.md` from the implement agent.

## Phase 6: REPORT

Write a summary of what was implemented to `$ARTIFACTS_DIR/implementation.md`:
- Files created/modified
- Tests added
- Migrations created (if any)
- Any decisions or trade-offs made
