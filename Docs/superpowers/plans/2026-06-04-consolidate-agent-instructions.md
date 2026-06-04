# Plan: Consolidate Competing Agent-Instruction Systems (Issue #170)

**Goal:** Retire the orphaned `.agent/skills/` directory (6 SKILL.md files + scripts), drop the stale reference in `POLYGON_RATE_LIMITS.md`, and add canonical-source notes to `.claude/agents/migrate.md` and `.claude/agents/validate.md` so that commands have one authoritative home.

**Architecture:** Pure documentation/configuration change — no runtime code, no migrations, no TypeScript compilation. Nothing loads `.agent/skills/`; deletion has zero runtime impact.

**Constraint:** `.archon/memory/architecture.md` records an explicit decision: "do not store agent memory in CLAUDE.md." This plan targets **human-authored** layers only — `.archon/memory/` is untouched.

**Tech Stack:** N/A — documentation and config files only.

---

## File Structure

| File | Action |
|------|--------|
| `.agent/skills/db_migrations/SKILL.md` | Delete |
| `.agent/skills/bash/SKILL.md` | Delete |
| `.agent/skills/backend_tests/SKILL.md` | Delete |
| `.agent/skills/frontend_lint/SKILL.md` | Delete |
| `.agent/skills/error_tracking/SKILL.md` | Delete |
| `.agent/skills/massive_api_research/SKILL.md` | Delete |
| `.agent/skills/massive_api_research/scripts/query_api.py` | Delete |
| `POLYGON_RATE_LIMITS.md` | Edit — replace dead script reference with `curl` |
| `.claude/agents/migrate.md` | Edit — prepend canonical-source note |
| `.claude/agents/validate.md` | Edit — prepend canonical-source note |

---

## Task 1 — Delete the orphaned `.agent/skills/` directory

**Files:** `.agent/skills/**` (entire tree)  
**Time estimate:** 2–3 minutes

### Steps

1. **Confirm nothing loads `.agent/skills/`**

   ```bash
   grep -rn "\.agent/skills" /workspace/markethawk \
     --include="*.md" --include="*.yml" --include="*.yaml" \
     --include="*.json" --include="*.py" --include="*.ts" --include="*.tsx"
   ```

   Expected: only the two lines in `POLYGON_RATE_LIMITS.md` (handled in Task 2).  
   If any loader or import appears outside `POLYGON_RATE_LIMITS.md`, stop and investigate before deleting.

2. **Delete the directory via git**

   ```bash
   cd /workspace/markethawk
   git rm -r .agent/skills/
   ```

   Expected output:
   ```
   rm '.agent/skills/backend_tests/SKILL.md'
   rm '.agent/skills/bash/SKILL.md'
   rm '.agent/skills/db_migrations/SKILL.md'
   rm '.agent/skills/error_tracking/SKILL.md'
   rm '.agent/skills/frontend_lint/SKILL.md'
   rm '.agent/skills/massive_api_research/SKILL.md'
   rm '.agent/skills/massive_api_research/scripts/query_api.py'
   ```

3. **Verify the directory is gone**

   ```bash
   ls /workspace/markethawk/.agent/skills/ 2>&1
   ```

   Expected: `ls: cannot access ... No such file or directory`

4. **Commit**

   ```bash
   git commit -m "$(cat <<'EOF'
   chore(#170): delete orphaned .agent/skills/ directory

   Nothing in the repo loads these 6 SKILL.md files. The same guidance
   lives in .claude/agents/ (migrate.md, validate.md) and CLAUDE.md.
   Removing the dead copies eliminates silent command drift.

   Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
   EOF
   )"
   ```

---

## Task 2 — Replace stale `.agent/skills/` script reference in `POLYGON_RATE_LIMITS.md`

**Files:** `POLYGON_RATE_LIMITS.md` (lines 74–80)  
**Time estimate:** 2–3 minutes

### Steps

1. **Read the affected section** to confirm exact text before editing:

   ```bash
   sed -n '72,84p' /workspace/markethawk/POLYGON_RATE_LIMITS.md
   ```

   Expected (current state):
   ```markdown
   ## Verifying API Connectivity

   ```bash
   # Check market status (uses one API call)
   python .agent/skills/massive_api_research/scripts/query_api.py custom "/v1/marketstatus/now"

   # Verify your key works
   python .agent/skills/massive_api_research/scripts/query_api.py details "AAPL"
   ```

   The script reads `POLYGON_API_KEY` from `.env` automatically.
   ```

