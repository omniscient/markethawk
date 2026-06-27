# Memory Import — seed structured backend from existing markdown

**Status:** design
**Date:** 2026-06-27
**Issue:** #649
**Epic:** #643 (Improve Dark Factory memory system using agent-native memory architecture)
**Phase:** Epic Phase 1 — non-invasive index (read only, no prompt changes)

## Problem

The Dark Factory memory layer lives as five human-readable markdown files in
`.archon/memory/`. Each file contains `- [KIND] lesson text <!-- metadata -->` entries
with structured metadata (issue, date, expires, source, path) embedded in inline comments.
The parent epic (#643) introduces a machine-queryable structured backend (JSONL index + per-record
JSON files) to enable scored retrieval, lifecycle maintenance, and run-level memory tracing.

Before the retriever (Phase 2) or writer (Phase 3) can be built, the existing ~129 entries
across five files must be imported into that backend without touching the markdown files and
without losing any entry's current state (kind, expiry, path tags, INVALID reasons,
PROVISIONAL status).

## Requirements

From the acceptance criteria and Q&A:

1. Parse all five `.archon/memory/*.md` files: `architecture.md`, `backend-patterns.md`,
   `codebase-patterns.md`, `dark-factory-ops.md`, `frontend-patterns.md`.
2. Extract every `- [KIND...] text <!-- metadata -->` entry (including `[INVALID: reason]`
   entries with embedded reasons and `[PROVISIONAL]` entries below the `---` separator).
3. Compute a **stable `id`** per entry: `sha256(source_filename + "\n" + normalized_text)[:16]`
   where `normalized_text` strips the `[KIND...]` bracket (including any embedded reason) and
   the trailing `<!-- ... -->` metadata comment, then collapses whitespace. The `id` must be
   invariant to kind-tag transitions (PROVISIONAL→PATTERN, PATTERN→INVALID) and minor
   metadata edits.
4. Write each record as ``.archon/memory/records/<id>.json``.
5. Maintain `.archon/memory/index.jsonl` — one line per record with the compact summary
   fields needed for retrieval scoring: `id`, `kind`, `scope`, `path_prefixes`,
   `confidence`, `expires_at`, `source_file`, `summary_snippet` (first 120 chars).
6. **Idempotency**: if `records/<id>.json` already exists, skip (do not overwrite). If its
   `index.jsonl` line is absent, append it. Never remove or overwrite existing lines.
7. Preserve `[INVALID]` entries with `kind: "INVALID"` and `confidence: 0.0`.
8. Preserve `[PROVISIONAL]` entries with `kind: "PROVISIONAL"` and `confidence: 0.4`.
9. Preserve expiry dates and path tags exactly as parsed.
10. Emit an import report to stdout: created / skipped / failed counts.
11. Support `--dry-run` flag: compute and print the report without writing any files.
12. Do NOT modify `.archon/memory/*.md` files under any circumstances.

## Record schema

```json
{
  "id": "a1b2c3d4e5f6g7h8",
  "project": "markethawk",
  "kind": "PATTERN",
  "scope": "backend",
  "path_prefixes": ["backend/app/routers/"],
  "summary": "SlowAPI @limiter.limit() requires the Request parameter to be named exactly `request` ...",
  "rationale": null,
  "evidence": [
    {"issue": 493, "source": "implement", "date": "2026-06-21", "evidence_tag": null}
  ],
  "confidence": 1.0,
  "expires_at": "2026-12-21",
  "retrieval_count": 0,
  "last_used_at": null,
  "supersedes": [],
  "superseded_by": null,
  "source_file": "backend-patterns.md"
}
```

### Field derivation rules

| Record field | Source |
|---|---|
| `id` | `sha256(source_filename + "\n" + normalized_text)[:16]` |
| `project` | hardcoded `"markethawk"` |
| `kind` | bracket tag: `PATTERN`, `AVOID`, `FIX`, `PROVISIONAL`, `INVALID` |
| `scope` | filename → scope map (see below) |
| `path_prefixes` | `path:` tag in metadata comment; `[]` if absent |
| `summary` | full lesson text with `[KIND...]` bracket and `<!-- -->` comment stripped |
| `rationale` | `null` (enrichment deferred to future pass) |
| `evidence` | array of `{issue, source, date, evidence_tag}` parsed from metadata comment |
| `confidence` | kind + source tiering (see below) |
| `expires_at` | `expires:YYYY-MM-DD` tag; `null` if absent |
| `retrieval_count` | `0` on import |
| `last_used_at` | `null` on import |
| `supersedes` | `[]` on import |
| `superseded_by` | `null` on import |
| `source_file` | basename of the source markdown file |

### Filename → scope map

| File | Scope |
|---|---|
| `architecture.md` | `"architecture"` |
| `backend-patterns.md` | `"backend"` |
| `frontend-patterns.md` | `"frontend"` |
| `dark-factory-ops.md` | `"dark-factory"` |
| `codebase-patterns.md` | `"codebase"` |

### Confidence tiering

| Condition | Confidence |
|---|---|
| `kind == "INVALID"` | `0.0` |
| `kind == "PROVISIONAL"` | `0.4` |
| `source == "implement"` | `1.0` |
| `source == "conformance"` | `1.0` |
| `source == "refine"` | `0.7` |
| `source == "code-review"` | `0.7` |
| `source == "bootstrap"` | `0.7` |
| unrecognized source | `0.7` |

### Evidence parsing

Parse all `issue:`, `date:`, `source:`, `evidence:`, `evidence2:` (and further numbered)
tags from the metadata comment. Construct one evidence object per `issue:` occurrence,
attaching the `evidence:` tag value (if any) as `evidence_tag`. Multi-evidence entries
(like the single `evidence2:` entry in `dark-factory-ops.md`) produce a two-element array.

