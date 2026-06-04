# Dark Factory Progress Visibility

**Issue:** #48 — Dark Factory should be a bit more verbose as it progresses  
**Date:** 2026-05-13  
**Approach:** Workflow-level GitHub comments + terminal echoes (Approach A)

## Problem

The dark factory has two blind spots where the user gets no feedback:

1. **"Continue" flow**: After leaving PR feedback and running `Continue issue #N`, there's no acknowledgment of what feedback was understood, and the board status doesn't visibly reset (it stays "In Progress" from the entrypoint, but was "In Review" — the user can't tell anything changed).
2. **"Close" flow**: After running `Close issue #N`, there's silence between kickoff and the final "Done" comment. The user doesn't know if the merge/teardown process started.

The existing status moves (In Progress, In Review, Done) are fine for the main "new" flow. This design only targets the two gaps above, plus minor terminal echo improvements.

## Changes

### 1. New node: `acknowledge-continue`

**File:** `.archon/workflows/archon-dark-factory.yaml`  
**Position:** After `fetch-issue`, before `setup-branch`  
**Condition:** `intent == 'continue'`

This is implemented as two sequential nodes (Archon nodes are either `prompt` or `bash`, not both):

**Node 1a: `summarize-feedback` (Haiku prompt node):**  
Receives the PR review comments, PR inline comments, and latest issue comments from `fetch-issue` output. The prompt instructs Haiku to focus on human-authored comments posted after the most recent "Dark Factory Run" or "Dark Factory — " comment (ignoring factory-posted comments). Produces a 2-3 sentence summary of what the user is requesting.

**Node 1b: `acknowledge-continue` (bash node):**  
Posts a GitHub comment to the issue using the summary from `summarize-feedback`:

```markdown
## Dark Factory — Resuming work

**Feedback understood:**
[Haiku-generated summary from summarize-feedback node]

Working on it now. Next update when implementation is complete.

---
*Posted by MarketHawk Dark Factory*
```

**Terminal:** `echo "Posted feedback acknowledgment to issue #N"`

**Board status:** The entrypoint already moves the ticket to "In Progress" for all non-close intents (line 65-68 of `entrypoint.sh`), so this is covered. No additional board logic needed.

**Dependency chain:** `fetch-issue` -> `summarize-feedback` -> `acknowledge-continue` -> `setup-branch` (existing nodes unchanged, just new dependencies inserted).

### 2. New node: `close-announce`

**File:** `.archon/workflows/archon-dark-factory.yaml`  
**Position:** After `fetch-issue`, before `close-preview`  
**Condition:** `intent == 'close'`

A bash node that posts a GitHub comment:

```markdown
## Dark Factory — Closing issue

Merging PR and tearing down preview environment. This usually takes under a minute.

---
*Posted by MarketHawk Dark Factory*
```

**Terminal:** `echo "Closing issue #N — merging PR and tearing down preview..."`

**Dependency chain:** `fetch-issue` -> `close-announce` -> `close-preview` (existing `close-preview` logic unchanged).

### 3. Terminal echo additions

Minor `echo` lines added to existing workflow nodes that currently run silently:

| Node | Echo added |
|------|------------|
| `setup-branch` | `echo "Setting up branch for issue #N..."` |
| `push-and-pr` | `echo "Pushing branch and creating/updating PR..."` |
| `status-in-review` | `echo "Moving issue #N to In Review..."` |
| `report` | `echo "Posting summary to issue #N..."` |

Nodes that already echo (`preview-up`, `close-preview`) and Archon command nodes (`implement`, `validate`) are left unchanged.

## Files Modified

| File | Change |
|------|--------|
| `.archon/workflows/archon-dark-factory.yaml` | Add `summarize-feedback` node (Haiku prompt), add `acknowledge-continue` node (bash), add `close-announce` node (bash), update dependency chains, add echo lines to `setup-branch`, `push-and-pr`, `status-in-review`, `report` |

## Not in Scope

- Richer progress for the "new" flow (board status moves already cover it)
- Single-comment-with-live-updates pattern (over-engineered for 2 blind spots)
- Changes to `entrypoint.sh` (its existing echoes and board logic are sufficient)
- Changes to Archon commands (`dark-factory-implement.md`, `dark-factory-validate.md`)
