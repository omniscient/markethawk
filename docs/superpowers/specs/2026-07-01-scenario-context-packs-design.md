# Scenario-Specific Context Packs for Dark Factory Phases

**Status:** design  
**Date:** 2026-07-01  
**Issue:** #665  
**Epic:** #663 (Dark Factory platform — context budget)  
**Size:** M (1-4 hours)

## Problem

Each Dark Factory phase command (`dark-factory-refine.md`, `dark-factory-plan.md`, etc.) assembles its context ad-hoc in Phase 1: a bash call to `memory_retrieve.py`, individual file reads of `CLAUDE.md` / `ARCHITECTURE.md`, issue JSON parsing, spec/impl/diff reads. This duplication makes it hard to reason about what each phase receives, impossible to measure overruns before runtime, and fragile against scenario-specific changes.

`context_budget.py` (issue #687) already probes the same sources and emits per-section token telemetry, but it does **not** assemble or return the actual text content. There is no single, deterministic artifact that represents "the full context pack for scenario X."

## Decision

Add `dark-factory/scripts/context_pack.py` — a content-assembly companion to `context_budget.py`. It produces two artifacts in `$ARTIFACTS_DIR`:

- **`context-pack.md`** — assembled Markdown containing all included sections for the scenario, headed with level-2 section labels, prompt-ready for agent injection.
- **`context-pack.json`** — a manifest with per-section status, token counts, source file hashes, the overall token budget, utilization percentage, and an `over_budget` flag.

The existing `.archon/commands/*` files are **not** modified in this issue. They "can consume" the pack but command migration is deferred to a follow-on issue per AC wording ("can consume packs without changing scheduler semantics").

## Requirements

1. New file `dark-factory/scripts/context_pack.py` (no other files created or modified).
2. CLI interface mirrors `context_budget.py`:
   ```
   python3 context_pack.py --scenario <name> --issue-num <N> --run-id <id> \
     --artifacts-dir <dir> --clone-dir <dir> \
     [--spec-file <path>] [--memory-file <path>] [--issue-json <path>] \
     [--impl-file <path>] [--diff-file <path>] \
     [--spec-component <component>] [--changed-files <f1> <f2> ...] \
     [--labels <l1> <l2> ...] \
     [--out-md <path>] [--out-json <path>]
   ```
3. Supported scenario names: `refine`, `plan`, `implement`, `continue`, `conformance`, `code-review`.  
   - The issue's `review_context` label corresponds to `code-review` in the existing registry.
4. Per-scenario section ordering reuses `_SECTION_REGISTRY` from `context_budget.py` (imported directly; Python does not enforce private-name access restriction across modules in the same package).
5. Default output paths (if `--out-md` / `--out-json` are not passed): `$artifacts_dir/context-pack.md` and `$artifacts_dir/context-pack.json`.
6. Assembled `context-pack.md` wraps each included section with a Markdown level-2 header matching the section key (e.g. `## claude_md`, `## architecture_md`, `## memory_context`).
7. Architecture section content is produced by calling `architecture_slice.slice_architecture()` with the supplied `--changed-files`, `--labels`, `--spec-component`, and `--clone-dir` — same call that `context_budget.py` makes.
8. Diff section applies `DIFF_LINE_CAP = 1000` line truncation (imported constant from `context_budget.py`) and appends a `<!-- truncated at 1000 lines -->` comment when truncated.
9. Sections that are missing, empty, or whose source file cannot be read are silently dropped and marked `status: dropped` in the JSON manifest.
10. Token budget: `BUDGET_TOKENS = 200_000` (imported from `context_budget.py`). If the assembled pack exceeds this, set `over_budget: true` in the JSON and emit a warning line to stderr. Do **not** drop sections — enforcement is deferred behind the `token_optimization.enforce_budgets` flag in `config.yaml`.
11. `context-pack.json` schema (mirrors `context_budget.py` output schema):
    ```json
    {
      "schema_version": 1,
      "scenario": "refine",
      "run_id": "...",
      "issue_number": 42,
      "generated_at": "<ISO-8601 UTC>",
      "budget_tokens": 200000,
      "estimated_input_tokens": 45000,
      "utilization_pct": 22.5,
      "over_budget": false,
      "sections": {
        "claude_md":       { "status": "included", "tokens": 12000, "file_hash": "..." },
        "architecture_md": { "status": "included_slice", "tokens": 3000, "component": "dark-factory", ... },
        "memory_context":  { "status": "dropped", "tokens": 0, "reason": "empty_or_missing" }
      },
      "included_sections": ["claude_md", "architecture_md", ...],
      "dropped_sections":  ["memory_context"],
      "source_file_hashes": { "CLAUDE.md": "...", "ARCHITECTURE.md": "..." }
    }
    ```
12. Tests in `dark-factory/tests/test_context_pack.py` cover:
    - `refine` scenario: verifies `context-pack.md` is produced, contains expected section headers, token count > 0 in JSON.
    - `implement` scenario: verifies spec section is included when `--spec-file` is supplied; dropped when absent.
    - `code-review` scenario: verifies diff section is included with truncation when diff exceeds `DIFF_LINE_CAP`.
    - `over_budget` flag: verifies `over_budget: true` and stderr warning when assembled pack exceeds `BUDGET_TOKENS`.
    - Missing source files: verifies graceful drop (status=dropped, pack still produced for other sections).

## Architecture

```
dark-factory/scripts/
  context_budget.py          — existing telemetry probe (unchanged)
  context_pack.py            — NEW: content assembler (imports from context_budget)
  architecture_slice.py      — existing: called by context_pack for arch content
  token_estimate.py          — existing: called by context_pack for token counting
  memory_retrieve.py         — existing: output consumed by context_pack via --memory-file

dark-factory/tests/
  test_context_pack.py       — NEW: unit tests for pack generation
```

`context_pack.py` imports from `context_budget`:
- `_SECTION_REGISTRY` — scenario→section list mapping
- `BUDGET_TOKENS`, `DIFF_LINE_CAP` — shared constants
- `_read_text` — path-safe file reader

It imports from `architecture_slice`:
- `slice_architecture` — returns `SliceResult` with `.text` (content) and metadata fields

It imports `token_estimate` as `te` for `te.estimate_tokens()` and `te.hash_file()`.

### Content assembly flow

```python
def assemble_pack(scenario, ...) -> tuple[str, dict]:
    active = _SECTION_REGISTRY.get(scenario, [])
    parts = []     # (header, content) pairs for context-pack.md
    sections = {}  # section_key -> manifest dict for context-pack.json

    for sec in active:
        content = _read_section_content(sec, ...)  # dispatch to per-section reader
        if content:
            parts.append(f"## {sec}\n\n{content}\n")
            sections[sec] = {"status": "included", "tokens": te.estimate_tokens(content)}
        else:
            sections[sec] = {"status": "dropped", "tokens": 0, "reason": "..."}

    md = "\n".join(parts)
    total_tokens = sum(v["tokens"] for v in sections.values())
    over_budget = total_tokens > BUDGET_TOKENS
    if over_budget:
        print(f"WARNING: context pack {total_tokens} tokens exceeds budget {BUDGET_TOKENS}", file=sys.stderr)

    manifest = _build_manifest(scenario, sections, total_tokens, over_budget, ...)
    return md, manifest
```

Each section has a dedicated reader that matches the probing logic in `context_budget.py` (e.g. `_read_claude_md`, `_read_architecture_md`, `_read_issue_context`, `_read_diff`).

## Alternatives Considered

**Extend `context_budget.py` in-place:** Add assembly to the same file. Rejected — mixes telemetry and assembly concerns; the file is already 310 lines with a clear single responsibility (measure-only probe). Keeping them separate preserves that invariant and makes each file independently testable.

**Self-contained with duplicated registry:** `context_pack.py` owns its own copy of `_SECTION_REGISTRY`. Rejected — the section registry is the single source of truth for what each phase receives. Two copies would drift out of sync when scenarios evolve.

**Generate via `build_budget()` + separate pass:** Call `build_budget()` to produce `context-pack.json` (reusing the full measurement path) and then do a second pass to assemble text. Feasible, but produces two file I/O passes for the same sources. The cleaner path is a single `assemble_pack()` call that produces both artifacts.

## Open Questions (non-blocking)

- Should `context_pack.py` eventually replace `context_budget.py` (single tool, dual output), or remain a separate companion? Leaving as separate tools is fine for now; the merge decision belongs to a follow-on refactor.
- The `token_optimization.default_budget_tokens: 24000` in `config.yaml` is a per-scenario enforcement budget (currently measure-only), different from `BUDGET_TOKENS = 200_000` (full context window). Should `context_pack.py` read the per-scenario budget from config for the `over_budget` check? For now, use `BUDGET_TOKENS` (200k) to stay consistent with `context_budget.py`. Revisit when `enforce_budgets` flips to `true`.

## Assumptions

- `review_context` (issue naming) = `code-review` (registry key). The implementation uses `code-review` for CLI compatibility with `context_budget.py`.
- `context_budget._SECTION_REGISTRY` and helpers (`_read_text`, constants) are importable from `context_pack.py` via `import context_budget as cb` (same directory, same `sys.path.insert` pattern already used by `context_budget.py` itself).
- No changes to `.archon/commands/*` in this issue — that migration is a follow-on.
- `generated_at` uses `datetime.now(timezone.utc).isoformat()` consistent with `context_budget.py`.
