# Comment Digest for Continue Runs

**Status:** design
**Date:** 2026-07-01
**Issue:** #668
**Epic:** #663 (Dark Factory platform — token efficiency)

## Problem

When `Continue issue #N` runs, the `continue` context scenario in `context_pack.py` passes ALL issue comments and PR reviews verbatim to Claude — including stale bot-authored factory run reports, cost reports, failure notices, and post-mortems. For an issue with several factory iterations this can be thousands of tokens of irrelevant noise. The human feedback the factory must act on is buried under bot churn, inflating cost and making the `summarize-feedback` Haiku node summarize the wrong content.

## Requirements

1. **`dark-factory/scripts/comment_digest.py`** — new pure-Python deterministic script:
   - Reads `issue.json` (produced by `fetch-issue` DAG node)
   - Identifies the latest factory-boundary comment via body-footer matching (same `bot_re` pattern as `scheduler.sh`)
   - Extracts human-authored issue comments and PR review bodies after the boundary
   - Groups surviving `pr_inline_comments` by `.path`, listing `line: body` per file
   - Emits `$ARTIFACTS_DIR/comment-digest.md` (structured verbatim output, no LLM call)
   - Emits an explicit no-feedback sentinel when no human comments survive

2. **New DAG node `digest-comments`** in `archon-dark-factory.yaml`:
   - `depends_on: [fetch-issue]`
   - `when: "$parse-intent.output.intent == 'continue'"` (continue only)
   - Produces `$ARTIFACTS_DIR/comment-digest.md`
   - `budget-implement` and `implement` nodes add it to their `depends_on`

3. **`_SECTION_REGISTRY` update** in both `context_budget.py` and `context_pack.py`:
   - `continue` entry changes from `["claude_md", "architecture_md", "issue_context", "comments", "memory_context", "pr_reviews"]`
     to `["claude_md", "architecture_md", "issue_context", "memory_context", "comment_digest"]`
   - Both `comments` and `pr_reviews` are removed from `continue` (both are replaced by `comment_digest`)
   - New `comment_digest` section handlers in both files (analogous to `memory_context` handlers)
   - `_read_comments()` and `_read_pr_reviews()` remain unchanged for refine/plan/implement

4. **`summarize-feedback` DAG node** updated to read `$ARTIFACTS_DIR/comment-digest.md` as input instead of raw `$fetch-issue.output`, so it summarizes pre-filtered human content only

5. **Tests** in `dark-factory/tests/test_comment_digest.py` covering:
   - No-feedback case (all comments are factory-authored, nothing after boundary)
   - Issue-comment feedback (human comment after last factory marker)
   - PR-review feedback (human PR review body after boundary)
   - Inline-comment feedback (human inline comments grouped by file path)

## Architecture / Approach

### `comment_digest.py` — deterministic filter, no LLM

Follows the same pattern as `context_pack.py` and `context_budget.py`: pure stdlib Python, no external dependencies, no LLM calls. The script's only job is to filter and structure; the existing `summarize-feedback` Haiku node handles prose summarization downstream.

**Bot detection.** Use body-footer string matching, not author login. All factory comments are posted via the same GitHub PAT as human collaborators (per `scheduler.sh:443` comment), so author login cannot reliably distinguish them. Match against the same footer set `scheduler.sh` uses:

```
"Posted by MarketHawk Refinement Pipeline"
"Posted by MarketHawk Backlog Scheduler"
"Posted by MarketHawk Dark Factory"
"Updated by MarketHawk Dark Factory"
"dark-factory-cost-report"
"Posted by MarketHawk Epic Autopilot"
```

**Algorithm:**
1. Scan `issue.json[".comments"]` in reverse-chronological order; find the last comment whose `.body` contains any marker string → factory boundary
2. Collect `.comments` after the boundary whose body does NOT match any marker → human issue comments
3. Collect `.pr_reviews` review-summary bodies whose timestamp > boundary and body does not match any marker → human PR reviews
4. Collect `.pr_inline_comments` with `created_at` > boundary timestamp, group by `.path`
5. Emit `comment-digest.md` (see output format below)
6. If nothing survives steps 2–4, emit the no-feedback sentinel

**Output format (`comment-digest.md`):**

```markdown
<!-- comment-digest: cutoff=<ISO8601> marker="<matched footer substring>" -->
## Marker

Latest factory comment at <cutoff>: "<first 80 chars of body>…"

## Human feedback since last factory run

### Issue comments

- [<created_at>] <body>

### PR review comments

- [<created_at>] <body>

### Inline review comments by file

#### <path>
- Line <N>: <body>
```

