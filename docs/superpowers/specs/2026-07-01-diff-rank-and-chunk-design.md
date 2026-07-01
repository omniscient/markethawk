# Diff Rank and Chunk — conformance and code-review prompt optimization

**Status:** design
**Date:** 2026-07-01
**Issue:** #669
**Epic:** #663 (Dark Factory platform)

## Problem

Both the conformance gate (`dark-factory-conformance.md`) and code-review gate (`dark-factory-code-review.md`) feed diffs to reviewer subagents with a hard `head -1000` line truncation. On a large branch, this silently drops code that a reviewer should see — and it consumes the same token budget regardless of whether the diff is 12 lines in a trading-path file or 1000 lines of test boilerplate. The result is wasted tokens on low-value content and missed coverage of high-value content.

## Requirements

From the issue acceptance criteria and Q&A:

- **R1** — Emit `$ARTIFACTS_DIR/diff-ranking.json` on every run.
- **R2** — Reviewer subagents receive high-risk chunks first, under a configurable token cap for non-safety-sensitive content.
- **R3** — Low-risk (test-only) files are summarized as a one-liner in the ranked output rather than fully included.
- **R4** — Safety-sensitive files (security/auth/trading/infra paths, codeindex hotspot files) bypass the token cap entirely and are always included in full.
- **R5** — Existing conformance and code-review gate semantics remain unchanged: the gates continue to receive one diff string and prompt the same subagents in the same way.
- **R6** — The script fails open on error: on any exception, the caller falls back to the fmt-filtered or raw diff, and the gate proceeds normally.

## Architecture

### New file: `dark-factory/scripts/diff_rank.py`

Pure Python, stdlib-only (no external deps), matching the style of `fmt_hunk_filter.py` and `gate_blast_radius.py`.

**CLI:**
```bash
python3 dark-factory/scripts/diff_rank.py \
  --diff <path>           \  # path to the input diff (fmt-filtered or raw)
  --artifacts-dir <dir>   \  # write diff-ranking.json here
  [--config <yaml>]          # default: .claude/skills/refinement/config.yaml
  [--spec-file <path>]       # optional: spec/plan file to identify spec-named files
  [--hotspots <path>]        # default: docs/codeindex-hotspots.md
```

Writes the ranked diff string to **stdout**. Exits 0 on success; on any error, exits non-zero (caller detects and falls back).

**Config keys read (from `--config`):**

| Key | Default | Purpose |
|-----|---------|---------|
| `token_optimization.diff.max_review_tokens` | 6000 | Token cap for non-critical content |
| `blast_radius.hotspot_score_floor` | 5.0 | Blast-radius threshold for safety-sensitive classification |

No new config keys are added; the script reuses the existing `token_optimization.diff.max_review_tokens` ceiling already consumed by the code-review gate.

### Risk classification

Each file in the diff is assigned one of four risk tiers:

**`critical` — bypass token cap, always include in full:**
- Path matches any `SAFETY_PATH_PATTERNS` (hardcoded, mirroring `gate_blast_radius.MIGRATION_SEED_AUTH_PATTERNS`):
  - `alembic/versions/` (migrations)
  - `backend/app/routers/auth` (auth endpoints)
  - `backend/app/core/auth` (auth core)
  - `app/services/trading` (trading service)
  - `app/tasks/trading.py` (trading tasks)
  - `dark-factory/` (factory self-modification guard — includes baked scripts)
- OR blast score ≥ `hotspot_score_floor` from `docs/codeindex-hotspots.md`

**`high` — fill token budget in rank order after critical:**
- Path mentioned in the spec file content (`--spec-file`)
- `backend/app/routers/` (public API endpoints)
- `requirements*.txt` or `package*.json` or `pyproject.toml` (dependency changes)
- Files not otherwise classified with blast score ≥ 2.0 (elevated but below floor)

**`medium` — fill remaining budget after high:**
- Anything with > 50 added+deleted lines not in a higher tier

**`low` — summarized, never fill budget:**
- Test files: `test_*.py`, `*/tests/**`, `conftest.py`, `*.test.ts`, `*.spec.ts`
- Anything not matched by the above tiers

Note: `*.md` files are already excluded by the `git diff -- ':!*.md'` call in both gates, so they never appear in `diff_rank.py`'s input.

