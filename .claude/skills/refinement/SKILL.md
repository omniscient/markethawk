---
name: refinement
description: >
  Multi-agent refinement pipeline for GitHub issues. Drives brainstorming via an
  orchestrator + product-owner subagent pair, produces specs, then generates
  implementation plans validated by an architect subagent. Integrates with the
  backlog scheduler for automatic processing.
---

# Refinement Pipeline

Invoke this skill to refine a GitHub issue into a complete spec and implementation plan.

## Usage

Manual invocation (in Claude Code session):
```
Refine issue #<number>
```

Automated invocation (via scheduler or dark factory):
```bash
docker compose --profile factory run --rm dark-factory "Refine issue #12"
docker compose --profile factory run --rm dark-factory "Plan issue #12"
```

## What It Does

**Phase 1 — Spec Generation (`refine` intent):**
1. Reads the issue and explores the codebase
2. Asks clarifying questions via product-owner subagent
3. Selects best approach from 2-3 alternatives
4. Writes and self-reviews the spec
5. Posts spec to the issue, adds `spec-pending-review` label

**Phase 2 — Plan Generation (`plan` intent):**
1. Reads the approved spec
2. Writes a full implementation plan (TDD, bite-sized tasks)
3. Validates via architect subagent
4. Posts plan to the issue, moves to Ready

## Configuration

See `config.yaml` for tunable parameters.

## Prompt Files

- `product-owner-prompt.md` — Persona for the Q&A subagent (adjustable)
- `architect-prompt.md` — Persona for the plan reviewer (adjustable)
- `orchestrator-prompt.md` — Instructions for the brainstorming orchestrator
