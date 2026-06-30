# Dark Factory — Memory Quality Evaluation Harness

**Date:** 2026-06-30
**Status:** design
**Issue:** #653
**Epic:** #643 (Dark Factory memory system)
**Depends on:** `memory_retrieve.py` (#646), `memory_write.py` (#648), memory integration (#652)

## Problem

The flat-file memory system (`memory_retrieve.py`, `memory_write.py`) was wired into the Dark
Factory gates in #652. We have no objective measure of whether retrieval surfaces the right
lessons when a factory agent runs against files that a prior regression touched. Without a
baseline metric, we cannot detect regressions in retrieval quality as the corpus evolves.

This ticket **measures** the system as merged. It does not change `memory_retrieve.py`,
`memory_write.py`, or any retrieval behavior.

## Requirements

1. **Read-only** — no modifications to `memory_retrieve.py`, `memory_write.py`, or any
   `.archon/memory/` file outside of adding the report artifact.
2. **Runnable harness** — `dark-factory/scripts/eval_memory_quality.py` that, for each
   scorable regression in `dark-factory/evals/factory-failures.jsonl`, calls
   `memory_retrieve.py --phase <role> --files <files>` and checks whether the relevant
   memory entry is surfaced.
3. **Objective scorecard** — recall over the scorable subset, reported as pass/fail against
   `PASS_THRESHOLD = 0.5`. Written to `dark-factory/evals/memory-quality-report.md`.
4. **Corpus-gap reporting** — substantive regressions with no matching memory entry are
   reported separately as a coverage-gap metric (not counted in the recall denominator).
5. **pytest suite** — `dark-factory/tests/test_eval_memory_quality.py` covering all scoring
   logic functions. At least 5 scored regression cases must be exercisable in CI without
   network or Docker access (unit tests only; the full harness uses subprocess).
6. **No semantic retrieval** — no vector DB, no embedding model, no agentmemory backend.

## Architecture

### Ground-truth construction

**Source:** `.archon/memory/*.md` — entries carry `<!-- issue:#NNN path:some/prefix/ -->` 
inline metadata written by `memory_write.py`. 

Ground truth is the set of `(issue_num, entry_text, path_tag)` triples extracted by scanning
each memory file for lines matching `- [TAG] ... <!-- ... issue:#NNN ... -->`. The issue tag
format is `issue:#NNN` (with hash prefix), per corpus convention.

An issue number in factory-failures.jsonl matches a memory entry when
`int(issue_tag.lstrip('#')) == regression['issue']`.

### `--files` input for retrieval

For each matched memory entry:
- If the entry carries a `path:` metadata tag: use that tag value as `--files` (newline-sep).
  This exercises the path filter against a realistic file prefix for that entry.
- If the entry has no `path:` tag: use an empty string for `--files` (the filter is a no-op
  for entries without path restrictions — they always pass the area/path filter).

This approach is self-contained and directly tests whether the path filter narrows retrieval
to the relevant entry without requiring git history or network access.

### Regression filtering

Before scoring, `factory-failures.jsonl` is deduplicated by issue number (taking the
most-substantive postmortem entry when duplicates exist) and filtered:

- **Infrastructure filter**: entries whose postmortem matches known infra patterns
  (`"session limit"`, `"resets.*UTC"`) are excluded from both the scored set and the
  corpus-gap metric. These are runtime events, not codeable lessons.
- **Deduplicate**: multiple entries per issue are collapsed to one. The filtering predicate
  is checked per-issue: if ALL entries for an issue are infrastructure failures, the whole
  issue is excluded.

Filtered count is reported in the scorecard for transparency.

### Hit detection

A regression case is a "hit" (pass) when `memory_retrieve.py` subprocess output contains
the body of the relevant memory entry (substring match on the entry text, stripped of inline
metadata comments). Case-insensitive prefix-to-first-space matching handles minor whitespace
normalization.

### Scoring and report

```
Recall   = hits / scorable_N
Pass     = recall >= PASS_THRESHOLD (0.5)
Gap rate = unevaluable_N / substantive_N
```

Where:
- `scorable_N` = regressions with at least one matching memory entry
- `hits` = scorable cases that returned a hit
- `unevaluable_N` = substantive (non-infra) regressions with no matching memory entry
- `substantive_N` = total after infra filter

The report (`memory-quality-report.md`) emits:
- Header with timestamp and git SHA
- Per-case table: `issue | title | phase | matched_entry | result (HIT/MISS) | files_used`
- Aggregate: recall, scorable_N, hits, unevaluable_N, gap_rate, PASS/FAIL

### Script interface

```bash
# Run the eval and write report
python3 dark-factory/scripts/eval_memory_quality.py \
  [--memory-dir .archon/memory] \
  [--failures dark-factory/evals/factory-failures.jsonl] \
  [--output dark-factory/evals/memory-quality-report.md] \
  [--retrieve-script dark-factory/scripts/memory_retrieve.py]

# Exit 0 on PASS (recall >= 0.5), exit 1 on FAIL
```

### pytest scope

`dark-factory/tests/test_eval_memory_quality.py` uses `tmp_path` and no subprocess calls.
Covers:
- `is_infrastructure_failure()` — session-limit and UTC-reset postmortem patterns
- `parse_memory_entries()` — `issue:#NNN`, `path:` tag extraction from mock `.md` files
- `check_hit()` — substring matching with/without trailing metadata
- `compute_scorecard()` — recall, gap rate, pass/fail at PASS_THRESHOLD
- `filter_and_deduplicate_regressions()` — per-issue infra collapse

## Alternatives Considered

**A. Use git log / GitHub API for `--files`**  
Accurate file sets, but requires network access at eval time and the referenced branches are
often deleted. Rejected: adds external dependency to a read-only measurement script.

**B. Use empty files for all cases**  
Simpler, but the path filter is a no-op for empty files — the test becomes "does any entry
exist" rather than "does path filtering surface the right entry." Rejected: doesn't test the
core retrieval mechanism.

**C. Semantic / LLM-based relevance scoring**  
Could surface entries that don't have exact `issue:#NNN` tags. Rejected explicitly by the
issue owner; contradicts the flat-file-only scope.

## Assumptions

- Memory entries written by `memory_write.py` for a specific issue carry an `issue:#NNN`
  tag in their inline metadata. Entries written without an issue tag (pre-scoping corpus)
  have no ground-truth linkage and are excluded from scoring.
- `memory_retrieve.py` is callable as a subprocess in the eval environment (it's in the
  same `dark-factory/scripts/` directory with no heavyweight deps).
- The `PASS_THRESHOLD = 0.5` is a configurable top-of-file constant; ratcheting it upward
  over time as the corpus grows is the intended use case.

## Open Questions (non-blocking)

- **OQ1**: Should the report be committed as a snapshot artifact, or regenerated on each run
  and gitignored? The issue says "committed artifact" — the script writes and the factory
  stages it. Future runs overwrite it, which is fine for a baseline-comparison workflow.
- **OQ2**: If `scorable_N < 5` (fewer than 5 regressions have memory entries), the spec's
  "evaluate at least 5 historical issues/PRs" acceptance criterion falls back to the
  corpus-gap section covering those extra issues narratively. A future issue can add manual
  annotations to the jsonl to increase coverage.

## Target Files

```
dark-factory/scripts/eval_memory_quality.py       (new)
dark-factory/tests/test_eval_memory_quality.py    (new)
dark-factory/evals/memory-quality-report.md       (generated artifact, committed)
```

No changes to `memory_retrieve.py`, `memory_write.py`, `.archon/memory/*.md`,
`dark-factory/evals/factory-failures.jsonl`, or any gate scripts.