When no human feedback exists:
```markdown
<!-- comment-digest: cutoff=<ISO8601> marker="<matched footer substring>" -->
<!-- no-feedback: true -->
No human feedback found after last factory marker.
```

When no factory marker exists at all (first run, no prior factory comments), include all comments verbatim with a note that no boundary was found.

### DAG node (`archon-dark-factory.yaml`)

```yaml
- id: digest-comments
  bash: |
    ISSUE=$(jq -r '.resolved_number' "$ARTIFACTS_DIR/issue.json")
    _CLONE="${CLONE_DIR:-.}"
    python3 "$_CLONE/dark-factory/scripts/comment_digest.py" \
      --issue-json "$ARTIFACTS_DIR/issue.json" \
      --out "$ARTIFACTS_DIR/comment-digest.md"
    echo "comment-digest.md written for issue #${ISSUE}"
  depends_on: [fetch-issue]
  when: "$parse-intent.output.intent == 'continue'"
  timeout: 15000
```

Update `budget-implement` and `implement` `depends_on` to add `digest-comments`. Update `summarize-feedback` prompt to reference the digest file content (via `$ARTIFACTS_DIR/comment-digest.md`) rather than inlining the raw `$fetch-issue.output`.

### `context_budget.py` and `context_pack.py` changes

Registry change (both files must stay in lockstep):
```python
"continue": ["claude_md", "architecture_md", "issue_context", "memory_context", "comment_digest"],
```

New probe/read functions follow the `memory_context` handler pattern:
- `_probe_comment_digest(digest_file)` in `context_budget.py`
- `_read_comment_digest(digest_file)` in `context_pack.py`

Both scripts get a `--comment-digest-file` arg (default: `<artifacts-dir>/comment-digest.md`).

The assembled `context-pack.md` for `continue` runs will include `## comment_digest` instead of `## comments` and `## pr_reviews`. Update `test_context_pack.py` and `test_context_budget.py` to assert:
- `continue` scenario emits `comment_digest`, not `comments` or `pr_reviews`
- `implement` scenario still emits `comments` (unchanged)

## Alternatives Considered

### Inline digest logic inside `_read_comments()` for continue

Rejected. `_read_comments()` currently has no scenario awareness and is shared by refine, plan, and implement. Adding a `scenario` parameter plus branching would couple a `continue`-specific concern into a shared function, complicating future changes. The `sec ==` dispatch model in both context scripts already handles per-scenario routing via the registry; a distinct `comment_digest` key is the natural extension.

### LLM summarization inside `comment_digest.py`

Rejected. All context-assembly helpers (`context_pack.py`, `context_budget.py`, `architecture_slice.py`, `token_estimate.py`) are deterministic Python with no API calls. LLM calls live exclusively in DAG nodes. Adding an LLM call here would also make the script slow, non-deterministic, and untestable without a real API key — contrary to the existing test patterns in `test_context_pack.py` and `test_context_budget.py` which use only fixtures.

### Keep `pr_reviews` as a separate unfiltered section alongside `comment_digest`

Rejected. `_read_pr_reviews()` in `context_pack.py:92-103` does a raw `json.dumps(pr) + json.dumps(inline)` with zero filtering. Keeping it alongside the digest would leak stale bot-authored PR reviews into the continue context and defeat the token savings. The acceptance criteria explicitly require the digest to contain "inline-comment paths", making inline comments the digest's responsibility.

## Open Questions

- Should `bot_re` be centralized (e.g. in a shared `dark_factory_constants.py`) to prevent future drift between `scheduler.sh` and `comment_digest.py`? A quality improvement, non-blocking for #668; can be a follow-on ticket.

## Assumptions

- All comments (issue, PR review, inline) in `issue.json` are authored via the same GitHub PAT, making author login unreliable for bot detection — per `scheduler.sh` comment at the `bot_re` definition.
- The `summarize-feedback` Haiku node's current prompt ("Focus only on human-authored feedback — ignore any comments from 'Dark Factory' or other bots") is superseded by the digest supplying pre-filtered content; the prompt may be simplified or removed in a follow-on.
- The `dark-factory-implement` command file's Phase 2 "continue" handling references issue feedback. It will also need to read from `comment-digest.md` (via the assembled `context-pack.md`) after this change — confirmed by the registry update.
- `pr_inline_comments` timestamps are ISO 8601 strings (`created_at` field, per the `gh api` output format in `fetch-issue`).