2. **Edit `POLYGON_RATE_LIMITS.md`** — replace the Python script lines with `curl` equivalents:

   Replace this block:
   ```
   ```bash
   # Check market status (uses one API call)
   python .agent/skills/massive_api_research/scripts/query_api.py custom "/v1/marketstatus/now"

   # Verify your key works
   python .agent/skills/massive_api_research/scripts/query_api.py details "AAPL"
   ```

   The script reads `POLYGON_API_KEY` from `.env` automatically.
   ```

   With this block:
   ```
   ```bash
   # Check market status (uses one API call)
   curl -s "https://api.polygon.io/v1/marketstatus/now?apiKey=$POLYGON_API_KEY" | python -m json.tool

   # Verify your key works
   curl -s "https://api.polygon.io/v3/reference/tickers/AAPL?apiKey=$POLYGON_API_KEY" | python -m json.tool
   ```

   Set `POLYGON_API_KEY` in `.env` — `docker-compose` exports it automatically.
   ```

3. **Verify no remaining `.agent/skills` references**

   ```bash
   grep -rn "\.agent/skills" /workspace/markethawk
   ```

   Expected: no output.

4. **Commit**

   ```bash
   git commit -m "$(cat <<'EOF'
   docs(#170): replace dead .agent/skills script ref in POLYGON_RATE_LIMITS.md

   The query_api.py script was part of the now-deleted .agent/skills/ tree.
   Replace both usages with equivalent curl commands that work out of the box
   and require no Python dependency setup.

   Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
   EOF
   )"
   ```

---

## Task 3 — Add canonical-source notes to `.claude/agents/migrate.md` and `validate.md`

**Files:** `.claude/agents/migrate.md`, `.claude/agents/validate.md`  
**Time estimate:** 3–5 minutes

The alembic commands in `migrate.md` and the validation commands in `validate.md` mirror sections in `CLAUDE.md`. Adding a visible maintenance note marks CLAUDE.md as the single source of truth so a future command change has one place to fix.

### Steps

1. **Read both files** to locate the exact frontmatter boundary (the closing `---` line after the YAML block) so the note is inserted correctly:

   ```bash
   head -10 /workspace/markethawk/.claude/agents/migrate.md
   head -10 /workspace/markethawk/.claude/agents/validate.md
   ```

2. **Edit `.claude/agents/migrate.md`** — insert the following blockquote immediately after the closing frontmatter `---` line and before the first `##` heading:

   ```markdown
   > **Canonical command reference:** `CLAUDE.md → Database Migrations` and `DEVELOPMENT.md`.
   > If any alembic command here diverges from CLAUDE.md, update CLAUDE.md — it is the authoritative source.
   ```

   Full insertion point example (after `---` that closes the YAML front-matter, before `You are the database migration agent...`):

   ```markdown
   ---

   > **Canonical command reference:** `CLAUDE.md → Database Migrations` and `DEVELOPMENT.md`.
   > If any alembic command here diverges from CLAUDE.md, update CLAUDE.md — it is the authoritative source.

   You are the database migration agent for MarketHawk...
   ```

3. **Edit `.claude/agents/validate.md`** — insert the equivalent note after its closing `---` frontmatter line:

   ```markdown
   > **Canonical command reference:** `CLAUDE.md → Validating Changes Before Committing`.
   > If any validation command here diverges from CLAUDE.md, update CLAUDE.md — it is the authoritative source.
   ```

4. **Verify** the files still parse as valid Markdown and the agent YAML frontmatter is intact:

   ```bash
   head -12 /workspace/markethawk/.claude/agents/migrate.md
   head -12 /workspace/markethawk/.claude/agents/validate.md
   ```

   The YAML block (`---`…`---`) must be unchanged; the note must appear after the closing `---`.

5. **Commit**

   ```bash
   git commit -m "$(cat <<'EOF'
   docs(#170): add canonical-source notes to .claude/agents migrate and validate

   CLAUDE.md is the authoritative home for alembic and validation commands.
   Adding a maintenance note to each agent file makes the canonical source
   explicit so developers know where to update commands and agents stop
   drifting silently.

   Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
   EOF
   )"
   ```

---

## Validation Checklist (post all tasks)

```bash
# No orphaned skill references remain
grep -rn "\.agent/skills" /workspace/markethawk
# Expected: no output

# All planned file deletions are staged/committed
git status
# Expected: clean working tree (all changes committed)

# .archon/memory/ is untouched
git diff HEAD -- .archon/memory/
# Expected: no output
```
