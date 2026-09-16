# Plan: Cleanup Orphaned Seed Files in dark-factory/seed/seed/

Date: 2026-06-22  
Issue: #518 (scope spillover from #436)  
Spec: [docs/superpowers/specs/2026-06-20-cleanup-orphaned-seed-files-design.md](../specs/2026-06-20-cleanup-orphaned-seed-files-design.md)

## Goal

Remove `dark-factory/seed/seed/` and all of its contents. A failed factory run left behind a mix
of untracked duplicate SQL files **and two git-tracked files** in this directory. All are deleted:

- `dark-factory/seed/seed/01_scanner_configs.sql` — tracked, exact duplicate of
  `dark-factory/seed/01_scanner_configs.sql`. Deleted via `git rm`.
- `dark-factory/seed/seed/06_tweet_monitor.sql` — tracked, unique (no root counterpart).
  Also deleted via `git rm`. **Note:** the tweet-monitor feature is active
  (`services/tweet-monitor/`, `backend/app/routers/tweets.py`, etc.) and this file belongs at
  `dark-factory/seed/06_tweet_monitor.sql` so the preview stack can execute it — but that
  relocation is deliberate new scope and belongs in a follow-up ticket. This plan's scope is
  deletion only, per spec.
- `00_base_tickers.sql`, `02_scanner_data.sql`, `03_market_data.sql`, `04_watchlist.sql`,
  and nested `seed/seed/seed/` — all untracked; deleted via `rm -rf`.

## Deviation from Spec

The spec Assumptions state: *"Files in `dark-factory/seed/seed/` are confirmed exact duplicates
… carry no unique content … never committed to git."* These assumptions are **incorrect**:

1. `01_scanner_configs.sql` is **tracked** in git (not untracked), though it is an exact
   duplicate of the root copy.
2. `06_tweet_monitor.sql` is **tracked** in git with unique content and no root counterpart.

As a result, the spec's "Expected PR content: documentation-only / no git-tracked diff" cannot
be honored literally — deleting the two tracked files requires `git rm` commits that appear in
the PR diff. This is a [MINOR] deviation forced by the incorrect spec assumption; the cleanup
intent (delete the whole `seed/seed/` tree) is preserved. The deviations are documented here
for the human reviewer.

## Architecture

No model, migration, frontend, or Docker changes. The only tracked changes are two `git rm`
deletions plus this plan file.

## Tech Stack

Shell (`git rm`, `rm -rf`) — no backend, frontend, migration, or Docker changes.

## File Structure

| Action | Path | Notes |
|--------|------|-------|
| `git rm` | `dark-factory/seed/seed/01_scanner_configs.sql` | Tracked; exact duplicate of root copy |
| `git rm` | `dark-factory/seed/seed/06_tweet_monitor.sql` | Tracked; unique — follow-up ticket to relocate to root |
| `rm -rf` (untracked) | `dark-factory/seed/seed/` (remainder) | Four untracked duplicates + nested dir |
| No change | `dark-factory/entrypoint.sh` | Root-cause context only; out of scope |
| No change | `docker-compose.preview.yml` | Referenced in assumptions; out of scope |

## Follow-up Required

After this PR merges, file a follow-up ticket to add `dark-factory/seed/06_tweet_monitor.sql`
at the root so the preview stack's `for f in /seed/*.sql` glob actually seeds tweet-monitor data.
The file has been at the wrong path (`seed/seed/`) since `87b97db` and has never been executed.

## Notes from Memory

- `dark-factory-ops.md [PATTERN]`: `docker-compose.preview.yml` mounts `./seed:/seed:ro` and
  runs `for f in /seed/*.sql` — only root-level files execute; subdirectory files do NOT run.
  This confirms that the orphaned `seed/seed/` files (including the deleted `06_tweet_monitor.sql`)
  were never executed by any preview stack.

---

## Task 1 — Safety-Verify Tracked vs Untracked Files

**Purpose:** Confirm the exact set of tracked and untracked files in `dark-factory/seed/seed/`
before taking any destructive action.

**Files:** `dark-factory/seed/seed/` (read-only verification)

**Steps:**

1. List tracked files in `dark-factory/seed/seed/`:

   ```bash
   git ls-files dark-factory/seed/seed/
   ```

   Expected output:
   ```
   dark-factory/seed/seed/01_scanner_configs.sql
   dark-factory/seed/seed/06_tweet_monitor.sql
   ```

2. List all untracked files:

   ```bash
   git status --short dark-factory/seed/seed/
   ```

   Expected output (lines beginning with `??`):
   ```
   ?? dark-factory/seed/seed/00_base_tickers.sql
   ?? dark-factory/seed/seed/02_scanner_data.sql
   ?? dark-factory/seed/seed/03_market_data.sql
   ?? dark-factory/seed/seed/04_watchlist.sql
   ?? dark-factory/seed/seed/seed/
   ```

3. Confirm `01_scanner_configs.sql` is an exact duplicate of the root copy:

   ```bash
   diff dark-factory/seed/01_scanner_configs.sql dark-factory/seed/seed/01_scanner_configs.sql
   ```

   Expected output: none (files identical). If diff output appears, stop and escalate — the
   files differ and `git rm` would destroy unique content stored nowhere else.

4. Confirm `06_tweet_monitor.sql` has no counterpart at the root (i.e., deletion loses no
   currently-executed preview data):

   ```bash
   ls dark-factory/seed/06_tweet_monitor.sql 2>/dev/null && echo "EXISTS — check before deleting" || echo "MISSING at root — deletion safe"
   ```

   Expected output: `MISSING at root — deletion safe`

**TDD:** N/A — verification only; no commit.

---