### Blast-radius reuse

`diff_rank.py` imports `parse_hotspots` from `gate_blast_radius` (same package — `sys.path.insert` pattern matching `fmt_hunk_filter.py`'s self-contained import pattern, or a direct function import). The two scripts must agree on which files are hotspots and at what score floor.

### Ranking algorithm and token budget

Token estimation: `len(text_chars) / 4` (character-based approximation, matching the `context_budget.py` convention).

1. **Collect and classify** all files from the diff.
2. **Emit critical files** in full (ordered by blast score descending, then lines changed descending). Record their token cost but do NOT count it against the cap.
3. **Remaining budget** = `max_review_tokens`.
4. **Fill high** tier files in rank order (spec-named first, then API, then deps, then blast-scored). Emit in full while budget remains. Truncate and summarize on budget exhaustion.
5. **Fill medium** tier files in rank order (lines changed descending). Emit in full while budget remains.
6. **Summarize all low** tier files and all remaining over-budget files:
   ```
   # [SUMMARIZED: low-risk test-only] tests/test_scanner.py — +42/-3 (2 hunks)
   ```
   For budget-exhausted high/medium files:
   ```
   # [SUMMARIZED: budget-exhausted] backend/app/services/stock_data.py — +120/-30 (5 hunks)
   ```

**Header line** (first line of stdout, matching the `[Pre-triage]` convention):
```
# [diff-rank: N files — 2 critical / 3 high / 2 medium / 1 low, est. 4200 tokens (cap 6000)]
```

### Output: `diff-ranking.json`

```json
{
  "token_cap": 6000,
  "estimated_tokens_emitted": 4200,
  "critical_tokens": 1800,
  "residual_tokens": 2400,
  "files": [
    {
      "path": "backend/app/routers/auth.py",
      "risk_class": "critical",
      "signals": ["auth_path"],
      "blast_score": null,
      "lines_added": 45,
      "lines_removed": 12,
      "hunk_count": 3,
      "included": "full",
      "estimated_tokens": 600
    },
    {
      "path": "tests/test_scanner.py",
      "risk_class": "low",
      "signals": ["test_file"],
      "blast_score": null,
      "lines_added": 42,
      "lines_removed": 3,
      "hunk_count": 2,
      "included": "summary",
      "estimated_tokens": 0
    }
  ]
}
```

### Integration: conformance gate

In `dark-factory-conformance.md`, Phase 3.0, after `fmt_hunk_filter.py` sets `TRIAGED_DIFF`:

```bash
# Rank and chunk the fmt-filtered diff (fail-open)
RANK_IN=$(mktemp /tmp/rank_in_XXXXXX.txt)
printf '%s' "$TRIAGED_DIFF" > "$RANK_IN"
RANKED=$(python3 dark-factory/scripts/diff_rank.py \
  --diff "$RANK_IN" \
  --artifacts-dir "$ARTIFACTS_DIR" \
  --config ".claude/skills/refinement/config.yaml" \
  ${SPEC_FILE:+--spec-file "$SPEC_FILE"} \
  2>/tmp/diff_rank_err.txt) \
  && TRIAGED_DIFF="$RANKED" \
  || echo "diff_rank: ranking failed ($(cat /tmp/diff_rank_err.txt)) — using fmt-filtered diff"
rm -f "$RANK_IN"
```

The `head -1000` on `RAW_DIFF` in Phase 3.0 is removed; budget is managed by `diff_rank.py` instead.

### Integration: code-review gate

In `dark-factory-code-review.md`, Phase 2, replace the current pipe:

```bash
# Current:
git diff main...HEAD -- ':!*.lock' ':!*.md' ... | head -1000 > "$ARTIFACTS_DIR/review_diff.txt"

# After:
RANK_IN=$(mktemp /tmp/rank_in_XXXXXX.txt)
git diff main...HEAD -- ':!*.lock' ':!*.md' \
  ':!.archon/memory/**' ':!codeindex.json' ':!symbolindex.json' \
  ':!docs/codeindex-hotspots.md' ':!docs/database-schema.md' \
  2>/dev/null > "$RANK_IN"
python3 dark-factory/scripts/diff_rank.py \
  --diff "$RANK_IN" \
  --artifacts-dir "$ARTIFACTS_DIR" \
  --config ".claude/skills/refinement/config.yaml" \
  2>/tmp/diff_rank_err.txt > "$ARTIFACTS_DIR/review_diff.txt" \
  || {
    echo "diff_rank: ranking failed ($(cat /tmp/diff_rank_err.txt)) — using raw diff"
    cp "$RANK_IN" "$ARTIFACTS_DIR/review_diff.txt"
  }
rm -f "$RANK_IN"
```

The truncation log ("diff truncated to 1000 lines") in Phase 2 is removed; the `diff-ranking.json` artifact serves as the budget log.

### Tests: `dark-factory/tests/test_diff_rank.py`

Unit tests covering (no git/subprocess needed — all in-process):
- Risk classification: `critical` for auth-path file, migration file, hotspot file; `high` for router file and spec-named file; `low` for test file.
- Token budget: critical files bypass cap; high files fill budget; low-risk files always summarized.
- Summary line format: `# [SUMMARIZED: low-risk test-only] path — +N/-M (K hunks)`
- Budget-exhausted summary: `# [SUMMARIZED: budget-exhausted] ...`
- Header line: `# [diff-rank: ...]` is first line of output.
- `diff-ranking.json`: written to `--artifacts-dir` with correct structure.
- Fail-open: on missing `--hotspots` file, proceeds without blast scores.
- Empty diff input: stdout is empty, `diff-ranking.json` written with 0 files.
- `parse_hotspots` import: same result as calling `gate_blast_radius.parse_hotspots` directly (no divergence).

## Alternatives considered

### Alternative 1 — Metadata-only JSON, gate-side composition

`diff_rank.py` emits only `diff-ranking.json`; each gate script reads it and composes its own prompt slice from the raw diff. Rejected: this puts brittle JSON-parsing + diff-slicing logic inside prose-format command files (`.archon/commands/`), duplicates it across two gates, and cannot be unit-tested in isolation. The existing `fmt_hunk_filter.py → $TRIAGED_DIFF` pipeline is the established pattern; this alternative diverges from it for no gain.

### Alternative 2 — Per-gate token cap configuration

Add separate `conformance_max_review_tokens` and `code_review_max_review_tokens` config keys. Rejected: the existing `token_optimization.diff.max_review_tokens` key is already used by the code-review stage and both gates reviewing the same diff at the same depth is the right default. A single cap keeps the config minimal (size M scope).

### Alternative 3 — Variable cap for safety-sensitive files (expand cap, don't bypass)

Double the token cap when a safety-sensitive file is detected. Rejected: the existing `gate_blast_radius.py` pattern establishes that safety signals trigger unconditional responses (HUMAN_REQUIRED) rather than budget scaling. A doubled cap could still silently truncate a very large trading-path file; hard bypass does not.

## Open questions (non-blocking)

- **Q1:** If multiple spec files exist (both the design spec and a plan), should `--spec-file` accept a glob or multiple paths? The implementation can default to the most recent spec in `docs/superpowers/specs/` for simplicity.
- **Q2:** Should the `# [diff-rank: ...]` header line be stripped before the diff string is passed to the reviewer (to avoid LLM confusion about a non-standard diff header)? Acceptable either way; the header is informational and does not affect diff parsing.

## Assumptions

- **[A1]** `docs/codeindex-hotspots.md` may not be present (the factory does not always regenerate it pre-gate). The script uses an empty-set fallback — no blast-radius signal, but all other signals still apply. Flagged because this means some hotspot files are not classified `critical` on runs without a fresh codeindex.
- **[A2]** The token estimator (`chars / 4`) is a known approximation. Its accuracy is sufficient for budget allocation (avoiding 10× over-budget diffs) but not precise enough to guarantee exact token counts in the `diff-ranking.json`.
- **[A3]** `.archon/commands/dark-factory-conformance.md` and `dark-factory-code-review.md` are clone-read files (not baked into the image), so updating them does not require a Docker image rebuild.
- **[A4]** The `SPEC_FILE` variable is available in the conformance gate's Phase 3 context (it is the spec file located in Phase 2). The code-review gate does not currently have a spec file reference and passes no `--spec-file` argument (the spec-named signal is omitted for code-review; conformance already has the spec).
