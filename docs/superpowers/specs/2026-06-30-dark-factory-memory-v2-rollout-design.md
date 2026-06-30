# Dark Factory Memory v2 — Rollout & Fallback Documentation Design

**Status:** design
**Date:** 2026-06-30
**Issue:** #655
**Epic:** #643 (Dark Factory memory v2)
**Size:** S

## Problem

The Dark Factory memory system (epic #643) was designed to help pipeline agents accumulate and reuse architectural lessons across runs. The original issue framing proposed a backend-selectable design (`DARK_FACTORY_MEMORY_BACKEND=markdown|agentmemory|hybrid`) including an agentmemory vector-DB option. That design was evaluated in spike #644 and rejected.

What was actually shipped is a **flat-file memory v2** comprising:
- `memory_retrieve.py` (#646) — role/phase + path-tag read, index.jsonl primary path, markdown fallback
- `memory_write.py` (#648) — write-through adapter (dedup, cap, expiry, tagging)
- `index.jsonl` + `records/` (#649) — compact summary index + per-entry JSON records
- Scoping tags (#651) — `source:`, `path:`, `issue:`, `date:`, `expires:` inline comment tokens
- `memory_maintain.py` (#650) — lifecycle maintenance CLI (expire, promote, dedup, invalidate)
- `docs/agents/dark-factory-memory-contract.md` (#645) — stable schema, lifecycle rules, scoping matrix
- Gate integration (#652) — all gate command files call `memory_retrieve.py` and `memory_write.py`

No operator rollout guide exists for this system. The acceptance criteria in #655 (feature flag, fallback, cost, security) need to be addressed against the flat-file reality, not the discarded agentmemory framing.

## Decision

Write a new **operator runbook** at `docs/agents/dark-factory-memory-v2.md`. Add pointer links from the three adjacent docs named below. This is purely a documentation task — no code changes.

### Why a standalone doc, not an appendix to the contract

The existing `docs/agents/dark-factory-memory-contract.md` is explicitly scoped as the *stable format and lifecycle contract* between the flat-file store, the gate tools, and any future backend. It ends with a migration guide. Appending rollout/fallback/security operational detail would blur that single responsibility. A sibling file maintains the one-concern-per-file convention already used across `docs/agents/`.

## Document Structure: `docs/agents/dark-factory-memory-v2.md`

The implementation task is to write this document with the sections below.

### §1 — Overview

A two-paragraph summary of what memory v2 does: pipeline agents read distilled architectural lessons at Phase 1 LOAD, gate agents write new lessons after each run. Cross-link to `dark-factory-memory-contract.md` as the authoritative schema and lifecycle reference.

### §2 — Component Map

A table listing each shipped component, its file, its role, and the gate/phase that uses it:

| Component | File | Role | Used by |
|---|---|---|---|
| Retriever | `dark-factory/scripts/memory_retrieve.py` | Reads area memory files for a phase + file set; emits `### Memory:` block | All gate commands (LOAD phase) |
| Writer | `dark-factory/scripts/memory_write.py` | Writes `[AVOID]` entries with dedup, cap, expiry | `gate_lib.sh::write_memory_entry()` |
| Index | `.archon/memory/index.jsonl` | Compact summary of all entries; primary retrieval path | `memory_retrieve.py` |
| Records | `.archon/memory/records/<id>.json` | Full entry content; read when index refers to a record | `memory_retrieve.py` |
| Memory files | `.archon/memory/*.md` | Human-readable authoritative store; markdown fallback path | `memory_retrieve.py`, `memory_write.py`, `memory_maintain.py` |
| Maintenance CLI | `dark-factory/scripts/memory_maintain.py` | Expire + promote provisional + dedup + invalidate | Manual / scheduled operator invocation |

### §3 — Configuration

**No feature flag exists.** The equivalent to "enabling memory v2" is the gate command-file calls to `memory_retrieve.py` and `memory_write.py` that already ship in every gate command under `.archon/commands/`. The system is always on when those command files are present.

**Default safe mode:** The retriever degrades gracefully — if `index.jsonl` is absent or empty, it falls through to the markdown-file scan; if memory files are missing or malformed, it returns an empty block and exits 0, allowing the gate to proceed without memory context. Nothing in the gate aborts on a memory read failure.

**No env vars are required.** All paths are derived from `git rev-parse --show-toplevel` at runtime. The only optional argument is `--memory-dir`, defaulting to `.archon/memory` relative to the repo root.

### §4 — Rollout Status

Memory v2 is fully deployed. All gate command files (`.archon/commands/dark-factory-*.md`) call `memory_retrieve.py` at Phase 1 LOAD and `memory_write.py` (via `gate_lib.sh::write_memory_entry()`) at the memory-write phase. The flat files in `.archon/memory/` are the authoritative store and are committed to the repository.

### §5 — Fallback and Rollback

**Fallback (memory read failure):** The retriever is fail-open — a missing index, unreadable file, or any OS error returns an empty string and exits 0. The gate proceeds with no memory context. No pipeline abort, no notification. See §3 default-safe-mode note.

**Rollback (reverting memory v2 gate integration):** If the gate command-file calls to `memory_retrieve.py` need to be reverted (e.g. to debug a regression), the procedure is:

1. In each affected `.archon/commands/dark-factory-*.md` gate command, replace the `memory_retrieve.py` call block with an inline `load_memory()` bash function (the pre-v2 pattern from `gate_lib.sh::load_memory`).
2. In each gate command, replace `memory_write.py` calls (via `write_memory_entry()`) with direct `awk`/`sed` writes to the `.md` files (the pre-v2 pattern from the old `gate_lib.sh` write block).
3. Commit the reverted command files.
4. No image rebuild is required — gate command files are read from the cloned repo at runtime (`.archon/commands/` files are live, not baked; see the `dark-factory-ops.md` pattern for this distinction).

**Rollback scope:** The flat `.archon/memory/*.md` files themselves do not need to be reverted — they remain the source of truth in both the v2 and pre-v2 paths. Only the gate *tooling* (Python scripts vs. inline bash) is being swapped.

### §6 — Memory Read/Write Failure Modes

| Failure | Behaviour | Recovery |
|---|---|---|
| `index.jsonl` absent | Retriever falls through to markdown-file scan | No action needed; will write on next gate run |
| `.archon/memory/*.md` absent | Retriever returns empty; write creates file on demand | No action needed |
| Malformed JSONL line in index | Line skipped; rest of index proceeds | Run `python memory_maintain.py run` to re-derive index |
| `index.jsonl` write error | Warning logged to stderr; gate exits 0 (index write is best-effort) | Re-run `memory_import.py` to rebuild index |
| Cap reached (30 entries/file) | Writer skips and logs; no abort | Run `memory_maintain.py run` to expire old entries and free capacity |
| Dedup match (identical lesson exists) | Writer reinforces existing entry (updates `date:`/`expires:`) | No action needed |

### §7 — Maintenance

**Periodic (monthly or when prompted by cap warnings):**

```bash
# Dry-run — see what would change
python dark-factory/scripts/memory_maintain.py run --dry-run

# Apply: expire old entries, promote provisional to active, dedup near-duplicates
python dark-factory/scripts/memory_maintain.py run

# Commit any changes
git add .archon/memory/
git commit -m "chore: memory maintenance (expire + promote + dedup)"
```

**Invalidate a wrong entry:**

```bash
python dark-factory/scripts/memory_maintain.py invalidate \
  --file .archon/memory/architecture.md \
  --match "the exact substring to match" \
  --reason "why this entry is factually wrong"
git add .archon/memory/ && git commit -m "memory: invalidate stale entry"
```

**Rebuild the index from the markdown files (after manual edits):**

```bash
python dark-factory/scripts/memory_import.py --dry-run  # preview
python dark-factory/scripts/memory_import.py            # write records/ + index.jsonl
git add .archon/memory/ && git commit -m "memory: rebuild index from markdown"
```

### §8 — Cost and Performance Impact

Memory read overhead per gate run: reads 2–5 local markdown files (2–20 KB each) and optionally parses `index.jsonl`. On typical hardware this takes < 50 ms. There is no network call, no vector DB, no external service. The operation is dominated by process startup time for `python3`.

Memory write overhead: one file read + one file write + one `index.jsonl` append per lesson written. Typically 0–1 writes per gate run (most runs write nothing — see write bar in the contract doc §3). Cost is negligible.

Storage: `.archon/memory/*.md` files are committed to git and count against repository size. Typical repository footprint is < 50 KB for the full memory corpus including index and records. The 30-entry cap per file bounds growth.

### §9 — Security

**Flat-file memory v2 has no runtime security surface.** There are no secrets, no env vars, no network endpoints, no external services. The original acceptance criteria referencing `AGENTMEMORY_SECRET`, localhost-only mode, and a local viewer were written under the discarded agentmemory/vector-DB design and do not apply.

The two relevant security properties are:

1. **Access control is git-level.** The `.archon/memory/` directory is committed to the repository. Read/write access is governed by the repository's existing branch and PR permissions — nothing memory-specific. Within the pipeline, *logical* write authority per file is governed by the writer-role matrix in `docs/agents/dark-factory-memory-contract.md` §4. Plan, validate, and revise-advisory gates are read-only consumers (they never call `memory_write.py`).

2. **Entries are committed to git.** Authors (human or gate agent) must never embed live secrets, credentials, customer data, or PII in lesson bodies. There is no scrubbing layer — once a lesson is committed, it persists in git history. Entries should contain only distilled engineering lessons about the codebase itself (patterns, avoidances, fixes). The contract doc §3 "Always prohibited" list already enforces this.

No additional security hardening is required.

### §10 — Related Docs

- `docs/agents/dark-factory-memory-contract.md` — authoritative schema, lifecycle rules, writer-role matrix, migration path to a future structured backend
- `docs/ai-development.md` §Dark Factory — getting started, Docker invocation
- `CLAUDE.md` §Memory contract — Agent Skills bullet pointing to this doc

## Pointer Updates Required (3 files)

As part of implementing this doc, update three existing files to add a link:

1. **`docs/agents/dark-factory-memory-contract.md`** — add to bottom: "See also: [Dark Factory Memory v2 — Rollout & Fallback](dark-factory-memory-v2.md) for the operator runbook."

2. **`docs/ai-development.md`** — in the §Dark Factory subsection, add a bullet: "- **Memory contract** — stable schema, lifecycle, and writer-role rules: `docs/agents/dark-factory-memory-contract.md`. **Memory v2 operator guide** — rollout, fallback, maintenance, security: `docs/agents/dark-factory-memory-v2.md`."

3. **`CLAUDE.md`** §Agent Skills — alongside the existing "**Memory contract**" bullet, add a companion bullet: "**Memory v2 operator guide** — rollout/fallback/maintenance runbook for the flat-file memory system. See `docs/agents/dark-factory-memory-v2.md`."

## Alternatives Considered

### A. Append to `docs/agents/dark-factory-memory-contract.md`

Keeps everything in one place. Rejected because the contract doc is explicitly scoped as the stable *format and lifecycle* reference, ending with a structured-backend migration path. Mixing operational rollout/fallback/security runbook content would blur that single responsibility and make the contract doc harder to treat as a stable interface.

### B. Inline in `docs/ai-development.md`

The operator getting-started guide already points to specialist docs for the contract. Inlining 9 sections of rollout/maintenance/security detail would crowd the getting-started flow. Rejected in favour of a linked sibling doc.

## Open Questions

None blocking.

## Assumptions

- `.archon/commands/` gate command files are live (not baked into the image) — confirmed by the dark-factory-ops memory entry from #162.
- The writer-role matrix in the contract doc is authoritative and does not need to be restated in the new doc (cross-link only).
- `memory_maintain.py` is already shipped and usable as documented here (#650).

## Validation

- Spec implements every acceptance criterion (remapped to flat-file reality):
  - [x] Feature flag / config documented — §3 (no flag; gate command-file calls are the integration point)
  - [x] Default mode remains safe — §3 (fail-open retriever)
  - [x] Rollback instructions — §5
  - [x] "Agentmemory outage behavior" — §6 (reframed as memory-read failure modes)
  - [x] Operator docs updated — §1–§10 new doc + 3 pointer updates in §"Pointer Updates"
  - [x] Cost/performance impact — §8
  - [x] Security notes — §9 (superseded agentmemory items dropped with explanation)
- Implement agent writes `docs/agents/dark-factory-memory-v2.md` with the above structure, then adds the three pointer links.