## Task 2 — Delete Tracked Duplicate (`01_scanner_configs.sql`)

**Purpose:** Remove the tracked copy of `01_scanner_configs.sql` from `seed/seed/`; it is an
exact duplicate of `dark-factory/seed/01_scanner_configs.sql`.

**Files:**
- `dark-factory/seed/seed/01_scanner_configs.sql` (deleted)

**Steps:**

1. Remove from git index and working tree:

   ```bash
   git rm dark-factory/seed/seed/01_scanner_configs.sql
   ```

   Expected output:
   ```
   rm 'dark-factory/seed/seed/01_scanner_configs.sql'
   ```

2. Confirm staged:

   ```bash
   git diff --cached --name-only
   ```

   Expected output:
   ```
   dark-factory/seed/seed/01_scanner_configs.sql
   ```

**TDD:** N/A — `git rm` of a confirmed exact duplicate; Task 1 step 3 was the gate.
No commit yet — all changes commit together in Task 5.

---

## Task 3 — Delete Tracked Unique File (`06_tweet_monitor.sql`)

**Purpose:** Remove the tracked `06_tweet_monitor.sql` from `seed/seed/`. This file has unique
content and belongs at `dark-factory/seed/06_tweet_monitor.sql`, but relocating it is new scope.
Deletion here is spec-faithful (delete all of `seed/seed/`); the relocation is a follow-up.
The deletion is safe because the file was never executed at `seed/seed/` (only root-level files
run in the preview stack).

**Files:**
- `dark-factory/seed/seed/06_tweet_monitor.sql` (deleted)

**Steps:**

1. Remove from git index and working tree:

   ```bash
   git rm dark-factory/seed/seed/06_tweet_monitor.sql
   ```

   Expected output:
   ```
   rm 'dark-factory/seed/seed/06_tweet_monitor.sql'
   ```

2. Confirm both tracked files are now staged for deletion:

   ```bash
   git diff --cached --name-status
   ```

   Expected output:
   ```
   D       dark-factory/seed/seed/01_scanner_configs.sql
   D       dark-factory/seed/seed/06_tweet_monitor.sql
   ```

**TDD:** N/A — `git rm` of a file that was never executed. Task 1 step 4 confirmed no root copy
exists, so deletion does not remove any currently-active seed.

---

## Task 4 — Delete Remaining Untracked Files

**Purpose:** Remove the four untracked duplicate SQL files and the nested `seed/seed/seed/`
directory. After Tasks 2 and 3, no tracked files remain under `dark-factory/seed/seed/`, so
`rm -rf` is safe.

**Files:**
- `dark-factory/seed/seed/` remainder (untracked): `00_base_tickers.sql`, `02_scanner_data.sql`,
  `03_market_data.sql`, `04_watchlist.sql`, and nested `seed/seed/seed/`

**Steps:**

1. Confirm no tracked files remain under `seed/seed/` (safety guard before `rm -rf`):

   ```bash
   git ls-files dark-factory/seed/seed/
   ```

   Expected output: **empty** (all tracked files were removed in Tasks 2–3).
   If any output appears, stop and escalate — do not run `rm -rf`.

2. Delete remaining untracked content:

   ```bash
   rm -rf dark-factory/seed/seed/
   ```

   Expected output: none (silent success).

3. Verify the directory is fully gone:

   ```bash
   ls dark-factory/seed/
   ```

   Expected output:
   ```
   00_base_tickers.sql  01_scanner_configs.sql  02_scanner_data.sql  03_market_data.sql  04_watchlist.sql
   ```

   (No `seed` subdirectory, no `06_tweet_monitor.sql` — that will be added in the follow-up.)

4. Confirm no `??` entries remain under `dark-factory/seed/seed/`:

   ```bash
   git status --short dark-factory/
   ```

   Expected output: only staged deletions (lines beginning with `D`); no `??` lines.

**TDD:** N/A — working-tree cleanup. Safety guard in step 1 is the gate.

---

## Task 5 — Commit

**Purpose:** Commit all staged changes as a single atomic commit.

**Files:**
- `dark-factory/seed/seed/01_scanner_configs.sql` (deleted)
- `dark-factory/seed/seed/06_tweet_monitor.sql` (deleted)
- `docs/superpowers/plans/2026-06-22-cleanup-orphaned-seed-files.md` (new)

**Steps:**

1. Stage the plan file:

   ```bash
   git add docs/superpowers/plans/2026-06-22-cleanup-orphaned-seed-files.md
   ```

2. Confirm staged diff is exactly the three expected changes:

   ```bash
   git diff --cached --name-status
   ```

   Expected output:
   ```
   D       dark-factory/seed/seed/01_scanner_configs.sql
   D       dark-factory/seed/seed/06_tweet_monitor.sql
   A       docs/superpowers/plans/2026-06-22-cleanup-orphaned-seed-files.md
   ```

3. Commit:

   ```bash
   git commit -m "cleanup(#518): delete orphaned dark-factory/seed/seed/ files (tracked + untracked)"
   ```

   Expected output:
   ```
   [feat/issue-518-... <hash>] cleanup(#518): delete orphaned dark-factory/seed/seed/ files (tracked + untracked)
    3 files changed, N insertions(+), N deletions(-)
    delete mode 100644 dark-factory/seed/seed/01_scanner_configs.sql
    delete mode 100644 dark-factory/seed/seed/06_tweet_monitor.sql
   ```

   Note: The PR diff shows two tracked deletions and the plan file — not documentation-only.
   This is expected: the spec's "no git-tracked diff" assumption was incorrect (the files were
   in fact tracked). See "Deviation from Spec" above.

**TDD:** N/A — seed cleanup and documentation commit only.
