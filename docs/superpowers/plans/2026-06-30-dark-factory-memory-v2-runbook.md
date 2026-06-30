# Plan: Dark Factory Memory v2 — Operator Runbook

**Issue:** #655  
**Spec:** `docs/superpowers/specs/2026-06-30-dark-factory-memory-v2-rollout-design.md`  
**Date:** 2026-06-30  
**Size:** S  
**Goal:** Write a new standalone operator runbook for the shipped flat-file memory v2 system and add pointer links from three adjacent docs. No code changes.

---

## Architecture

Memory v2 is a **purely file-based** system already deployed. The runbook documents what exists:

- `dark-factory/scripts/memory_retrieve.py` — reads `.archon/memory/*.md` + `index.jsonl` at gate LOAD
- `dark-factory/scripts/memory_write.py` — writes new lessons post-run (via `gate_lib.sh::write_memory_entry()`)
- `.archon/memory/*.md` — authoritative flat-file store committed to git
- `.archon/memory/index.jsonl` + `records/` — compact index + per-entry JSON records
- `dark-factory/scripts/memory_maintain.py` — lifecycle maintenance CLI

This plan produces documentation only. The implementation agent writes one new markdown file and adds three pointer lines to existing docs.

---

## Tech Stack

- **Documentation format:** Markdown (GitHub-flavored)
- **No build step** — all changes are prose files
- **Verification:** Spell-check AC coverage (manual), `grep` to confirm pointer insertions

---

## File Structure

| File | Change |
|---|---|
| `docs/agents/dark-factory-memory-v2.md` | **New** — operator runbook (10 sections) |
| `docs/agents/dark-factory-memory-contract.md` | **Edit** — add "See also" footer link |
| `docs/ai-development.md` | **Edit** — add memory pointer bullet in §Dark Factory |
| `CLAUDE.md` | **Edit** — add "Memory v2 operator guide" companion bullet in §Agent Skills |

---

## Tasks

---

### Task 1 — Write `docs/agents/dark-factory-memory-v2.md`

**Files:** `docs/agents/dark-factory-memory-v2.md`

**Note:** This file is the sole major deliverable. All 10 sections map 1-to-1 to the spec. Because this is a documentation task, "TDD" is replaced with a draft → coverage-check → commit pattern.

#### Step 1 — Draft the document

Create `docs/agents/dark-factory-memory-v2.md` with the following exact content:

