# Dark Factory Claude Skills — Architecture and Safety Policy

**Status:** design
**Date:** 2026-07-01
**Issue:** #693
**Epic supplement:** #663 (token optimization / prompt modularization)
**Build constraint:** Policy doc only — no code changes. Implementation produces
`docs/agents/dark-factory-claude-skills.md` as the living ops doc.

## Problem

The Dark Factory pipeline has accumulated skills (`.claude/skills/`) and settings
(`.claude/settings.json`) without a codified convention. This creates three risks:

1. **Safety gap** — no rule prevents adding `allowed-tools: Bash(*)` to a factory skill
   or auto-triggering an implement/deploy-like skill mid-conversation.
2. **Context bloat** — skill bodies can inline raw `cat ARCHITECTURE.md`, raw `git diff`,
   or raw comment dumps, burning tokens the budget accounting never sees.
3. **Drift** — each new skill author independently decides layout, tooling scope, and
   context strategy, diverging from established patterns.

This spec defines the conventions that close these gaps and must be enforced on all
future `.claude/skills/**`, `.claude/settings.json`, hook, and plugin-config changes.

## Requirements

Distilled from the Q&A with the product owner:

1. **One skill = one directory** at `.claude/skills/<name>/SKILL.md`. No category
   subdirectories between `.claude/skills/` and the skill folder.
2. **Three skill classes** — _phase_, _interactive_, _reference_ — each with fixed
   frontmatter obligations.
3. **Phase skills must carry `disable-model-invocation: true`** to prevent auto-triggering
   from description matching.
4. **No `allowed-tools: Bash(*)`** — all bash grants are enumerated by subcommand.
5. **Explicit `disallowed-tools`** for destructive operations on every phase skill,
   independent of the allowlist.
6. **Dynamic context injection via compact scripts** — never raw file cat or raw diff or
   raw comment dumps in a SKILL.md body.
7. **Subagent prompts stay inside the parent skill dir** — never promoted to standalone
   skills with their own invocable frontmatter.
8. **Archon/scheduler compatibility** — a phase skill's trigger phrases must match the
   exact strings the scheduler dispatches.
9. **Tiered evaluation gate** — phase-skill changes require a bench pass; reference-skill
   changes require code review + dry-run only.

## Architecture

### Skill Classes

| Class | Examples | Side effects | Invocability |
|---|---|---|---|
| **Phase** | `refinement` | git commits, GH comments, label changes | Explicit dispatch or slash command only |
| **Interactive** | `architecture-review`, `validate-scanner` | writes files, posts DB records | User-invocable (slash command or explicit ask) |
| **Reference** | `archon` | none | Model-invocable from description match |

### Directory Layout Convention

```
.claude/skills/
  <skill-name>/
    SKILL.md          ← sole entry point; frontmatter + instructions
    config.yaml       ← skill-local tunables (optional, stays at root)
    templates/        ← subagent prompt files (*-prompt.md)
    references/       ← reference docs the skill reads on demand
    scripts/          ← skill-private compact scripts (only if no shared equivalent)
    assets/           ← non-text support files (HTML shells, images)
```

**Rules:**
- Flat sibling layout (no subdirs) is acceptable for skills with ≤ 3 supporting files.
- Skills with > 3 supporting files must use the categorized layout above.
- Subagent persona files (`product-owner-prompt.md`, `architect-prompt.md`, etc.) live
  in `templates/` and are never promoted to top-level skills.
- The `scripts/` subdir is for skill-private helpers with no reuse value. Shared compact
  scripts (memory retrieval, context packs, architecture slices, diff filtering) live in
  `dark-factory/scripts/` and are called from SKILL.md bodies by path.

### Frontmatter Obligations by Class

```yaml
# Phase skill example
---
name: implement
description: >
  Execute a Dark Factory implement run for a planned issue.
  Trigger phrases: "Fix issue #<number>", "Implement issue #<number>".
disable-model-invocation: true   # REQUIRED — never auto-triggered from description match
user-invocable: true             # explicit slash command or named dispatch only
allowed-tools:
  - Read
  - Glob
  - Grep
  - Write
  - Edit
  - Bash(git diff:*)
  - Bash(git log:*)
  - Bash(git add:*)
  - Bash(git commit:*)
  - Bash(gh issue view:*)
  - Bash(gh issue comment:*)
  - Bash(gh issue edit:*)
  - Bash(python3 dark-factory/scripts/*:*)
disallowed-tools:
  - Bash(rm:*)
  - Bash(git push --force:*)
  - Bash(git reset --hard:*)
  - Bash(gh repo delete:*)
  - Bash(gh pr merge:*)
  - Bash(git push --no-verify:*)
---
```

