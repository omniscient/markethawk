# Dark Factory Prompt Surface Inventory

**Status:** design
**Date:** 2026-07-01
**Issue:** #692
**Epic:** #663 (Dark Factory token optimization)
**Related:** #664, #665, #666, #669, #672, #674, #675, #643

## Problem

The Dark Factory pipeline loads context from many sources — command files, memory, skills,
CLAUDE.md, ARCHITECTURE.md — but there is no single authoritative inventory of what surfaces
exist, how large they are, or which phases load them. Without this inventory it is impossible
to reason coherently about where to invest further optimization effort or what would be
safe to move out of CLAUDE.md into more narrowly scoped files.

This spec is a foundation artifact: it produces the inventory and migration map that
downstream prompt-modularization issues will execute against.

## Requirements

1. List every prompt/context surface in the Dark Factory pipeline with its approximate
   token count (using the factory's own `char / 4` heuristic from `token_estimate.py`).
2. Classify each surface as exactly one of five categories:
   - **always-needed fact** — loaded into every phase by default
   - **phase procedure** — loaded as instructions for a specific phase or subagent
   - **large reference** — potentially loaded but expensive; may be filtered/sliced
   - **deterministic script** — runs as shell/Python code; never loaded as a Claude prompt
   - **security-sensitive config** — Archon/Claude Code configuration; not a prompt
3. Identify which pieces should remain in `CLAUDE.md` versus move to skills or supporting files.
4. Map each surface to the existing #663 child issues that already addressed it, to avoid
   duplicating script work.
5. Produce a migration map: one row per surface, with a recommended action and related issue.
6. Do NOT implement any migrations, modify scripts, or create new GitHub sub-issues.

## Approach

Enumerate all files listed in the issue Scope section, compute `len(file_text) // 4` per
file (matching `te.estimate_tokens()` in `dark-factory/scripts/token_estimate.py`), classify
using the fixed five-category taxonomy, and populate the migration map table below.

Token counts reflect the raw file sizes. For sources with runtime capping — ARCHITECTURE.md
(sliced to ≤3,000 tokens via #666/#689), memory files (capped at 8 entries / 1,500 tokens
via #672/#688) — the "effective in-prompt" column notes the actual cap.

**What counts as a prompt surface:** only files whose content is passed to a Claude model
as input context. Deterministic scripts (Python CLI tools) and the workflow YAML
(interpreted by Archon, not Claude) are inventoried for completeness but are not prompt
surfaces — they orchestrate or construct the prompt, not become it.

## Migration Map

### A. archon-dark-factory.yaml and Command Files

| Source | ~Tokens (raw) | Effective in-prompt | Classification | Phases that load it | Recommended action | Related issue |
|---|---|---|---|---|---|---|
| `.archon/workflows/archon-dark-factory.yaml` | 14,628 | 0 (not loaded as prompt) | phase-procedure | — (Archon DAG interpreter) | Keep. Archon interprets this file; Claude never reads it. Audit comments/embedded text for content that duplicates command files. | — |
| `.archon/commands/dark-factory-refine.md` | 2,766 | 2,766 | phase-procedure | refine | Keep. Well-scoped. Skill prompts loaded separately via /opt/refinement-skills/. | — |
| `.archon/commands/dark-factory-plan.md` | 2,708 | 2,708 | phase-procedure | plan | Keep. Within budget. | — |
| `.archon/commands/dark-factory-implement.md` | 4,675 | 4,675 | phase-procedure | implement, continue | Split consideration: the memory-write format reference (~1,500 tokens) is repeated from `.archon/memory/dark-factory-ops.md`. Audit for consolidation in a follow-up S ticket. | new issue TBD |
| `.archon/commands/dark-factory-conformance.md` | 4,808 | 4,808 | phase-procedure | conformance | Split consideration: OOS resolution procedure is verbose; could reference a separate protocol doc. Follow-up S ticket. | new issue TBD |
| `.archon/commands/dark-factory-code-review.md` | 2,136 | 2,136 | phase-procedure | code-review | Keep. Compact. | — |
| `.archon/commands/dark-factory-validate.md` | 1,996 | 1,996 | phase-procedure | validate | Keep. Compact. | — |
| `.archon/commands/dark-factory-revise-advisory.md` | 1,167 | 1,167 | phase-procedure | revise-advisory | Keep. Compact. | — |
| `.archon/commands/ceiling-revisit.md` | 1,663 | 1,663 | phase-procedure | ceiling-revisit | Keep. Compact. | — |

### B. Always-Loaded Context

| Source | ~Tokens (raw) | Effective in-prompt | Classification | Phases that load it | Recommended action | Related issue |
|---|---|---|---|---|---|---|
| `CLAUDE.md` | 2,411 | 2,411 | always-needed fact | ALL (all scenarios include `claude_md`) | Slim. The "Replay Benchmark" subsection (~200 tokens) and Dark Factory operational detail in "AI-Assisted Development" are factory-only guidance that duplicates `dark-factory-ops.md`. Audit in a follow-up S ticket to see what can safely move to memory or a dedicated factory-ops skill. | new issue TBD |
| `ARCHITECTURE.md` | 14,479 | ≤3,000 (sliced) | large reference | refine, plan, implement, continue | Keep. Architecture slicing (#666, shipped #689) already caps this at 3,000 tokens via `architecture_slice.py`. No further action needed. | #666, #689 |

### C. Skill Files (COPYed into Docker image as /opt/refinement-skills/)

| Source | ~Tokens (raw) | Effective in-prompt | Classification | Phases that load it | Recommended action | Related issue |
|---|---|---|---|---|---|---|
| `.claude/skills/refinement/orchestrator-prompt.md` | 931 | 931 | phase-procedure | refine (skill_prompts section) | Keep. Appropriately scoped persona. | — |
| `.claude/skills/refinement/product-owner-prompt.md` | 507 | 507 | phase-procedure | refine (subagent) | Keep. Compact. | — |
| `.claude/skills/refinement/architect-prompt.md` | 705 | 705 | phase-procedure | plan (subagent) | Keep. Compact. | — |
| `.claude/skills/refinement/conformance-reviewer-prompt.md` | 1,261 | 1,261 | phase-procedure | conformance (skill_prompts section) | Keep. Appropriately scoped. | — |
| `.claude/skills/refinement/code-review-reviewer-prompt.md` | 853 | 853 | phase-procedure | code-review (skill_prompts section) | Keep. Appropriately scoped. | — |
| `.claude/skills/refinement/config.yaml` | 1,870 | 0 (read by scripts, not Claude) | deterministic-script (secondary: phase-procedure config) | All phases (via scheduler.sh and Python scripts) | Keep. Not a prompt surface; read by Python and shell. | — |
| `.claude/skills/refinement/SKILL.md` | 389 | 389 | phase-procedure | Interactive Claude Code sessions only | Keep. Compact skill entry point. | — |
| `.claude/skills/architecture-review/SKILL.md` | 1,004 | 1,004 | phase-procedure | Interactive Claude Code sessions only | Keep. | — |
| `.claude/skills/archon/SKILL.md` | 3,945 | 3,945 | phase-procedure | Interactive Claude Code sessions only | Review. Largest skill file; only loaded when user explicitly invokes `/archon`. Archon.diy URL map section is large — consider whether it can be condensed. | new issue TBD |
| `.claude/skills/validate-scanner/SKILL.md` | 2,916 | 2,916 | phase-procedure | Interactive Claude Code sessions only | Keep. Focused workflow skill. | — |

### D. Memory Files (selective retrieval)

| Source | ~Tokens (raw) | Effective in-prompt | Classification | Phases that load it | Recommended action | Related issue |
|---|---|---|---|---|---|---|
| `.archon/memory/dark-factory-ops.md` | 5,068 | ≤1,500 (top-k cap) | always-needed fact | All phases (via memory_retrieve.py) | Keep. Already capped at 8 entries / 1,500 tokens by #672/#688. | #672, #688 |
| `.archon/memory/backend-patterns.md` | 4,075 | ≤1,500 (top-k cap) | always-needed fact | All phases | Keep. Same cap applies. | #672, #688 |
| `.archon/memory/codebase-patterns.md` | 1,571 | ≤1,500 (top-k cap) | always-needed fact | All phases | Keep. Small raw size. | — |
| `.archon/memory/frontend-patterns.md` | 3,749 | ≤1,500 (top-k cap) | always-needed fact | All phases | Keep. | #672, #688 |
| `.archon/memory/architecture.md` | 641 | 641 | always-needed fact | refine (via memory_retrieve.py) | Keep. Small; rarely hits top-k cap. | — |

### E. Configuration (not prompt surfaces)

| Source | ~Tokens (raw) | Effective in-prompt | Classification | Notes | Recommended action | Related issue |
|---|---|---|---|---|---|---|
| `.claude/settings.json` | 172 | 0 (not a Claude prompt) | security-sensitive config | Contains PostToolUse hooks and plugin enablement. Never passed to Claude model. | Keep. Not a prompt surface; no migration needed. | — |

### F. Deterministic Scripts (#663 optimization infrastructure)

These files are executed as CLI tools. They are NOT prompt surfaces — Claude never reads them.
Inventoried here per the issue scope to establish the boundary between "scripts that construct
prompts" and "prompts themselves."

| Source | ~Tokens (raw) | Classification | Purpose | Shipped in | Recommended action |
|---|---|---|---|---|---|
| `dark-factory/scripts/context_budget.py` | 2,910 | deterministic-script | Measures pre-prompt token estimates per scenario | #664, #687 | Keep. Do not modify. |
| `dark-factory/scripts/memory_retrieve.py` | 3,548 | deterministic-script | Selects top-k memory entries for a phase | #672, #688 | Keep. Do not modify. |
| `dark-factory/scripts/memory_write.py` | 2,090 | deterministic-script | Appends entries to memory files with dedup | #643 | Keep. Do not modify. |
| `dark-factory/scripts/context_pack.py` | 3,445 | deterministic-script | Assembles scenario-specific context packs | #665, #690 | Keep. Do not modify. |
| `dark-factory/scripts/architecture_slice.py` | 3,763 | deterministic-script | Emits relevant ARCHITECTURE.md excerpt | #666, #689 | Keep. Do not modify. |
| `dark-factory/scripts/token_estimate.py` | 138 | deterministic-script | `char / 4` token estimator (factory baseline) | #664 | Keep. Source of truth for token math. |
| `dark-factory/scripts/code_review_payload.py` | 2,033 | deterministic-script | Prepares diff payload for code-review phase | #669 | Keep. |
| `dark-factory/scripts/fmt_hunk_filter.py` | 2,417 | deterministic-script | Filters diff hunks by relevance score | #669 | Keep. |
| `dark-factory/scripts/gate_blast_radius.py` | 1,122 | deterministic-script | Evaluates blast radius before dispatch | — | Keep. |
| `dark-factory/scripts/eval_memory_quality.py` | 3,053 | deterministic-script | Evaluates memory entry quality | #672 | Keep. |
| `dark-factory/scripts/memory_import.py` | 3,662 | deterministic-script | Bulk imports memory entries | #643 | Keep. |
| `dark-factory/scripts/memory_maintain.py` | 3,908 | deterministic-script | Prunes and maintains memory files | #643 | Keep. |
| `dark-factory/scripts/check_workflow_dag.py` | 1,069 | deterministic-script | Validates workflow DAG structure | — | Keep. |
| `dark-factory/scripts/check_workflow_when.py` | 945 | deterministic-script | Validates `when:` conditions in workflow | — | Keep. |
| `dark-factory/scripts/dedupe_oos.py` | 1,320 | deterministic-script | Detects duplicate OOS excisions | — | Keep. |

## Summary: Token Budget by Category and Phase

**Raw totals by classification:**

| Classification | Files | Raw ~tokens |
|---|---|---|
| phase-procedure (prompt surfaces) | 22 | 49,058 |
| deterministic-script (not prompts) | 15 | 37,293 |
| always-needed fact | 5 | 17,515 |
| large-reference | 1 | 14,479 |
| security-sensitive config | 1 | 172 |

**Effective prompt tokens loaded per factory phase** (post-optimization by #663 children):

| Phase | Command file | CLAUDE.md | ARCHITECTURE.md | Skill prompts | Memory | Estimated total |
|---|---|---|---|---|---|---|
| refine | 2,766 | 2,411 | ≤3,000 | ~2,200 | ≤1,500 | ~11,900 |
| plan | 2,708 | 2,411 | ≤3,000 | ~700 | ≤1,500 | ~10,300 |
| implement | 4,675 | 2,411 | ≤3,000 | 0 | ≤1,500 | ~11,600 |
| conformance | 4,808 | 0 | 0 | ~2,100 | 0 | ~6,900 |
| code-review | 2,136 | 0 | 0 | ~850 | 0 | ~3,000 |
| validate | 1,996 | 2,411 | 0 | 0 | ≤1,500 | ~5,900 |

Note: These estimates cover the structured factory context only. Issue body, comments, spec
text, PR diff, and implementation.md are scenario-specific and variable.

## CLAUDE.md vs Skills: What Should Move

**Keep in CLAUDE.md:**
- Tech stack, commands, ports — these are developer-facing and apply to all contexts (interactive, factory, local dev).
- Architecture section overview — brief by design; details live in ARCHITECTURE.md.
- "Further Reading" links — navigation aids for all contributors.
- Development Rules — apply to every coding context.
- Codeindex and Repowise sections — tool configuration for both interactive and factory use.

**Candidates to move out of CLAUDE.md** (follow-up issue TBD):
- "Replay Benchmark" subsection — operational detail for factory-only use; duplicates what dark-factory-ops.md covers. Slim to a one-line pointer to `dark-factory/bench/`.
- "AI-Assisted Development" subsection on Dark Factory — the detailed `docker compose --profile factory run` invocation and "Dark Factory (autonomous Docker)" paragraph are factory-ops content already in dark-factory-ops.md. Replace with a one-line pointer to `docs/ai-development.md`.
- Expected savings from CLAUDE.md slim: ~200–300 tokens across all phases.

## Overlaps with #663 Child Issues (Do Not Duplicate)

| #663 child | Shipped in | What it delivered | Status re: this inventory |
|---|---|---|---|
| #664 context telemetry | #687 | `context_budget.py` — per-phase token measurement | Complete; this spec uses its numbers |
| #665 context packs | #690 | `context_pack.py` — scenario-specific context assembly | Complete |
| #666 architecture slices | #689 | `architecture_slice.py` — ARCHITECTURE.md slicing | Complete; caps ARCHITECTURE.md at ≤3,000 tokens |
| #669 diff ranking | — | `fmt_hunk_filter.py`, `code_review_payload.py` | Scripts exist; integration status per workflow |
| #672 token-quality evaluation | #688 | `memory_retrieve.py` top-k cap; `eval_memory_quality.py` | Complete; memory capped at 1,500 tokens |
| #674/#675 codebase-memory-mcp | — | Structural code memory via MCP | In progress |
| #643 memory v2 | — | Flat-file memory system; `memory_write/import/maintain.py` | In progress |
| #688 refinement config token policy | #688 | `config.yaml` `token_optimization` block | Complete |

## Alternatives Considered

### Option A: Produce spec-only inventory (chosen)

Write the full inventory and migration map in this spec. Downstream implementation tickets
execute the migrations. Keeps this `size: S` ticket focused on its deliverable.

### Option B: Auto-create sub-issues from migration map

File a GitHub sub-issue for each "new issue TBD" row. Rejected: the epic owner controls
issue creation; auto-filing risks duplicating tickets already being planned or creating
scope the team hasn't prioritized. A Markdown table with "new issue TBD" placeholders
is the appropriate hand-off artifact.

### Option C: Use actual BPE tokenization

Replace the `char / 4` heuristic with a real tiktoken tokenizer for precision. Rejected:
the factory's own `context_budget.py` uses `char / 4` as its baseline; deviating from
that heuristic would make this inventory's numbers inconsistent with factory telemetry.
The ~10% BPE variance is within the "approximate" tolerance of the AC.

## Open Questions

- **How many of the "new issue TBD" migration actions will the epic owner file?** Not
  blocking for this spec; the map is complete enough to drive issue creation.
- **Does the conformance command file warrant a split?** At 4,808 tokens it is the largest
  command file, but it's only loaded in the conformance phase (not every phase). The
  savings from splitting it are phase-specific, not cross-cutting.

## Assumptions

- Token estimates use `floor(len(text) / 4)` as computed at spec-write time (2026-07-01).
  File sizes change as issues land; re-run `token_estimate.py` before citing these numbers
  in implementation tickets.
- The `validate-scanner/SKILL.md` (2,916 tokens) is only loaded during interactive
  `/validate-scanner` sessions, not by any factory phase.
- The `archon/SKILL.md` (3,945 tokens) is only loaded during interactive `/archon` sessions.
- Memory effective-in-prompt values assume the top-k cap from #688 is active
  (`memory.max_entries: 8`, `memory.max_tokens: 1500`).
