# Memory System Revamp — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a single PR that (1) audits and prunes all ~79 existing memory entries to a high-signal core with documented before/after counts, and (2) revamps the write/curate/consume loop so the system stops accumulating noise going forward — via a default-to-nothing write bar, a `[PROVISIONAL]` tier for empirical runtime claims, a hard 30-entry cap, an `[INVALID]` tombstone for proven-wrong entries, and consume-side filters that strip unverified/invalidated entries before injecting memory into prompts.

**Architecture:** Markdown-only changes to 5 `.archon/memory/` files and 3 `.archon/commands/` files. No backend or frontend code. No migrations. No new services.

**Tech Stack:** Bash (mawk-compatible awk), Markdown, `git`, `grep`, `wc`.

**Spec:** [`docs/superpowers/specs/2026-06-06-memory-system-revamp-design.md`](../specs/2026-06-06-memory-system-revamp-design.md)
**Issue:** [#254](https://github.com/omniscient/markethawk/issues/254)
**Epic:** [#262 — Harden the Dark Factory self-improvement loop](https://github.com/omniscient/markethawk/issues/262)

---

## File Structure

| File | Change |
|------|--------|
| `.archon/memory/architecture.md` | Audit + prune entries; add `<!-- PROVISIONAL -->` footer section |
| `.archon/memory/backend-patterns.md` | Audit + prune entries; add `<!-- PROVISIONAL -->` footer section |
| `.archon/memory/codebase-patterns.md` | Audit + prune entries; add `<!-- PROVISIONAL -->` footer section |
| `.archon/memory/dark-factory-ops.md` | Audit + prune entries aggressively (currently ~45 entries → ≤ 30); add `<!-- PROVISIONAL -->` footer section |
| `.archon/memory/frontend-patterns.md` | Audit + prune entries; add `<!-- PROVISIONAL -->` footer section |
| `.archon/commands/dark-factory-implement.md` | Rewrite Phase 5 (memory write rules) to add write bar, provisional tier, cap check, invalidation path; fix mawk-incompatible awk; add Phase 1 filter note |
| `.archon/commands/dark-factory-refine.md` | Rewrite Phase 5 (memory write rules) with same new rubric; add Phase 1 filter note |
| `.archon/commands/dark-factory-plan.md` | Update Phase 3 `$MEMORY_CONTEXT` builder to filter `[PROVISIONAL]` and `[INVALID]` lines |

---

## Task 1: Measure baseline, audit and prune all 5 memory files (R1)

**Files:** `.archon/memory/architecture.md`, `.archon/memory/backend-patterns.md`, `.archon/memory/codebase-patterns.md`, `.archon/memory/dark-factory-ops.md`, `.archon/memory/frontend-patterns.md`

- [ ] **Step 1: Record baseline counts**

  Run and record the output (paste into the PR description):

  ```bash
  echo "=== Baseline entry counts ==="
  for f in .archon/memory/*.md; do
    count=$(grep -c '^\- \[' "$f" || true)
    echo "$f: $count entries ($(wc -l < "$f") lines)"
  done
  ```

  Expected baseline (approximate):

  | File | Current entries | Current lines |
  |------|-----------------|---------------|
  | `architecture.md` | ~11 | ~35 |
  | `backend-patterns.md` | ~18 | ~54 |
  | `codebase-patterns.md` | ~6 | ~26 |
  | `dark-factory-ops.md` | ~45 | ~130 |
  | `frontend-patterns.md` | ~20 | ~60 |

- [ ] **Step 2: Apply the audit rubric to each file**

  For every `- [PATTERN]`, `- [AVOID]`, or `- [FIX]` bullet across all 5 files, classify it as:

  | Verdict | Criterion | Action |
  |---------|-----------|--------|
  | **keep** | Correct, general beyond one run, reusable, decision-changing for a future agent | Leave unchanged |
  | **fix** | True fact, but mis-stated or imprecisely worded | Rewrite the entry in-place; keep it |
  | **demote** | Correct but factory-environment trivia (bash dialect quirks, awk compatibility edge cases, tool version-specific CLI flags, one-off debugging steps) | Delete the entry |
  | **drop** | Wrong, stale, redundant, or so situational it cannot recur | Delete the entry |

  **Key demote candidates in `dark-factory-ops.md`** (verify each, delete if they fit):
  - Entries about `mawk` 3-arg `match()` incompatibility — factory trivia; captured separately in the command file fix
  - Entries about `grep -c` returning exit code 1 on zero matches — generic bash trivia
  - Entries about `set -euo pipefail` inheriting into test scripts — generic bash trivia
  - Entries about `if/fi` returning 0 with no `else` branch — generic bash trivia
  - Entries about `repowise` version-specific subcommand names — version-specific trivia that will rot
  - Entries about PDF extraction via `pdfminer.six` — situational one-off, unlikely to recur
  - Entries about self-contained HTML for analysis docs — too specific to one deliverable
  - Entries about inline Python in bash functions — generic bash technique, not factory-specific

  **Correctness verification requirement:** Any "keep" entry that asserts runtime behavior (i.e., "X does Y when Z") must be quickly verified against the current codebase or a `docker exec` before being kept. Any claim that cannot be confirmed in under 2 minutes should be downgraded to `[PROVISIONAL]` (add to the provisional section — see Step 4) or dropped.

  **Near-duplicate merge:** If two entries cover ≥ 90% of the same ground, merge them into one combined entry. Do not keep both.

  **Do not write verdict notes into the files themselves** — they go in the PR description only.

- [ ] **Step 3: Apply all edits to the 5 files**

  Edit each file directly. For "demote" and "drop" verdicts, delete the full bullet line including its trailing inline comment. For "fix" verdicts, rewrite the entry in-place.

  After editing, verify no orphaned inline comments (`<!--`) or half-deleted bullet fragments remain:

  ```bash
  for f in .archon/memory/*.md; do
    echo "=== $f ==="
    grep -n '<!--' "$f" | grep -v 'PROVISIONAL\|evidence:\|bootstrap\|issue:\|source:'  && echo "(check above for orphaned comments)"
    echo ""
  done
  ```

- [ ] **Step 4: Add the `<!-- PROVISIONAL -->` footer section to each file**

  Append the following block to the bottom of each memory file (after all existing content):

  ```markdown
  ---
  <!-- PROVISIONAL — entries below are from a single observed run; unverified.
       Do not rely on these as authoritative guidance. They are excluded from
       plan/implement prompt injection except as advisory context.
       Each will be promoted to [PATTERN] on second-run confirmation (different issue number) or dropped at TTL. -->
  ```

  At this stage no actual provisional entries are added — the section is empty. It will be populated by future implement runs.

- [ ] **Step 5: Verify post-audit counts meet targets**

  ```bash
  echo "=== Post-audit entry counts ==="
  for f in .archon/memory/*.md; do
    auth_count=$(grep -c '^\- \[PATTERN\]\|^\- \[AVOID\]\|^\- \[FIX\]' "$f" || true)
    prov_count=$(grep -c '^\- \[PROVISIONAL\]' "$f" || true)
    echo "$f: $auth_count authoritative + $prov_count provisional ($(wc -l < "$f") lines)"
  done
  ```

  Required targets (ceilings — fewer is better):

  | File | Target authoritative entries |
  |------|------------------------------|
  | `architecture.md` | ≤ 10 |
  | `backend-patterns.md` | ≤ 20 |
  | `codebase-patterns.md` | ≤ 10 |
  | `dark-factory-ops.md` | **≤ 30** (currently ~44 — must drop ≥ 14) |
  | `frontend-patterns.md` | ≤ 20 |

  If `dark-factory-ops.md` is still above 30 after Step 3, continue demoting/dropping until the cap is met. Drop by priority: factory-trivia first, then oldest by date. Note: the actual baseline count in `dark-factory-ops.md` is ~44 entries, so at least 14 must be dropped to reach 30.

- [ ] **Step 6: Commit**

  ```bash
  # Record before/after for PR description
  for f in .archon/memory/*.md; do echo "$f"; done  # already captured in Steps 1 and 5

  git add .archon/memory/
  git commit -m "memory: audit and prune (issue #254)"
  ```

  The PR description must include the before/after table (entry counts + line counts per file) and a one-line rationale for each entry classified as "fix", "demote", or "drop" (kept entries need no rationale).

---

## Task 2: Rewrite implement Phase 5 + add Phase 1 filter note (R2–R5)

**Files:** `.archon/commands/dark-factory-implement.md`

- [ ] **Step 1: Verify the current Phase 5 range**

  ```bash
  grep -n "^## Phase 5:" .archon/commands/dark-factory-implement.md
  grep -n "^## Phase 6:" .archon/commands/dark-factory-implement.md
  ```

  Expected: Phase 5 starts at line ~160, Phase 6 at line ~215.

- [ ] **Step 2: Verify the mawk-incompatible awk is present (the bug we're fixing)**

  ```bash
  grep -n ', arr)' .archon/commands/dark-factory-implement.md
  # Also check the capture reference:
  grep -n 'arr\[1\]' .archon/commands/dark-factory-implement.md
  ```

  Expected: two matches — the current `match($0, /regex/, arr)` call (ending `, arr)`) and `arr[1]` capture. These are the buggy gawk-only lines per `.archon/memory/dark-factory-ops.md` `[AVOID]` entry on awk compatibility (issue #149).

- [ ] **Step 3: Replace Phase 5 entirely**

  Replace from `## Phase 5: MEMORY UPDATE` through the last line before `## Phase 6:` with the following text:

  ```markdown
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

  ```

- [ ] **Step 4: Add Phase 1 load filter note**

  After the list of "If the issue touches..." read instructions in Phase 1 (currently ending around line 34 with the dark-factory-ops.md bullet), add the following note:

  ```markdown
  When reading memory files, skip entries tagged `[PROVISIONAL]` and `[INVALID]` — they are
  unverified or invalidated and must not be used as authoritative guidance. Treat the
  `<!-- PROVISIONAL -->` fenced section as advisory context only, never as settled fact.
  ```

- [ ] **Step 5: Verify the changes**

  ```bash
  # Confirm new Phase 5 heading is present
  grep -n "^### Write bar\|^### Entry types\|^### Per-file authoritative\|^\- \[PROVISIONAL\]" \
    .archon/commands/dark-factory-implement.md | head -10

  # Confirm 3-arg awk match is gone (was the mawk bug)
  grep -n ', arr)' .archon/commands/dark-factory-implement.md && echo "FAIL: 3-arg match still present" || echo "OK: 3-arg match removed"

  # Confirm 2-arg awk form is present
  grep -n "RSTART+8" .archon/commands/dark-factory-implement.md && echo "OK: 2-arg mawk-compatible form present"

  # Confirm Phase 1 filter note was added
  grep -n "PROVISIONAL.*unverified\|skip entries tagged" .archon/commands/dark-factory-implement.md
  ```

- [ ] **Step 6: Commit**

  ```bash
  git add .archon/commands/dark-factory-implement.md
  git commit -m "feat(factory): revamp implement Phase 5 memory write rules (issue #254)"
  ```

---

## Task 3: Rewrite refine memory-write block + add Phase 1 filter note (R2–R5, R6)

**Files:** `.archon/commands/dark-factory-refine.md`

> **Note on refine structure:** Unlike the implement command which has a standalone Phase 5 for memory, `dark-factory-refine.md` places memory writes inside **step 6 of Phase 5 (SPEC WRITING)**. There is no separate memory phase. Use the anchor strings `"What to write and where:"` and the PATTERN+AVOID pair format block — not phase numbers — to locate the insertion points.

- [ ] **Step 1: Locate the memory-write block and the awk script in refine**

  ```bash
  grep -n "^## Phase 5:\|^## Phase 6:\|What to write and where\|, arr)" .archon/commands/dark-factory-refine.md
  ```

  Expected: Phase 5 = SPEC WRITING (~line 67), Phase 6 = PUBLISH. The memory-write block starts at step 6 ("Append memory entries...") around line ~81. The mawk-incompatible 3-arg `match()` appears around lines 90–91.

- [ ] **Step 2: Fix the awk expiry script (same mawk bug as in implement)**

  Locate the awk block inside the memory-write section of Phase 5 SPEC WRITING (around lines 87–95 in refine). Replace:

  ```awk
  match($0, /expires:([0-9]{4}-[0-9]{2}-[0-9]{2})/, arr)
  if (arr[1] < today) next
  ```

  With the mawk-compatible 2-arg form:

  ```awk
  found=match($0, /expires:[0-9]{4}-[0-9]{2}-[0-9]{2}/)
  if (found) { expiry_date=substr($0, RSTART+8, 10); if (expiry_date < today) next }
  ```

- [ ] **Step 3: Add the default-to-nothing write bar**

  Immediately before the "**What to write and where:**" block (step 6 of Phase 5 SPEC WRITING), insert:

  ```markdown
  **Write bar — default to nothing:**

  Before adding any entry, ask: "Would a future agent make a materially different architectural
  decision because of this entry, compared to reading `CLAUDE.md` and `ARCHITECTURE.md` alone?"
  If no → skip. Do not add entries that record trivial Q&A or patterns already documented
  elsewhere. Most refinement runs add zero memory entries.
  ```

- [ ] **Step 4: Add provisional tier + cap check**

  After the PATTERN+AVOID pair format block (step 6a in Phase 5 SPEC WRITING), add:

  ```markdown
  **Provisional tier for empirical claims (R2):**

  If an architectural decision depends on an empirically-observed runtime behavior (e.g.,
  "this service behaves like X when Y"), write it as `[PROVISIONAL]` in the provisional
  section of the target file rather than as a top-level `[PATTERN]`. Use the same
  `evidence:` format and provisional section structure as the implement agent.

  **Per-file entry cap (R4):**

  After appending to `architecture.md`, count authoritative entries:

  ```bash
  COUNT=$(grep -c '^\- \[PATTERN\]\|^\- \[AVOID\]\|^\- \[FIX\]' .archon/memory/architecture.md || true)
  if [ "$COUNT" -gt 30 ]; then
    echo "WARNING: architecture.md has $COUNT entries (cap: 30). Drop oldest/lowest-signal before committing."
  fi
  ```
  ```

- [ ] **Step 5: Add Phase 1 filter note to refine**

  In Phase 1 of the refine command (where memory files are read), locate the instruction to read `.archon/memory/architecture.md` (and other memory files). After the read instructions, add:

  ```markdown
  When reading memory files, skip entries tagged `[PROVISIONAL]` and `[INVALID]` — treat
  them as unverified or invalidated. Do not base architectural decisions on provisional
  entries; they require cross-run confirmation before becoming authoritative.
  ```

- [ ] **Step 6: Verify**

  ```bash
  # Confirm mawk fix applied
  grep -n ', arr)' .archon/commands/dark-factory-refine.md && echo "FAIL: 3-arg match still present" || echo "OK"
  grep -n "RSTART+8" .archon/commands/dark-factory-refine.md && echo "OK: 2-arg form present"

  # Confirm write bar added
  grep -n "default to nothing\|Most refinement runs add zero" .archon/commands/dark-factory-refine.md

  # Confirm provisional tier added
  grep -n "Provisional tier\|provisional section\|\[PROVISIONAL\]" .archon/commands/dark-factory-refine.md

  # Confirm Phase 1 filter note
  grep -n "skip entries tagged\|PROVISIONAL.*unverified" .archon/commands/dark-factory-refine.md
  ```

- [ ] **Step 7: Commit**

  ```bash
  git add .archon/commands/dark-factory-refine.md
  git commit -m "feat(factory): revamp refine Phase 5 memory write rules (issue #254)"
  ```

---

## Task 4: Update plan consume-side injection filters (R6)

**Files:** `.archon/commands/dark-factory-plan.md`

- [ ] **Step 1: Locate the `$MEMORY_CONTEXT` builder block**

  ```bash
  grep -n "MEMORY_CONTEXT\|cat .archon/memory" .archon/commands/dark-factory-plan.md
  ```

  Expected: the bash block starting around line 41 with `MEMORY_CONTEXT=""`.

- [ ] **Step 2: Audit all consume sites across all command files (R6 audit)**

  ```bash
  # Broad scan — classify every reference to .archon/memory in command files
  grep -rn '\.archon/memory' .archon/commands/
  ```

  Classify each hit:
  - **Shell injection** (e.g. `cat .archon/memory/...`, `$(...memory/...)`, `<(grep .../memory/...)`) → needs the `grep -v` shell filter; only `dark-factory-plan.md` is expected here.
  - **Git pathspec exclusion** (e.g. `':!.archon/memory/**'`) → not a consume site; skip.
  - **Phase 1 Read instruction** (e.g. "Read `.archon/memory/codebase-patterns.md`") → covered by the Phase 1 skip-note added in Tasks 2 and 3; no shell filter needed.

  Expected result: only `dark-factory-plan.md` has shell-level cat/injection. The implement and refine commands load memory via Read-tool instructions in Phase 1 — those are filtered by the "skip [PROVISIONAL]/[INVALID]" notes added in Tasks 2 and 3, not by shell `grep -v`. No shell filter is added to implement/refine because there is no shell cat to filter.

- [ ] **Step 3: Replace the `$MEMORY_CONTEXT` builder block**

  Replace the entire bash block (from `MEMORY_CONTEXT=""` through the closing backtick of the code fence) with:

  ```bash
  MEMORY_CONTEXT=""

  # Filter out [PROVISIONAL] and [INVALID] lines so unverified/invalidated entries
  # are excluded from authoritative prompt context (R6).
  _filter_memory() {
    grep -v '^\- \[PROVISIONAL\]\|^\- \[INVALID\]' "$1"
  }

  # architecture.md is always included if it exists
  if [ -f ".archon/memory/architecture.md" ]; then
    MEMORY_CONTEXT="$MEMORY_CONTEXT\n\n### From .archon/memory/architecture.md\n$(_filter_memory .archon/memory/architecture.md)"
  fi

  # Backend area — extract the Component field from the spec file header
  SPEC_COMPONENT=$(grep -m1 '^\*\*Component' "$SPEC_FILE" | sed 's/.*: //')
  if echo "$SPEC_COMPONENT" | grep -qE "models/|routers/|services/|tasks/"; then
    MEMORY_CONTEXT="$MEMORY_CONTEXT\n\n### From .archon/memory/backend-patterns.md\n$(_filter_memory .archon/memory/backend-patterns.md)"
  fi

  # Frontend area
  if echo "$SPEC_COMPONENT" | grep -q "frontend/src/"; then
    MEMORY_CONTEXT="$MEMORY_CONTEXT\n\n### From .archon/memory/frontend-patterns.md\n$(_filter_memory .archon/memory/frontend-patterns.md)"
  fi

  # Docker / infrastructure area
  if echo "$SPEC_COMPONENT" | grep -qE "docker-compose|Dockerfile|dark-factory/"; then
    MEMORY_CONTEXT="$MEMORY_CONTEXT\n\n### From .archon/memory/dark-factory-ops.md\n$(_filter_memory .archon/memory/dark-factory-ops.md)"
  fi
  ```

  > **Implementation note:** The `_filter_memory` shell function uses `grep -v` to strip `[PROVISIONAL]` and `[INVALID]` bullet lines before pasting into the architect prompt. The `<!-- PROVISIONAL -->` section header and `---` separator will remain in the output — that's intentional, as they provide context that the section exists without including unverified entries. Per spec A4, this filtering is done here (by the orchestrating shell logic), not by the subagent.

- [ ] **Step 4: Verify**

  ```bash
  # Confirm old cat calls are gone
  grep -n "cat .archon/memory" .archon/commands/dark-factory-plan.md && echo "FAIL: bare cat still present" || echo "OK: no bare cat"

  # Confirm filter function present
  grep -n "_filter_memory\|grep -v.*PROVISIONAL.*INVALID" .archon/commands/dark-factory-plan.md

  # Confirm all 4 memory files still covered
  grep -n "architecture.md\|backend-patterns.md\|frontend-patterns.md\|dark-factory-ops.md" \
    .archon/commands/dark-factory-plan.md | grep "_filter_memory"
  ```

- [ ] **Step 5: Commit**

  ```bash
  git add .archon/commands/dark-factory-plan.md
  git commit -m "feat(factory): filter PROVISIONAL/INVALID entries from memory context injection (issue #254)"
  ```

---

## Task 5: Verify footprint reduction and format correctness

- [ ] **Step 1: Final entry count and line count**

  ```bash
  echo "=== Final memory footprint ==="
  for f in .archon/memory/*.md; do
    auth=$(grep -c '^\- \[PATTERN\]\|^\- \[AVOID\]\|^\- \[FIX\]' "$f" || true)
    prov=$(grep -c '^\- \[PROVISIONAL\]' "$f" || true)
    inv=$(grep -c '^\- \[INVALID' "$f" || true)
    echo "$f: $auth authoritative, $prov provisional, $inv invalid ($(wc -l < "$f") lines)"
  done
  echo "=== Total lines ==="
  cat .archon/memory/*.md | wc -l
  ```

  Required:
  - `dark-factory-ops.md`: ≤ 30 authoritative entries
  - All files combined: substantially fewer total lines than the baseline of 305 (target ≤ ~200 after prune)
  - No `[PROVISIONAL]` bullet entries yet (provisional section exists but is empty — only the header comment is present)

- [ ] **Step 2: Verify provisional section format in every memory file**

  ```bash
  for f in .archon/memory/*.md; do
    echo "=== $f ==="
    tail -6 "$f"
    echo ""
  done
  ```

  Each file should end with:
  ```
  ---
  <!-- PROVISIONAL — entries below are from a single observed run; unverified.
       Do not rely on these as authoritative guidance. They are excluded from
       plan/implement prompt injection except as advisory context.
       Each will be promoted to [PATTERN] on second-run confirmation (different issue number) or dropped at TTL. -->
  ```

- [ ] **Step 3: Verify mawk fix in both command files**

  ```bash
  grep -rn ', arr)' .archon/commands/dark-factory-implement.md .archon/commands/dark-factory-refine.md \
    && echo "FAIL: 3-arg gawk match() still present" \
    || echo "OK: no 3-arg match() remaining"

  grep -rn "RSTART+8" .archon/commands/dark-factory-implement.md .archon/commands/dark-factory-refine.md
  # Expected: 2 matches — one per file
  ```

- [ ] **Step 4: Verify consume-side filter is in place**

  ```bash
  grep -c "_filter_memory\|grep -v.*PROVISIONAL" .archon/commands/dark-factory-plan.md
  # Expected: ≥ 2 (function definition + calls)
  ```

- [ ] **Step 5: Final commit if any cleanup is needed**

  ```bash
  git status  # should show clean or only .archon/ changes
  # If any final tweaks: git add .archon/ && git commit -m "memory: final cleanup (issue #254)"
  ```

  Then record before/after stats for the PR description:

  ```bash
  echo "=== Before/After Summary for PR ==="
  echo "Before: 5 files, ~305 lines, ~38 KB, ~100 authoritative entries (see baseline in Task 1 Step 1)"
  echo "After:"
  wc -l .archon/memory/*.md
  wc -c .archon/memory/*.md
  for f in .archon/memory/*.md; do
    echo "$f: $(grep -c '^\- \[PATTERN\]\|^\- \[AVOID\]\|^\- \[FIX\]' "$f" || true) authoritative entries"
  done
  ```