```markdown
# Dark Factory Memory v2 — Rollout & Fallback Operator Guide

**Status:** shipped  
**Date:** 2026-06-30  
**Issue:** #655 | **Epic:** #643  
**Author:** MarketHawk Refinement Pipeline

---

## §1 — Overview

Dark Factory memory v2 is the flat-file accumulation system that lets pipeline agents learn from past runs. At Phase 1 LOAD, each gate agent reads distilled architectural lessons from `.archon/memory/` — patterns and avoidances scoped to the files being changed. At gate exit, the same agent writes any new lesson back to the store. The result is a continuously improving context layer that does not require any external service.

The flat-file store (`.archon/memory/*.md`) is the authoritative source of truth. It is committed to the repository, human-readable, and diffable in code review. The schema, lifecycle rules, writer-role matrix, and tag vocabulary are defined and maintained in **`docs/agents/dark-factory-memory-contract.md`** — treat that doc as the stable interface reference. This document is the operator runbook: it covers rollout status, fallback behaviour, rollback steps, failure modes, maintenance CLI usage, cost/performance, and security.

---

## §2 — Component Map

| Component | File | Role | Used by |
|---|---|---|---|
| Retriever | `dark-factory/scripts/memory_retrieve.py` | Reads area memory files for a phase + file set; emits `### Memory:` block | All gate commands (Phase 1 LOAD) |
| Writer | `dark-factory/scripts/memory_write.py` | Writes new lessons with dedup, cap, expiry tagging | `gate_lib.sh::write_memory_entry()` |
| Index | `.archon/memory/index.jsonl` | Compact summary of all entries; primary retrieval path | `memory_retrieve.py` |
| Records | `.archon/memory/records/<id>.json` | Full entry content; read when index refers to a record | `memory_retrieve.py` |
| Memory files | `.archon/memory/*.md` | Human-readable authoritative store; markdown fallback path | `memory_retrieve.py`, `memory_write.py`, `memory_maintain.py` |
| Maintenance CLI | `dark-factory/scripts/memory_maintain.py` | Expire + promote provisional + dedup + invalidate | Manual / scheduled operator invocation |

---

## §3 — Configuration

**No feature flag exists.** The equivalent of "enabling memory v2" is the gate command-file calls to `memory_retrieve.py` and `memory_write.py` that ship in every gate command under `.archon/commands/`. The system is always on when those command files are present in the cloned repository.

**Default safe mode — fail-open retriever.** If `index.jsonl` is absent or empty, the retriever falls through to a direct scan of the `.archon/memory/*.md` files. If memory files are missing or malformed, it returns an empty block and exits 0. Nothing in any gate aborts on a memory read failure. This is the "default safe mode": the gate always proceeds; memory context is best-effort.

**No env vars are required.** All paths are derived from `git rev-parse --show-toplevel` at runtime. The only optional argument is `--memory-dir`, defaulting to `.archon/memory` relative to the repo root. No credentials, no API keys, no external service addresses are needed.

---

## §4 — Rollout Status

Memory v2 is **fully deployed**. All gate command files (`.archon/commands/dark-factory-*.md`) call `memory_retrieve.py` at Phase 1 LOAD and `memory_write.py` (via `gate_lib.sh::write_memory_entry()`) at the memory-write phase. The flat files in `.archon/memory/` are the authoritative store and are committed to the repository.

No partial rollout or feature gate exists. Memory v2 cannot be partially enabled per-gate — it is either present in all gate command files (current state) or reverted from all of them (see §5 rollback).

---

## §5 — Fallback and Rollback

### Fallback (memory read failure at runtime)

The retriever is fail-open. A missing index, unreadable file, or any OS error returns an empty string and exits 0. The gate proceeds with no memory context. There is no pipeline abort and no notification. See §3 default-safe-mode and §6 failure mode table for specific scenarios.

### Rollback (reverting the v2 gate integration)

If the gate command-file calls to `memory_retrieve.py` and `memory_write.py` need to be reverted — for example, to isolate a regression — the procedure is:

1. **Revert retrieval:** In each affected `.archon/commands/dark-factory-*.md` gate command, replace the `memory_retrieve.py` call block with the pre-v2 inline bash pattern. Recover the reference implementation from git history:
   ```bash
   git log --oneline -- dark-factory/scripts/gate_lib.sh | head -20
   git show <pre-v2-sha>:dark-factory/scripts/gate_lib.sh | grep -A20 "load_memory"
   ```

2. **Revert writes:** In each gate command, replace `memory_write.py` calls (invoked via `write_memory_entry()`) with the pre-v2 direct `awk`/`sed` write pattern. Recover from git history:
   ```bash
   git show <pre-v2-sha>:dark-factory/scripts/gate_lib.sh | grep -A20 "write_memory"
   ```

3. **Commit the reverted command files:**
   ```bash
   git add .archon/commands/
   git commit -m "revert: memory v2 gate integration (debug)"
   ```

4. **No image rebuild required.** Gate command files are read from the cloned repository at runtime — `.archon/commands/` files are live, not baked into the Dark Factory image. The reverted commands take effect on the next factory invocation without a Docker rebuild.

### Rollback scope

The `.archon/memory/*.md` files themselves do **not** need to be reverted. They remain the source of truth in both the v2 path and the pre-v2 (inline bash) path. Only the gate tooling (Python scripts vs. inline bash) is being swapped. Accumulated lessons are preserved through the rollback.

---

## §6 — Memory Read/Write Failure Modes

| Failure | Behaviour | Recovery |
|---|---|---|
| `index.jsonl` absent | Retriever falls through to markdown-file scan | No action needed; index is written on the next gate run that writes a lesson |
| `.archon/memory/*.md` absent | Retriever returns empty block; writer creates the file on demand | No action needed |
| Malformed JSONL line in index | Line is skipped; rest of index proceeds normally | Run `python dark-factory/scripts/memory_maintain.py run` to re-derive index |
| `index.jsonl` write error | Warning logged to stderr; gate exits 0 (index write is best-effort) | Re-run `python dark-factory/scripts/memory_import.py` to rebuild the index |
| Cap reached (30 entries/file) | Writer skips the new entry and logs to stderr; no abort | Run `memory_maintain.py run` to expire old entries and free capacity |
| Dedup match (identical lesson exists) | Writer reinforces the existing entry (`date:`/`expires:` updated); no duplicate written | No action needed |

---

## §7 — Maintenance

Run maintenance monthly, or immediately when cap warnings appear in gate logs.

### Routine maintenance

```bash
# Dry-run — see what would change without writing anything
python dark-factory/scripts/memory_maintain.py run --dry-run

# Apply: expire old entries, promote provisional to active, dedup near-duplicates
python dark-factory/scripts/memory_maintain.py run

# Commit any changes
git add .archon/memory/
git commit -m "chore: memory maintenance (expire + promote + dedup)"
```

### Invalidate a wrong entry

Use this when a gate wrote a lesson that is factually incorrect or outdated:

```bash
python dark-factory/scripts/memory_maintain.py invalidate \
  --file .archon/memory/architecture.md \
  --match "the exact substring to match" \
  --reason "why this entry is factually wrong"
git add .archon/memory/ && git commit -m "memory: invalidate stale entry"
```

### Rebuild the index from the markdown files

Use this after manual edits to `.archon/memory/*.md` files, or after restoring from a backup:

```bash
python dark-factory/scripts/memory_import.py --dry-run  # preview what would be written
python dark-factory/scripts/memory_import.py            # write records/ + index.jsonl
git add .archon/memory/ && git commit -m "memory: rebuild index from markdown"
```

---

## §8 — Cost and Performance Impact

**Memory read overhead per gate run:** The retriever reads 2–5 local markdown files (2–20 KB each) and optionally parses `index.jsonl`. On typical hardware this takes < 50 ms. There is no network call, no vector DB, no embedding model, no external service. Runtime is dominated by Python process startup.

**Memory write overhead:** One file read + one file write + one `index.jsonl` append per lesson written. Most gate runs write zero lessons — the write bar (defined in the contract doc §3) requires a sufficiently novel finding. Cost per write is negligible (< 10 ms I/O, < 1 KB of storage per entry).

**Storage footprint:** `.archon/memory/*.md` files are committed to git and count against repository size. The typical corpus is < 50 KB including the index and records directory. The 30-entry cap per file bounds unbounded growth.

---

## §9 — Security

**Flat-file memory v2 has no runtime security surface.** There are no secrets, no env vars containing credentials, no network endpoints, no external services, and no in-process authentication. The original acceptance criteria for #655 referencing `AGENTMEMORY_SECRET`, localhost-only mode, and a local viewer were written under the discarded agentmemory/vector-DB design (spike #644) and do not apply to the shipped flat-file system.

The two security properties that do apply:

1. **Access control is git-level.** The `.archon/memory/` directory is committed to the repository. Read and write access is governed by the repository's existing branch and PR permissions — nothing memory-specific. Within the pipeline, _logical_ write authority per file is governed by the writer-role matrix in `docs/agents/dark-factory-memory-contract.md §4`. Plan, validate, and revise-advisory gates are read-only consumers; they never call `memory_write.py`.

2. **Entries are committed to git history permanently.** Authors (human or gate agent) must never embed live secrets, credentials, customer data, or PII in lesson bodies. There is no scrubbing layer — once committed, an entry persists in git history even if later invalidated. Entries must contain only distilled engineering lessons about the codebase itself (patterns, avoidances, fixes). The contract doc §3 "Always prohibited" list already enforces this and is the authoritative reference.

No additional security hardening is required.

---

## §10 — Related Docs

- [`docs/agents/dark-factory-memory-contract.md`](dark-factory-memory-contract.md) — authoritative schema, lifecycle rules, writer-role matrix, and migration path to a future structured backend
- [`docs/ai-development.md`](../ai-development.md) §Dark Factory — getting started, Docker invocation, preview environments
- [`CLAUDE.md`](../../CLAUDE.md) §Agent Skills — index of agent-facing docs for this repository
```

#### Step 2 — Verify AC coverage

After writing the file, verify all acceptance criteria from #655 are addressed (reading the file mentally against the spec's §Validation table):

| AC item | §§ |
|---|---|
| Feature flag / config documented | §3 (no flag; gate command-file calls are the integration point) |
| Default mode remains safe | §3 (fail-open retriever) |
| Rollback instructions | §5 |
| Agentmemory outage behaviour | §6 (reframed as memory-read failure modes; agentmemory framing dropped) |
| Operator docs updated | §1–§10 new doc + 3 pointer updates (Tasks 2–3) |
| Cost/performance impact | §8 |
| Security notes | §9 (superseded agentmemory items dropped with explanation) |

Run:
```bash
# Confirm file exists and has all 10 sections
grep -c "^## §" docs/agents/dark-factory-memory-v2.md
# Expected output: 10
```

Expected output: `10`

#### Step 3 — Commit

```bash
git add docs/agents/dark-factory-memory-v2.md
git commit -m "docs(#655): add Dark Factory memory v2 operator runbook"
```

Expected output: `[refine/issue-655-... <sha>] docs(#655): add Dark Factory memory v2 operator runbook`

---

### Task 2 — Add pointer to `docs/agents/dark-factory-memory-contract.md`

**Files:** `docs/agents/dark-factory-memory-contract.md`

The spec requires adding a "See also" link at the bottom of the contract doc.

#### Step 1 — Locate insertion point

```bash
tail -5 docs/agents/dark-factory-memory-contract.md
```

The file ends with the structured-backend migration path (step 5). Append after the final line.

#### Step 2 — Append the pointer

Append the following to the bottom of `docs/agents/dark-factory-memory-contract.md`:

```markdown

---

See also: [Dark Factory Memory v2 — Rollout & Fallback](dark-factory-memory-v2.md) for the operator runbook (rollout status, fallback behaviour, rollback steps, maintenance CLI, cost/perf, and security).
```

#### Step 3 — Verify insertion

```bash
tail -4 docs/agents/dark-factory-memory-contract.md
```

Expected output includes the "See also:" line.

#### Step 4 — Commit with next task (or standalone)

Commit alongside Tasks 3–4 pointer updates (see Task 4 step 4).

---

### Task 3 — Add memory pointer bullet to `docs/ai-development.md`

**Files:** `docs/ai-development.md`

The spec requires adding a bullet to the §Dark Factory subsection of `docs/ai-development.md` referencing both the contract doc and the new runbook.

#### Step 1 — Confirm insertion point

The `## Dark Factory` section is the last top-level section in `docs/ai-development.md`. It ends with a `### Architecture` subsection (the last line of the file). The new `### Memory` subsection is appended immediately after that final line.

```bash
tail -5 docs/ai-development.md
```

Expected: last lines are the `### Architecture` paragraph ending with `...full architecture, security model, and container topology.`

#### Step 2 — Add pointer

Append a new `### Memory` subsection at the end of `docs/ai-development.md`:

```markdown

### Memory

- **Memory contract** — stable schema, lifecycle, and writer-role rules: [`docs/agents/dark-factory-memory-contract.md`](agents/dark-factory-memory-contract.md)
- **Memory v2 operator guide** — rollout, fallback, maintenance, security: [`docs/agents/dark-factory-memory-v2.md`](agents/dark-factory-memory-v2.md)
```

#### Step 3 — Verify

```bash
tail -8 docs/ai-development.md
```

Expected: `### Memory` heading followed by the two bullet lines.

---

### Task 4 — Add companion bullet to `CLAUDE.md`

**Files:** `CLAUDE.md`

The spec requires adding a "Memory v2 operator guide" companion bullet in `CLAUDE.md` §Agent Skills, alongside the existing "Memory contract" bullet at line 170.

#### Step 1 — Locate the line

```bash
grep -n "Memory contract" CLAUDE.md
```

Expected: line 170 — `- **Memory contract** — stable schema, lifecycle rules, and scoping matrix for \`.archon/memory/*.md\`. See \`docs/agents/dark-factory-memory-contract.md\`.`

#### Step 2 — Insert companion bullet

After line 170, insert:

```markdown
- **Memory v2 operator guide** — rollout/fallback/maintenance runbook for the flat-file memory system. See `docs/agents/dark-factory-memory-v2.md`.
```

#### Step 3 — Verify

```bash
grep -A2 "Memory contract" CLAUDE.md
```

Expected: Memory contract bullet followed immediately by Memory v2 operator guide bullet.

#### Step 4 — Commit all pointer updates (Tasks 2–4)

```bash
git add docs/agents/dark-factory-memory-contract.md docs/ai-development.md CLAUDE.md
git commit -m "docs(#655): add memory v2 runbook pointers in contract, ai-development, CLAUDE.md"
```

Expected output: `[refine/issue-655-... <sha>] docs(#655): add memory v2 runbook pointers in contract, ai-development, CLAUDE.md`

---

## Summary

| Task | File(s) | Action |
|---|---|---|
| 1 | `docs/agents/dark-factory-memory-v2.md` | Create 10-section operator runbook |
| 2 | `docs/agents/dark-factory-memory-contract.md` | Append "See also" footer link |
| 3 | `docs/ai-development.md` | Add `### Memory` subsection with two bullets |
| 4 | `CLAUDE.md` | Add companion bullet in §Agent Skills |

**Total tasks:** 4  
**Total steps:** 12  
**Code changes:** 0 (documentation only)  
**Migrations:** none  
**New dependencies:** none