## Architecture / approach

### Script: `dark-factory/scripts/memory_import.py`

Standalone Python 3, stdlib only (no dependencies beyond `hashlib`, `json`, `re`,
`pathlib`, `argparse`). Runs outside the factory container — can be executed locally or
inside any environment with read access to the repo.

**Invocation:**
```bash
# From repo root
python dark-factory/scripts/memory_import.py                  # write mode
python dark-factory/scripts/memory_import.py --dry-run        # preview only
python dark-factory/scripts/memory_import.py --memory-dir .archon/memory  # explicit path
```

**Algorithm:**

```
parse_entry(line, source_file) → MemoryRecord | None
  - match regex: ^- \[([^\]]+)\] (.+?) <!-- (.+?) -->$
  - strip kind bracket (including embedded reason for INVALID: ...)
  - strip metadata comment → normalized_text
  - compute id = sha256(source_file + "\n" + normalized_text.strip())[:16]
  - parse metadata tags from comment
  - derive scope, confidence, path_prefixes, evidence array
  - return MemoryRecord dataclass

for each *.md file in memory_dir:
  lines = read_file()
  in_provisional_section = False
  for line in lines:
    if line == "---":                        # PROVISIONAL separator
      in_provisional_section = True
    if line matches entry pattern:
      record = parse_entry(line, filename)
      if in_provisional_section and record.kind not in ("PROVISIONAL", "INVALID"):
        # entries below --- inherit PROVISIONAL unless already tagged
        record.kind = "PROVISIONAL"
        record.confidence = 0.4
    else:
      continue
  yield record

write_record(record, records_dir, dry_run):
  path = records_dir / f"{record.id}.json"
  if path.exists():
    return "skipped"
  if not dry_run:
    path.write_text(json.dumps(record.as_dict(), indent=2, sort_keys=True))
  return "created"

update_index(records, index_path, dry_run):
  existing_ids = set of ids already in index.jsonl
  for record in records where record.id not in existing_ids:
    if not dry_run:
      append one compact JSONL line to index.jsonl
```

### Output format

```
Memory import — markethawk
  Source: .archon/memory/
  Records: .archon/memory/records/
  Index:   .archon/memory/index.jsonl
  Mode:    dry-run

  architecture.md        12 entries → 12 would-be-created
  backend-patterns.md    34 entries → 34 would-be-created
  codebase-patterns.md   22 entries → 22 would-be-created
  dark-factory-ops.md    47 entries → 47 would-be-created
  frontend-patterns.md   14 entries → 14 would-be-created

  Total: 129 entries | created: 129 | skipped: 0 | failed: 0
```

On re-run: the `skipped` count rises as existing records are detected; `created` falls to 0.

### Tests: `dark-factory/tests/test_memory_import.py`

Unit tests (pytest):
- ID stability: same entry yields same `id` across repeated calls
- Kind-transition stability: modifying the `[KIND]` tag on a fixed text yields the same `id`
- `[INVALID: reason]` parsing: bracket with embedded reason is stripped correctly; `kind == "INVALID"`; reason captured in `summary` prefix
- PROVISIONAL section: entries below `---` without `[PROVISIONAL]` tag inherit kind PROVISIONAL
- Scope derivation: each of the five filenames maps to the correct scope
- Confidence tiering: INVALID→0.0, PROVISIONAL→0.4, implement→1.0, refine→0.7
- Evidence array: single-evidence entry → one-element array; `evidence2:` → two-element array
- `path_prefixes`: extracted when `path:` tag present; `[]` when absent
- `expires_at`: extracted as ISO string; null when absent
- Idempotency: writing twice skips on second run (by checking record file existence)

Integration test (one function, no golden files):
- Run importer against real `.archon/memory/` with `dry_run=True`
- Assert: total entry count ≥ 100; no duplicate IDs; all records are schema-valid dicts;
  no `.archon/memory/*.md` file was modified (compare mtime before/after)

## Alternatives considered

### A. JSONL-only (single `index.jsonl`)
Simpler to write. But every update requires rewriting the whole file (global rewrite),
which the epic explicitly calls out as something to avoid — localized maintenance is a key
design principle. Rejected.

### B. Per-record files only (no index)
Clean idempotency (file-exists check). But Phase 2's retriever needs to rank candidates by
scope, confidence, and path before loading record bodies. Without an index it must open and
parse every `records/*.json` on each lookup. Rejected.

### C. Use a pip package (mistune, marko) for markdown parsing
The entry format is a defined pattern (`- [KIND] text <!-- metadata -->`), not
general-purpose markdown. A regex is more precise, has zero deps, and is simpler to test.
Rejected.

## Open questions (non-blocking)

1. Should the import script be called automatically from `dark-factory/entrypoint.sh` on
   startup, or only run manually? (Deferred to Phase 2 integration planning.)
2. When Phase 3 (write-path replacement) ships, `gate_lib.sh::write_memory_entry()` will
   write structured records. Should `memory_import.py` be updated to use the same writer
   module, or remain a standalone bootstrap tool? (Out of scope for this ticket.)

## Assumptions

- [A1] The five `.archon/memory/*.md` files contain all current authoritative entries; there
  are no memory entries in other locations that should be imported.
- [A2] The `records/` subdirectory under `.archon/memory/` does not yet exist and will be
  created by the importer on first run.
- [A3] `index.jsonl` does not yet exist and will be created by the importer on first run.
- [A4] The factory container already has Python 3 (stdlib). No additional packages need to
  be installed.
- [A5] The import script is a bootstrap tool for Phase 1 only; it does not need to be
  called from any pipeline command until Phase 2 wires up the retriever.
