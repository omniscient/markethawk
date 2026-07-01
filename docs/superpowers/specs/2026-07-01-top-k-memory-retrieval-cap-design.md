# Top-k Memory Retrieval Cap — token-bounded ranked selection for Dark Factory memory v2

**Status:** design
**Date:** 2026-07-01
**Issue:** #667
**Epic:** #663
**Compatible with:** memory-v2 epic #643

## Problem

`memory_retrieve.py` dumps all passing entries (up to ~131 in the current corpus) into every agent prompt with no cap. The full unranked block can exceed 11 000 tokens — consuming a significant share of the 200 000-token context budget before any codebase context is loaded. The index path (`index.jsonl` + `records/`) already exists and sorts by path specificity then recency, but neither path enforces a count or token ceiling.

## Requirements

1. The index path must not return more than **8 authoritative entries** (PATTERN/AVOID/FIX, excludes PROVISIONAL/INVALID) per call.
2. The index path must not return more than **1 500 estimated tokens** of memory text per call.
3. Both caps apply simultaneously — whichever is hit first stops inclusion.
4. Ranking is a multi-factor sort: **(path specificity + label boost, created_at DESC)**, where label boost is +1 when the entry's `source_file` corresponds to a domain matched by one of the issue's labels.
5. The `--labels` CLI argument (currently "reserved, unused") must be wired through the retrieval stack and used to compute label boost.
6. The markdown fallback path stays unchanged — uncapped, unranked.
7. `memory-trace.json` must gain per-file fields: `entries_selected` (survived the cap) and `entries_dropped_by_cap`, plus run-level totals.
8. `context-budget.json`'s `memory_context` section must gain `entries_selected` and `entries_dropped` totals, sourced from the trace file when available.
9. All existing `test_memory_retrieve.py` tests must continue passing.

## Architecture and Approach

### Cap and ranking in the index path

The cap is applied inside `format_index_output()` before rendering. After sorting by `(specificity + label_boost, created_at)` DESC, iterate candidates greedily: include each entry if adding its estimated token cost keeps the running total below 1 500 and the running count below 8. Remaining entries are "dropped by cap."

Token estimation uses the existing `token_estimate.estimate_tokens(text)` helper (4 chars = 1 token), applied to the formatted entry string (`f"- [{kind}] {summary}"`).

### Label boost

Map issue labels to `source_file` using a label map that mirrors `architecture_slice.py`'s `_LABEL_COMPONENT_MAP`:

```python
_LABEL_SOURCE_BOOST_MAP = {
    "dark factory":     "dark-factory-ops.md",
    "dark-factory":     "dark-factory-ops.md",
    "frontend":         "frontend-patterns.md",
    "backend":          "backend-patterns.md",
}
```

Match case-insensitively (lowercase both label text and map keys), check by substring (`key in label_text`). If any label matches a `source_file`, entries from that file get `label_boost=1` added to their sort key. Global files (`codebase-patterns.md`, `architecture.md`) are not boosted — they are always loaded and the area-file filter is the correct mechanism for narrowing them.

### Threading labels

`--labels` in `memory_retrieve.py` is already parsed as a string (`default=""`). Change it to `nargs="*"` (a list of strings) to match the `context_budget.py` / `architecture_slice.py` calling convention. Thread `labels: list[str]` from `retrieve_memory()` → `scan_index()` / `format_index_output()`.

### Trace updates (`emit_memory_trace`)

`emit_memory_trace()` currently computes per-file `entries_total`, `entries_included`, `entries_filtered_out` from the markdown files independently of the index path. To capture post-cap counts, `retrieve_memory()` must return a retrieval result struct (or side-channel dict) that carries:

- `entries_selected`: how many entries survived the cap
- `entries_dropped_by_cap`: how many candidates were dropped by the cap

These are added to the `files_loaded[]` entries in `memory-trace.json` when the index path ran, and set to `entries_dropped_by_cap=0` when the markdown fallback ran.

Add run-level rollups to the trace root:
```json
{
  "entries_selected_total": 6,
  "entries_dropped_by_cap_total": 12
}
```

### Context-budget updates (`context_budget.py`)

The `memory_context` section probe (`_included(_read_text(memory_file), memory_file)`) already reads the memory-context.md file after it has been written. Add a parallel read of `memory-trace.json` from the artifacts dir (best-effort, fail-open):

```python
# If memory-trace.json is present in the artifacts dir, surface cap counts.
trace = _read_json(trace_path)
if trace:
    section["entries_selected"] = trace.get("entries_selected_total", 0)
    section["entries_dropped"] = trace.get("entries_dropped_by_cap_total", 0)
```

Since `context_budget.py` is often called before the memory-context.md is written (before the command session), these fields will be missing or zero in that pre-run budget call. Post-run telemetry consumers that call `context_budget.py` after the command session will see the correct values. This is acceptable — the constraint is documented in `context_budget.py` lines 204-206.

### No change to the markdown fallback

When `format_index_output()` is bypassed and `scan_markdown_files()` runs, `entries_dropped_by_cap=0` is emitted in the trace. The markdown output is returned as-is, unchanged. "Fall back safely to existing markdown behavior if ranking fails" means: if `scan_index()` raises `(OSError, ValueError)` or returns zero candidates, the existing fall-through to `scan_markdown_files()` is unchanged.

## Alternatives Considered

### A — Apply cap to both index and markdown paths

The markdown fallback path could also be capped. Rejected: the fallback exists for environments where the `index.jsonl` is absent (older environments, fresh clones). Capping a path that has no ranking would require arbitrary truncation of an unordered set, potentially dropping more-relevant entries silently. The accept criterion "fall back safely to existing markdown behavior" explicitly rules this out.

### B — Token-only cap (no count cap)

Skip the `k=8` count cap and enforce only the 1 500-token budget. Rejected: a token-only cap is susceptible to very long single entries consuming the whole budget. The dual cap (count OR tokens, whichever first) provides predictability for both dense and sparse corpora.

### C — Separate `--top-k` CLI flag and mode flag

Introduce a new `--top-k N` flag and a `--mode top-k|full` switch so callers can opt in. Rejected (YAGNI): all callers want the cap (the purpose of this issue is to stop dumping full files). Defaults of `TOP_K=8` and `TOKEN_BUDGET=1500` as named constants in `memory_retrieve.py` allow callers to override without a separate mode flag.

## Open Questions (non-blocking)

1. Should constants `TOP_K_DEFAULT = 8` and `TOKEN_BUDGET_DEFAULT = 1500` be promoted to CLI flags (`--top-k`, `--token-budget`) in a follow-up? Current issue scope says defaults only.
2. Should the `--labels` nargs change be backward-compatible with the current string callers? The existing callers (factory command prompts) pass labels as a space-separated bash expansion; switching to `nargs="*"` keeps that compatible as long as callers pass each label as a separate arg.

## Assumptions

- **[ASSUMED]** Callers of `memory_retrieve.py` pass labels as separate shell args (e.g. `--labels "Dark Factory" "performance"`), not as a comma-delimited string. If they currently pass a single comma-delimited string, the `nargs="*"` change would break callers and the string-split approach should be preserved.
- **[ASSUMED]** `entries_selected_total` + `entries_dropped_by_cap_total` fields in `memory-trace.json` are additive across files — this is consistent with the existing `files_loaded[]` per-file structure.
- **[ASSUMED]** The `context_budget.py` trace-read is best-effort: if `memory-trace.json` is absent (pre-run call), the fields are omitted rather than raising an error.
