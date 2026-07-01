# Refinement & Planning Prompts — Phase Playbook Refactor

**Status:** design
**Date:** 2026-07-01
**Issue:** #694
**Epic:** Claude Skills prompt-modularization supplement to #663

## Problem

The `.claude/skills/refinement` skill mixes two concerns in one file:

1. **Documentation** — the `SKILL.md` describes both the refine and plan phases inline, duplicating narrative that already lives authoritatively in the Archon command files (`.archon/commands/dark-factory-refine.md` and `.archon/commands/dark-factory-plan.md`).
2. **Context loading** — both command files read `CLAUDE.md` and `ARCHITECTURE.md` unconditionally at Phase 1 LOAD, even though the `context_pack.py` pipeline (shipped in #663/665) already assembles these into a pre-built `context-pack.md` artifact in `$ARTIFACTS_DIR`. When the pack is present, the individual file reads are redundant.

The result: the SKILL.md is harder to maintain (it drifts from the command files) and the command files spend tokens re-reading files that the context-budget already assembled.

## Requirements

1. The `.claude/skills/refinement/SKILL.md` becomes a concise compat wrapper — invocation triggers and a pointer to the canonical command files. The verbose phase breakdown (lines 27-40) is removed.
2. Both command files check for `$ARTIFACTS_DIR/context-pack.md` at Phase 1 LOAD. When the pack is present, read `CLAUDE.md` from the `## claude_md` section and `ARCHITECTURE.md` from the `## architecture_md` section. When absent, fall back to direct file reads (existing behavior, unchanged).
3. The `dark-factory-plan.md` command additionally reads the spec from the pack's `## spec` section when available, with fallback to the existing `docs/superpowers/specs/` glob search.
4. Prompt files (`/opt/refinement-skills/*.md`) and `config.yaml` are always read from their mount paths, regardless of pack status — the pack's `skill_prompts` section concatenates them without filename boundaries and does not include `config.yaml`.
5. The `memory_retrieve.py` bash block is always run (the pack's `memory_context` section is generated inside the command session, so the pre-run pack always sees it as absent).
6. All existing scheduler command strings (`Refine issue #N`, `Plan issue #N`), Archon invocation paths, Dockerfile mounts, and `config.yaml` paths are unchanged.
7. No new `.claude/skills/` directories are created — the "split into two skills" per AC #1 refers to the Archon command files (`dark-factory-refine.md` / `dark-factory-plan.md`) which already exist as separate phase playbooks.

## Architecture

### File changes

#### `.claude/skills/refinement/SKILL.md` — shrink to compat wrapper (~20-25 lines)

Remove the "What It Does" phase breakdown (lines 27-40 of the current file). Keep:
- Frontmatter (`name`, `description`)
- Usage section with invocation triggers and docker commands — **these preserve scheduler compat**
- One-line note: "The executable phase playbooks live in `.archon/commands/dark-factory-refine.md` and `.archon/commands/dark-factory-plan.md`."
- Configuration section (points at `config.yaml`)
- Prompt Files section (lists shared bundle files — documents the `/opt/refinement-skills/` mount)

Nothing else changes in `.claude/skills/refinement/` — shared prompt files and `config.yaml` stay exactly where they are.

#### `.archon/commands/dark-factory-refine.md` — Phase 1 LOAD

Replace steps 1-2 ("Read CLAUDE.md… Read ARCHITECTURE.md") with the context-pack aware block:

```
## Phase 1: LOAD

1. Check for a pre-assembled context pack:

   ```bash
   CONTEXT_PACK="${ARTIFACTS_DIR:-/tmp}/context-pack.md"
   if [ -f "$CONTEXT_PACK" ]; then
     echo "context-pack.md found — using pre-assembled context"
   else
     echo "context-pack.md absent — reading source files directly"
   fi
   ```

   **If the pack is present:** read the following sections from `$CONTEXT_PACK`:
   - `## claude_md` → use as CLAUDE.md content (development rules, architecture, conventions)
   - `## architecture_md` → use as ARCHITECTURE.md content (service topology, module map)

   If a section is missing or empty in the pack, read the source file directly as fallback:
   - `CLAUDE.md` — development rules, architecture, conventions
   - `ARCHITECTURE.md` — service topology and module map

   **If the pack is absent:** read both `CLAUDE.md` and `ARCHITECTURE.md` directly.

2. The issue context has been fetched by the workflow. It is available in the conversation.
3. Read `/opt/refinement-skills/orchestrator-prompt.md` for your process instructions
4. Read `/opt/refinement-skills/product-owner-prompt.md` — you will pass this to subagents
5. Read `/opt/refinement-skills/config.yaml` for pipeline configuration
6. [Memory context step — unchanged]
```

Steps 3-7 (prompt files, memory context, re-run handling) are unchanged.

#### `.archon/commands/dark-factory-plan.md` — Phase 1 LOAD

Same pattern as refine, plus the spec section. Replace steps 1, 4-5:

```
1. Check for a pre-assembled context pack (same bash block as refine).

   **If the pack is present:** read `## claude_md` as CLAUDE.md content. If absent/empty, read `CLAUDE.md` directly.

2. The issue context has been fetched by the workflow.
3. Read `/opt/refinement-skills/architect-prompt.md` — you will pass this to the review subagent
4. Find and read the spec:

   **If the pack is present** and `## spec` is non-empty: use that content as the spec.
   **Otherwise:** look in `docs/superpowers/specs/` for a file matching this issue's topic,
   or check the issue comments for a "Refinement Pipeline — Spec Generated" report that names
   the spec path. Read the spec file.

5. [Memory context step — unchanged]
```

Note: plan's Phase 1 already does not load `ARCHITECTURE.md` directly (it relies on the spec for architecture context). The pack's `## architecture_md` section is available for plan too, but including it is optional — the spec should leave this as a "read if present" advisory rather than a required step to avoid bloating plan context.

### Section key reference

Context-pack sections relevant to these commands, from `context_budget.py:27-28`:

| Section key | Refine pack | Plan pack | Source |
|---|---|---|---|
| `claude_md` | ✓ | ✓ | `CLAUDE.md` (full or sliced) |
| `architecture_md` | ✓ | ✓ | `ARCHITECTURE.md` (sliced by scenario) |
| `skill_prompts` | ✓ | ✓ | `/opt/refinement-skills/*.md` concatenated — **not used from pack** |
| `issue_context` | ✓ | ✓ | Issue body — already in conversation context |
| `comments` | ✓ | ✓ | Issue comments — already in conversation context |
| `memory_context` | ✓ | ✓ | Written inside session — **always empty in pre-run pack** |
| `spec` | — | ✓ | Spec file from `docs/superpowers/specs/` |

The header format in `context-pack.md` is exactly `## <section_key>` (e.g., `## claude_md`) per `context_pack.py:258`.

## Alternatives Considered

### A. Create new `.claude/skills/dark-factory-refine/` and `.claude/skills/dark-factory-plan/` directories

Copy the Phase 1-6 playbook content into two new SKILL.md files. Rejected: the playbooks are 300+ lines of bash-embedded phase instructions that already have exactly one authoritative home (`.archon/commands/`). Duplicating into `.claude/skills/` creates a two-copy drift hazard and adds files that nothing in the factory pipeline reads. The Dockerfile, entrypoint, scheduler, and `context_budget.py` all hardcode `.claude/skills/refinement/` — no benefit from new directories.

### B. Read the context pack unconditionally (no fallback)

If the pack exists, require it; otherwise error. Rejected: as of this writing, no DAG node invokes `context_pack.py --scenario refine|plan` before these commands fire. The presence-check with fallback ("where available") is the correct contract — the fallback branch is the live production path until the DAG is updated.

### C. Remove the `memory_retrieve.py` bash block and read memory from the pack

Rejected: the `memory_context` section in the pre-run pack is always empty (it's populated by `memory_retrieve.py` inside the command session, after the pack was generated). Reading it from the pack would silently load zero memory context in every run.

## Assumptions

- `$ARTIFACTS_DIR` is always set by the Archon workflow before the command runs (it's set in `entrypoint.sh:95`).
- The context pack, when present, follows the `## <section_key>` header convention from `context_pack.py:258`. No version negotiation needed.
- `context_pack.py --scenario refine` and `--scenario plan` already pass their own tests (`dark-factory/tests/test_context_pack.py`) — no test changes are required by this refactor.
- The `spec` section in the plan pack points at the same file the existing spec-discovery logic would find. No spec-selection logic changes needed.

## Open Questions

- Should plan also consume `## architecture_md` from the pack? The architecture slice is potentially useful context for plan writing. This is advisory — the implementer can include it as a "read if present" step without blocking approval.
- Will the scheduler/DAG be updated in a follow-up to pre-generate context packs for the refine/plan scenarios? This refactor is designed to work whether or not that wiring exists.
