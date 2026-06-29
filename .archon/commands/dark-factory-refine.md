---
description: Refine a GitHub issue into a design spec using multi-agent brainstorming
argument-hint: (no arguments - reads issue context from workflow)
---

# Dark Factory — Refine

**Workflow ID**: $WORKFLOW_ID

---

## CRITICAL: Skip Guard

If the issue has any of these labels, STOP immediately and exit with code 0 (not an error):
- `spec-pending-review` — already processed
- `needs-discussion` — waiting for human input
- `epic` — needs manual decomposition

## SCOPE BOUNDARY

This command's only authorized file outputs are:
- Documents under `docs/superpowers/specs/` (the spec file)
- Entries under `.archon/memory/` (optional architecture memory)

Do NOT create or modify any other files. Do NOT implement code, write tests, or edit configuration.

---

## Phase 1: LOAD

1. Read `CLAUDE.md` for development rules, architecture, and conventions
2. Read `ARCHITECTURE.md` for service topology and module map
3. The issue context has been fetched by the workflow. It is available in the conversation.
4. Read `/opt/refinement-skills/orchestrator-prompt.md` for your process instructions
5. Read `/opt/refinement-skills/product-owner-prompt.md` — you will pass this to subagents
6. Read `/opt/refinement-skills/config.yaml` for pipeline configuration
7. Compute the affected file set and define `load_memory` for path-tag filtering:

