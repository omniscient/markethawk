# Documentation — Single Source of Truth Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give every drifting fact exactly one canonical owner. Fix known port drift (3000→3333) and tasks.py→tasks/ across all affected docs. Slim README.md to a thin front door (remove duplicated env-var table and command sections). Slim CLAUDE.md's commands section so DEVELOPMENT.md is the single authoritative command reference.

**Architecture:** Pure documentation change — no code changes, no migrations, no backend or frontend modifications. All files are Markdown. Verification is grep-based: confirm bad content is absent, new content is present.

**Canonical ownership after this plan:**
- **Ports** → service-ports table in `CLAUDE.md` (already correct; all other docs link to it or re-assert `CLAUDE.md`'s value)
- **Env vars** → `ENV_VARIABLES.md` (already comprehensive; `README.md` table removed)
- **Commands** → `DEVELOPMENT.md` (already comprehensive; `README.md` sections and `CLAUDE.md` Backend/Frontend manual sections removed)
- **README.md** → thin front door: features, criteria, architecture diagram, two-step quick-start, documentation table

---

## File Structure

| File | Role | Changes |
|------|------|---------|
| `README.md` | Thin front door | Fix port 3000→3333; fix `tasks.py`→`tasks/`; remove env-var table; remove duplicated DB/test/docker command sections |
| `DEVELOPMENT.md` | Owns commands | Fix port 3000→3333 (two occurrences) |
| `ARCHITECTURE.md` | System topology | Fix port `HTTP:3000`→`HTTP:3333` in topology diagram |
| `CLAUDE.md` | Agent quick-ref | Remove Backend and Frontend manual command sections; add DEVELOPMENT.md reference note |
| `ENV_VARIABLES.md` | Owns env vars | No change — already the authoritative reference |
| `PROJECT_STRUCTURE.md` | File tree | No change — already shows `tasks/` (package) correctly |

---

### Task 1: Fix port drift and tasks.py drift in README.md

**Files:** `README.md`

Two distinct drift items in the same file. Fix them together so a single commit makes README.md internally consistent.

- [ ] **Step 1: Verify the drift exists**

```bash
grep -n "localhost:3000\|tasks\.py" README.md
```

Expected: Two matches — one at the "Access the application" table (port 3000) and one in the Backend module map (`tasks.py`).

- [ ] **Step 2: Fix frontend port in the "Access the application" table**

In `README.md`, in the "Access the application" table under "Quick Start", replace:

```
| Frontend | http://localhost:3000 |
```

with:

```
| Frontend | http://localhost:3333 |
```

- [ ] **Step 3: Fix tasks.py → tasks/ in the Backend module map**

In `README.md`, in the backend directory tree under "Architecture → Backend", replace:

```
tasks.py        — Celery background/scheduled tasks
```

with:

```
tasks/          — Celery task package (sync.py, scanning.py, trading.py, quality.py)
```

- [ ] **Step 4: Verify both fixes applied cleanly**

```bash
grep -n "localhost:3000\|tasks\.py" README.md
```

Expected: **zero matches** — no remaining port drift or stale module name.

```bash
grep -n "localhost:3333\|tasks/" README.md
```

Expected: At least one match each confirming the new values are present.

- [ ] **Step 5: Commit**

```bash
git add README.md
git commit -m "docs(#168): fix port 3000→3333 and tasks.py→tasks/ drift in README"
```

---

### Task 2: Fix port drift in DEVELOPMENT.md

**Files:** `DEVELOPMENT.md`

DEVELOPMENT.md owns commands and service URLs — so the correct port lives here. Two occurrences to fix: the service URL table and the manual-setup note.

- [ ] **Step 1: Verify the drift exists**

```bash
grep -n "localhost:3000" DEVELOPMENT.md
```

Expected: At least two matches (service URL table and manual frontend setup comment).

- [ ] **Step 2: Fix the service URL table**

In `DEVELOPMENT.md`, under "Service URLs", replace:

```
| Frontend | http://localhost:3000 | — |
```

with:

```
| Frontend | http://localhost:3333 | — |
```

- [ ] **Step 3: Fix the manual-setup comment**

In `DEVELOPMENT.md`, under "Manual Setup → Frontend", replace:

```
npm run dev        # Dev server at http://localhost:3000
```

with:

```
npm run dev        # Dev server at http://localhost:3333
```

- [ ] **Step 4: Check for any remaining occurrences**

```bash
grep -n "localhost:3000" DEVELOPMENT.md
```

Expected: **zero matches** — no remaining port drift.

- [ ] **Step 5: Also fix the port conflict troubleshooting section**

```bash
grep -n ":3000" DEVELOPMENT.md
```

If a `netstat -ano | findstr :3000` line appears (troubleshooting section), replace `:3000` with `:3333` there too.

- [ ] **Step 6: Commit**

```bash
git add DEVELOPMENT.md
git commit -m "docs(#168): fix port 3000→3333 drift in DEVELOPMENT.md"
```

---

### Task 3: Fix port drift in ARCHITECTURE.md topology diagram

**Files:** `ARCHITECTURE.md`

The service topology ASCII diagram shows `Browser ──HTTP:3000──>`. Fix it to match the actual port.

- [ ] **Step 1: Verify the drift exists**

```bash
grep -n "HTTP:3000\|localhost:3000" ARCHITECTURE.md
```

Expected: At least one match in the topology diagram.

- [ ] **Step 2: Fix the topology diagram**

In `ARCHITECTURE.md`, in the ASCII topology diagram at the top, replace:

```
  Browser ──HTTP:3000──> │ frontend ──HTTP──> backend:8000          │
```

with:

```
  Browser ──HTTP:3333──> │ frontend ──HTTP──> backend:8000          │
```

- [ ] **Step 3: Verify fix applied**

```bash
grep -n "HTTP:3000\|localhost:3000" ARCHITECTURE.md
```

Expected: **zero matches**.

```bash
grep -n "HTTP:3333" ARCHITECTURE.md
```

Expected: one match confirming the correct port.

- [ ] **Step 4: Commit**

```bash
git add ARCHITECTURE.md
git commit -m "docs(#168): fix port 3000→3333 drift in ARCHITECTURE.md topology"
```

---

### Task 4: Slim README.md — Remove env-var table, replace with ENV_VARIABLES.md link

**Files:** `README.md`

`README.md` contains a partial env-var table that duplicates `ENV_VARIABLES.md`. Remove the table and replace it with a one-liner link. ENV_VARIABLES.md is the canonical owner.

- [ ] **Step 1: Verify the duplicate table exists**

```bash
grep -n "POLYGON_API_KEY\|DATABASE_URL\|SECRET_KEY" README.md
```

Expected: Multiple matches — rows of the env-var table.

- [ ] **Step 2: Replace the "Environment Variables" section in README.md**

Remove the `## Environment Variables` section with its full table (the block starting with `## Environment Variables` and ending with the last table row), and replace it with:

```markdown
## Environment Variables

See [ENV_VARIABLES.md](ENV_VARIABLES.md) for the complete reference with defaults and descriptions.
```

- [ ] **Step 3: Verify the table is gone**

```bash
grep -n "POLYGON_API_KEY\|DATABASE_URL\|SECRET_KEY\|PGADMIN" README.md
```

Expected: **zero matches** — no env-var table rows remain in README.

```bash
grep -n "ENV_VARIABLES.md" README.md
```

Expected: at least one match confirming the link is present.

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs(#168): slim README env-var section — link to ENV_VARIABLES.md"
```

---

### Task 5: Slim README.md — Remove duplicated command sections

**Files:** `README.md`

README.md has three command sections that duplicate content already owned by DEVELOPMENT.md: "Database Migrations", "Running Tests", and "Useful Docker Commands". Remove these sections and replace with a single reference pointing to DEVELOPMENT.md.

- [ ] **Step 1: Verify the duplicated sections exist**

```bash
grep -n "## Database Migrations\|## Running Tests\|## Useful Docker Commands" README.md
```

Expected: Three matches — one heading per section to remove.

- [ ] **Step 2: Remove "Database Migrations" section**

Remove the `## Database Migrations` heading and its content block (from the heading to just before the next `##` heading).

- [ ] **Step 3: Remove "Running Tests" section**

Remove the `## Running Tests` heading and its content block.

- [ ] **Step 4: Remove "Useful Docker Commands" section**

Remove the `## Useful Docker Commands` heading and its content block.

- [ ] **Step 5: Add DEVELOPMENT.md reference after Quick Start**

After the Quick Start section (before the Documentation table), add:

```markdown
> For detailed setup, manual (non-Docker) configuration, database migrations, running tests, and troubleshooting, see [DEVELOPMENT.md](DEVELOPMENT.md).
```

- [ ] **Step 6: Verify sections are removed and link is present**

```bash
grep -n "## Database Migrations\|## Running Tests\|## Useful Docker Commands" README.md
```

Expected: **zero matches**.

```bash
grep -n "DEVELOPMENT.md" README.md
```

Expected: At least one match (the new link and the existing Documentation table entry).

- [ ] **Step 7: Commit**

```bash
git add README.md
git commit -m "docs(#168): slim README — remove duplicated command sections, link to DEVELOPMENT.md"
```

---

### Task 6: Slim CLAUDE.md — Remove Backend and Frontend manual command sections

**Files:** `CLAUDE.md`

CLAUDE.md has "Backend (manual)" and "Frontend (manual)" command sections that duplicate DEVELOPMENT.md. Keep only the Docker section (the four commands agents use constantly). Add a note pointing to DEVELOPMENT.md for the full reference.

- [ ] **Step 1: Verify the duplicate sections exist**

```bash
grep -n "pip install\|npm install\|npm run dev\|npm run build\|uvicorn app.main" CLAUDE.md
```

Expected: Multiple matches — the Backend and Frontend manual command blocks.

- [ ] **Step 2: Remove "Backend (manual)" section from CLAUDE.md Commands**

Remove the `### Backend (manual)` heading and its entire code block (from the heading to just before the next `###`).

- [ ] **Step 3: Remove "Frontend (manual)" section from CLAUDE.md Commands**

Remove the `### Frontend (manual)` heading and its entire code block.

- [ ] **Step 4: Add reference note after the Docker section**

After the `### Docker (recommended for full stack)` block and its dev/live isolation note, add:

```markdown
> For manual (non-Docker) backend and frontend setup, migration commands, test commands, and pre-commit hook setup, see [DEVELOPMENT.md](DEVELOPMENT.md).
```

- [ ] **Step 5: Verify the manual sections are gone and link is present**

```bash
grep -n "pip install\|npm install\|npm run dev\|uvicorn app.main" CLAUDE.md
```

Expected: **zero matches** — no manual backend/frontend commands remain.

```bash
grep -n "DEVELOPMENT.md" CLAUDE.md
```

Expected: at least one match confirming the reference link is present.

- [ ] **Step 6: Commit**

```bash
git add CLAUDE.md
git commit -m "docs(#168): slim CLAUDE.md commands — remove Backend/Frontend manual sections, link to DEVELOPMENT.md"
```

---

### Task 7: Final audit — confirm no residual drift

**Files:** `README.md`, `DEVELOPMENT.md`, `ARCHITECTURE.md`, `CLAUDE.md`

Run a comprehensive grep across all affected files to confirm no drift remains.

- [ ] **Step 1: Confirm port 3000 is gone from all docs**

```bash
grep -rn "localhost:3000\|HTTP:3000" README.md DEVELOPMENT.md ARCHITECTURE.md CLAUDE.md
```

Expected: **zero matches**. If any appear, fix them now.

- [ ] **Step 2: Confirm tasks.py is gone from README.md**

```bash
grep -n "tasks\.py" README.md
```

Expected: **zero matches**.

- [ ] **Step 3: Confirm env-var table is gone from README.md**

```bash
grep -n "POLYGON_API_KEY\|POSTGRES_PASSWORD\|SECRET_KEY" README.md
```

Expected: **zero matches**.

- [ ] **Step 4: Confirm duplicated command sections are gone from README.md**

```bash
grep -n "## Database Migrations\|## Running Tests\|## Useful Docker Commands\|pip install\|npm install" README.md
```

Expected: **zero matches**.

- [ ] **Step 5: Confirm duplicated command sections are gone from CLAUDE.md**

```bash
grep -n "pip install\|npm run dev\|uvicorn app.main" CLAUDE.md
```

Expected: **zero matches**.

- [ ] **Step 6: Confirm canonical owners are intact**

```bash
# CLAUDE.md still has the service ports table with 3333
grep -n "localhost:3333" CLAUDE.md

# ENV_VARIABLES.md still has the env-var table
grep -n "POLYGON_API_KEY" ENV_VARIABLES.md

# DEVELOPMENT.md still has the full command reference
grep -n "python -m pytest\|alembic upgrade head\|npm run dev" DEVELOPMENT.md
```

Expected: Each grep returns at least one match, confirming canonical owners are intact.

- [ ] **Step 7: Final commit (if any residual fixes were applied)**

```bash
git add README.md DEVELOPMENT.md ARCHITECTURE.md CLAUDE.md
git commit -m "docs(#168): audit — fix residual drift found in final sweep"
```