```yaml
# Reference skill example
---
name: archon
description: >
  Use when: User wants to run Archon workflows, create commands, ...
# No disable-model-invocation (model may auto-invoke on description match)
allowed-tools:
  - Read
  - Glob
  - Grep
---
```

```yaml
# Interactive skill example
---
name: architecture-review
description: Generate a point-in-time Architecture & Quality report ...
# No disable-model-invocation (user explicitly invokes, model may also match)
allowed-tools:
  - Read
  - Glob
  - Grep
  - Write
  - Edit
  - Bash(git log:*)
  - Bash(git rev-parse:*)
  - Bash(find:*)
  - Bash(npx tsc:*)
---
```

### Tool Permission Rules

**Banned in all factory skills:**
- `Bash(*)` — blanket bash grant is prohibited
- `Bash(git push --force:*)`, `Bash(git reset --hard:*)` — destructive git ops
- `Bash(gh pr merge:*)`, `Bash(gh repo delete:*)` — destructive GH ops
- `Bash(rm -rf:*)` or `Bash(rm:*)` — filesystem destruction

**Phase skill minimum disallowed-tools:** Every phase skill must carry an explicit
`disallowed-tools:` block naming the destructive operations above, even when `allowed-tools`
already excludes them. This is defense-in-depth for reviewers — the block documents intent
and ensures a narrowed allowlist plus a hard ban are both visible in the frontmatter.

**Tiered allowed-tools grants:**

| Class | Minimum grant | May add |
|---|---|---|
| Reference | `Read, Glob, Grep` | Nothing |
| Interactive | `Read, Glob, Grep, Write, Edit` | Specific `Bash(git log:*)`, `Bash(find:*)`, safe read-commands |
| Phase | `Read, Glob, Grep, Write, Edit` | Specific `Bash(git commit:*)`, `Bash(gh issue comment:*)`, `Bash(python3 dark-factory/scripts/*:*)` — enumerate every subcommand explicitly |

### Dynamic Context Injection Policy

**Banned inside SKILL.md bodies:**
- `` `cat ARCHITECTURE.md` `` or any raw file read injected inline
- `` `git diff` `` without piping through a filter script
- Raw issue comment dumps (e.g. `` `gh issue view $N --comments` `` unparsed)

**Required pattern:**

Every context artifact injected into a skill prompt must come from a compact script
that self-caps its output. The script must:

1. Live in `dark-factory/scripts/` (shared) or the skill's own `scripts/` (private only)
2. Accept a `--phase` or equivalent flag so context is scoped to what the phase needs
3. Honor the budget accounting in `context_budget.py` (`BUDGET_TOKENS`, per-section caps)
4. Emit its own token count if called with `--emit-trace-to <path>`

Approved compact scripts and their replacements:

| Banned pattern | Approved replacement |
|---|---|
| `cat ARCHITECTURE.md` | `python3 dark-factory/scripts/context_pack.py --phase <phase>` |
| `git diff` raw | `python3 dark-factory/scripts/code_review_payload.py` |
| `gh issue view --comments` raw | `gh issue view $N --json body,comments \| python3 dark-factory/scripts/fmt_issue.py` |
| All memory files | `python3 dark-factory/scripts/memory_retrieve.py --phase <phase>` |
| Architecture slice | `python3 dark-factory/scripts/architecture_slice.py --component <c>` |