```bash
AFFECTED=$(git diff --name-only origin/main...HEAD 2>/dev/null || echo "")

REPO_ROOT=$(git rev-parse --show-toplevel)
source "${REPO_ROOT}/dark-factory/scripts/agent_roles.sh"
AGENT_ID="${AGENT_ID_REFINEMENT}"

# load_memory: reads a memory file; project-tagged entries for other projects are excluded;
# path-tagged entries are filtered against AFFECTED; entries with neither tag are always included.
# When AFFECTED is empty (new branch, nothing implemented yet), all entries are included.
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

8. Run `load_memory codebase-patterns.md` and include its filtered output in context — global lessons from past runs.
9. Run `load_memory architecture.md` and include its filtered output in context — prior architectural decisions written by previous refine runs (if the file exists).
10. Run area-specific memory filtering relevant to the issue's domain: if the issue touches backend code run `load_memory backend-patterns.md`; if it touches frontend code run `load_memory frontend-patterns.md`; if it touches Docker or infrastructure run `load_memory dark-factory-ops.md`.

When reading memory files, skip entries tagged `[PROVISIONAL]` and `[INVALID]` — treat them
as unverified or invalidated. Do not base architectural decisions on provisional entries; they
require cross-run confirmation before becoming authoritative.

`AVOID` entries are especially relevant to spec decisions — if a memory entry marks an approach as AVOID, do not specify that approach in the spec without an explicit justification.

### If this is a re-run (feedback present in issue comments after a previous refinement report)

Read the latest comments after any "Refinement Pipeline" report. Treat these as additional requirements from the user. Do NOT start from scratch — build on the previous spec if one exists on this branch.

## Phase 2: PRE-FLIGHT

Check the issue body length. If fewer than 20 characters:
1. Post a comment: "This issue needs more detail before it can be refined. Please add a description of what you'd like to build and any constraints."
2. Add `needs-discussion` label: `gh issue edit $ISSUE_NUM --add-label needs-discussion`
3. Exit cleanly

## Phase 3: CONTEXT ASSEMBLY

Build a context package by exploring the codebase:
1. Identify which area of the codebase the issue touches (backend models? services? frontend pages?)
2. Read the relevant existing files to understand current patterns
3. Assemble this into a context summary you will pass to every product-owner subagent

## Phase 4: BRAINSTORMING LOOP

Follow the process in `orchestrator-prompt.md`:
1. Formulate one clarifying question at a time
2. For each question, spawn a product-owner subagent using the Agent tool:
   - `description`: "Product owner: <short question summary>"
   - `prompt`: Content of `product-owner-prompt.md` with the $ISSUE_CONTEXT, $QA_HISTORY, and $QUESTION placeholders replaced with actual values
   - `model`: `claude-opus-4-8` — **always** pin this subagent to Opus 4.8 (do not let it inherit the orchestrator's model)
   - The subagent needs Glob, Grep, and Read tools to explore the codebase
3. If the subagent returns a response starting with `UNCERTAIN:`:
   - Post a comment on the issue explaining the question and context gathered so far
   - Run: `gh issue edit $ISSUE_NUM --add-label needs-discussion`
   - Write a brief summary to `$ARTIFACTS_DIR/refinement-status.md` noting the abort reason
   - Exit cleanly (exit code 0)
4. Record the answer and continue until you have enough information

## Phase 5: SPEC WRITING

1. Propose 2-3 approaches with trade-offs
2. Select the best approach based on Q&A answers and codebase patterns
3. Write the spec to `docs/superpowers/specs/YYYY-MM-DD-<topic>-design.md` following existing spec format:
   - Overview / problem statement
   - Requirements (from Q&A)
   - Architecture / approach
   - Alternatives considered
   - Open questions (non-blocking)
   - Assumptions (flagged)
4. Self-review: placeholder scan, consistency check, scope check, ambiguity check. Fix inline.
5. Run the OOS gate — detect and revert any files committed outside the refine allowlist:
   ```bash
   ALLOWED_PREFIXES="docs/superpowers/specs/ .archon/memory/"
   OOS_FILES=$(git diff --name-only origin/main HEAD 2>/dev/null | while read -r f; do
     ALLOWED=false
     for prefix in $ALLOWED_PREFIXES; do
       case "$f" in "$prefix"*) ALLOWED=true; break;; esac
     done
     $ALLOWED || echo "$f"
   done)
   if [ -n "$OOS_FILES" ]; then
     echo "OOS gate: excising out-of-scope files: $OOS_FILES"
     for f in $OOS_FILES; do
       if git show origin/main:"$f" > /dev/null 2>&1; then
         git checkout origin/main -- "$f"
       else
         git rm -f --cached "$f" 2>/dev/null; rm -f "$f"
       fi
     done
     git commit -m "chore: excise out-of-scope files from refine run (#$ISSUE_NUM)" --allow-empty
     mkdir -p "$ARTIFACTS_DIR"
     echo "$OOS_FILES" | while read -r f; do
       echo "- $f: removed by refine OOS gate (should not have been created/modified)" >> "$ARTIFACTS_DIR/out-of-scope.md"
     done
   fi
   ```
   Retain `$OOS_FILES` for use in the Phase 6 comment.
6. Commit the spec

7. Append memory entries to `.archon/memory/`:

   **Expiry cleanup (run before appending to any file):**
   For each target memory file you are about to write, remove expired entries first:
   ```bash
   TODAY=$(date +%Y-%m-%d)
   TARGET=".archon/memory/architecture.md"  # replace with actual target file
   awk -v today="$TODAY" '
     /expires:[0-9]{4}-[0-9]{2}-[0-9]{2}/ {
       found=match($0, /expires:[0-9]{4}-[0-9]{2}-[0-9]{2}/)
       if (found) { expiry_date=substr($0, RSTART+8, 10); if (expiry_date < today) next }
     }
     { print }
   ' "$TARGET" > "$TARGET.tmp" && mv "$TARGET.tmp" "$TARGET"
   ```

   **Write bar — default to nothing:**

   Before adding any entry, ask: "Would a future agent make a materially different architectural
   decision because of this entry, compared to reading `CLAUDE.md` and `ARCHITECTURE.md` alone?"
   If no → skip. Do not add entries that record trivial Q&A or patterns already documented
   elsewhere. Most refinement runs add zero memory entries.

   **What to write and where:**

   a. For each architectural decision made during Phase 4 Q&A where a trade-off was explicitly weighed (why approach X over approach Y): append a PATTERN+AVOID pair to `.archon/memory/architecture.md`:
      ```
      - [PATTERN] <the chosen approach and why it is correct> <!-- issue:#$ISSUE_NUM date:$(date +%Y-%m-%d) expires:$(date -d '+6 months' +%Y-%m-%d 2>/dev/null || date -v+6m +%Y-%m-%d) source:refine -->
      - [AVOID] <the rejected approach and the concrete reason it was rejected> <!-- issue:#$ISSUE_NUM date:$(date +%Y-%m-%d) expires:$(date -d '+6 months' +%Y-%m-%d 2>/dev/null || date -v+6m +%Y-%m-%d) source:refine -->
      ```

   **Append-only rule:** New memory entries must be written with shell appends:
     echo '- [PATTERN] ...' >> .archon/memory/architecture.md
   NEVER use the Write or Edit tool on a memory file to add new entries — doing so risks
   regenerating the file from a stale in-context copy and silently dropping existing entries.

   The ONLY operations permitted to remove or modify existing lines are:
     (a) the awk expiry-cleanup block (entries with a past `expires:` date)
     (b) R4 cap-drop (explicit drop of the oldest/lowest-signal entries when COUNT > 30)
     (c) R5 invalidation (rewrite `[PATTERN]` → `[INVALID: reason]` for a single entry)
   Each of these operations must touch ONLY the targeted lines and leave all other lines verbatim.

   **Provisional tier for empirical claims (R2):**

   If an architectural decision depends on an empirically-observed runtime behavior (e.g.,
   "this service behaves like X when Y"), write it as `[PROVISIONAL]` in the provisional
   section at the bottom of the target file rather than as a top-level `[PATTERN]`. Include
   an `evidence:` field in the inline comment describing how the behavior was observed
   (e.g., `evidence:docker-exec`). Max 10 provisional entries per file. Provisional entries
   are promoted to `[PATTERN]` only when a *different issue number* confirms the same behavior.

   **Per-file entry cap (R4):**

   After appending to any memory file, count authoritative entries:
   ```bash
   COUNT=$(grep -c '^\- \[PATTERN\]\|^\- \[AVOID\]\|^\- \[FIX\]' .archon/memory/architecture.md || true)
   if [ "$COUNT" -gt 30 ]; then
     echo "WARNING: architecture.md has $COUNT entries (cap: 30). Drop oldest/lowest-signal before committing."
   fi
   ```

   b. For any codebase convention discovered during Phase 3 context assembly that is absent from `CLAUDE.md` and absent from `ARCHITECTURE.md`: append a `[PATTERN]` entry to the relevant area file (`backend-patterns.md`, `frontend-patterns.md`, or `dark-factory-ops.md`) with `source:refine`.

   c. Before appending any entry, check for duplicates: `grep -F "<core sentence of the new entry>" .archon/memory/architecture.md`. If a matching line exists, skip that entry.

   d. Do NOT write to `codebase-patterns.md` from the refine agent — that file is maintained by the implement agent for runtime-proven lessons only.

   **Post-write verification backstop** — run after all R3/R4 operations and before `git add .archon/memory/`:

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

   e. If any entries were added, commit:
      ```bash
      git add .archon/memory/
      git commit -m "memory: architectural decisions from refine #$ISSUE_NUM"
      ```
      If no entries were added (Q&A produced no novel trade-offs and Phase 3 found nothing new), skip the commit.

## Phase 6: PUBLISH

1. Determine the current branch name: `BRANCH=$(git branch --show-current)`
2. Build GitHub links:
   - Spec link: `https://github.com/omniscient/markethawk/blob/$BRANCH/<spec-file-path>` (e.g. `docs/superpowers/specs/2026-05-13-topic-design.md`)
   - Branch link: `https://github.com/omniscient/markethawk/tree/$BRANCH`