**Token budget:** No single injected artifact has a fixed global cap — artifact sizes
legitimately vary (a memory summary is smaller than an architecture slice). Instead, all
artifacts must route through the existing `context_budget.py` accounting so the run's
telemetry (issue #664) stays accurate. Any script that emits injected context must report
its estimated token cost or emit the `over_budget` flag when it exceeds its section ceiling.

### Archon/Scheduler Compatibility

Phase skills that carry `disable-model-invocation: true` are not reachable by the model
from description matching. The scheduler dispatches them via explicit message strings
(e.g. `"Refine issue #12"`, `"Plan issue #12"`, `"Fix issue #12"`). To preserve this:

1. The SKILL.md `description` field must contain the exact trigger phrases the scheduler
   emits — not just a summary. This keeps both paths aligned: the scheduler's explicit
   string matches the same phrases, and an interactive user can type the same string to
   invoke the skill explicitly.
2. When a new phase-skill variant is added (e.g. `"Evaluate issue #N"`), the corresponding
   dispatch path in `dark-factory/scheduler.sh` (or `entrypoint.sh`) must be updated in the
   same PR so the scheduler and skill stay in sync.
3. Skills must produce the same outcome whether invoked via `docker compose --profile factory
   run --rm dark-factory "..."` or typed directly into a Claude Code session — there is no
   formal workflow YAML in this path.

### Review Expectations

Changes to `.claude/skills/**`, `.claude/settings.json`, hooks (`hooks:` in settings), or
`enabledPlugins` must go through the following gates before merge:

| Change type | Gate |
|---|---|
| Phase skill SKILL.md, subagent prompt `*-prompt.md`, or config.yaml | `dark-factory/bench/run_suite.sh` pass (no regression vs `bench/baseline.md`) |
| Phase skill `disallowed-tools` or `allowed-tools` change | Bench pass + security review in PR |
| `.claude/settings.json` hooks | Bench pass + `run_suite.sh --dry-run` |
| Interactive skill | Code review + `run_suite.sh --dry-run` (bench not required) |
| Reference skill | Code review only |
| `enabledPlugins` add | Code review + manual trigger check in staging |

**Bench pass criteria:** `pass^k` per size bucket must not regress against the committed
`dark-factory/bench/baseline.md` values. Record the bench result in the PR body.

## Alternatives Considered

### A: Category subdirectories inside `.claude/skills/`

Place phase skills at `.claude/skills/phase/<name>/` and reference skills at
`.claude/skills/reference/<name>/`. Rejected because Claude Code's skill loader discovers
skills by scanning for `SKILL.md` files in the *immediate* child of `.claude/skills/`; a
nested category directory breaks discovery. Encode the phase/reference distinction in
frontmatter instead.

### B: Promote subagent prompts to standalone skills

Give `product-owner-prompt.md` and `architect-prompt.md` their own frontmatter and
`SKILL.md` wrappers so they are independently invocable. Rejected because promotion adds
new description-match surfaces for auto-triggering and increases the review footprint.
These prompts are variable-substituted templates, not independently callable capabilities.

### C: Per-skill fixed token cap (e.g. 2000 tokens per injected artifact)

Apply a single global max per injected context artifact. Rejected because a memory summary
and an architecture slice have legitimately different sizes. Use the existing
`context_budget.py` per-section accounting instead — it already enforces `BUDGET_TOKENS`
overall and section-level `over_budget` flags.

## Assumptions

- `disable-model-invocation` in Claude Code frontmatter prevents the model from
  auto-invoking the skill based on description matching; it does not prevent the skill from
  spawning its own subagents once invoked. This is the intended semantics.
- The existing `dark-factory/scripts/` compact scripts (`memory_retrieve.py`,
  `context_pack.py`, `architecture_slice.py`, `context_budget.py`) are the approved shared
  injection layer; new scripts should extend this set, not duplicate it.
- The primary living ops doc (`docs/agents/dark-factory-claude-skills.md`) is out of scope
  for this refine run (OOS gate allows only `docs/superpowers/specs/` and `.archon/memory/`);
  it is the first implementation deliverable.

## Open Questions (non-blocking)

1. **`disallowed-tools` interaction with `allowed-tools`**: It is unclear whether Claude Code
   processes both lists and treats `disallowed-tools` as a hard override, or whether a narrow
   `allowed-tools` list makes `disallowed-tools` redundant. The defense-in-depth rationale
   stands regardless, but implementation should verify the processing order.
2. **Bench baseline update cadence**: The `dark-factory/bench/baseline.md` needs to be
   updated when skills legitimately change behavior. Clarify whether the implementer or a
   human updates the baseline after a breaking-but-intentional skill change.

## Implementation Deliverables

1. `docs/agents/dark-factory-claude-skills.md` — the living ops doc (authoritative, linked
   from CLAUDE.md "Agent Skills" section). Contains the full policy tables, frontmatter
   templates, and injection rules from this spec.
2. Retrofit existing skills to comply: add explicit `allowed-tools`/`disallowed-tools` to
   `refinement/SKILL.md`; add `disable-model-invocation: true` to phase-oriented skills;
   move `refinement/`'s prompt files to `templates/`.
3. Bench run confirming no regression after skill-frontmatter changes.