3. Check if the issue carries the `direct-to-pr` label:
   ```bash
   IS_DIRECT_TO_PR=$(gh issue view $ISSUE_NUM --repo omniscient/markethawk \
     --json labels --jq '.labels[].name' | grep -q "direct-to-pr" && echo "yes" || echo "no")
   SPEC_GRACE=$(python3 -c "import yaml; d=yaml.safe_load(open('.claude/skills/refinement/config.yaml')); print(d.get('direct_to_pr',{}).get('spec_grace_minutes',30))" 2>/dev/null || echo "30")
   ```
   If `IS_DIRECT_TO_PR=yes`, prepend the following note to the "### Next Steps" section of the comment (replacing `$SPEC_GRACE` with the actual value):
   > ⏩ **Auto-advancing in ~`$SPEC_GRACE` min** unless you comment — the scheduler will move this to **Refined** automatically once the grace window elapses. Leave a comment to re-run the spec or override the direction.
4. Post a summary comment on the issue:
   ```
   ## Refinement Pipeline — Spec Generated

   **Spec:** [<spec-file-path>](https://github.com/omniscient/markethawk/blob/<BRANCH>/<spec-file-path>)
   **Branch:** [`<BRANCH>`](https://github.com/omniscient/markethawk/tree/<BRANCH>)
   <!-- If OOS_FILES is non-empty, include this line: -->
   > ⚠️ **OOS excision**: The following files were created outside the refine scope and were reverted before publishing: `$OOS_FILES`. Scope-spillover tickets may be filed automatically.

   ### Summary
   <2-3 sentence overview>

   ### Brainstorming Q&A

   Include the FULL dialogue from Phase 4. For each question-answer pair:

   > **Q:** <the question you asked>
   > **A:** <the product owner's answer>

   This lets the reviewer see the reasoning and assumptions behind the spec.

   ### Requirements
   <bulleted list of key requirements>

   ### Approach
   <1-2 sentences on chosen approach>

   ### Assumptions
   <bulleted list if any>

   ### Next Steps

   <!-- If IS_DIRECT_TO_PR=yes, insert the auto-advance note here (from step 3 above) -->

   - ✅ **Approve spec** — move the issue to the **Refined** column on the project board. The scheduler will automatically trigger plan generation.
   - ✏️ **Request changes** — leave a comment on this issue with your feedback, then re-run:
     ```bash
     docker compose --profile factory run --rm dark-factory "Refine issue #$ISSUE_NUM"
     ```
   - ❓ **Need to discuss** — add the `needs-discussion` label to pause automation.

   ---
   *Posted by MarketHawk Refinement Pipeline*
   ```
6. Write status to `$ARTIFACTS_DIR/refinement-status.md`:
   ```
   STATUS: SPEC_COMPLETE
   SPEC_PATH: <path>
   BRANCH: <branch>
   QUESTIONS_ASKED: <count>
   ```
