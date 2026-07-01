# Configurable Token Optimization Policy — Dark Factory

**Status:** design
**Date:** 2026-07-01
**Epic:** #663 (Dark Factory token optimization: scenario-specific context budgeting and prompt slimming)
**Issue:** #671

---

## Problem

The Dark Factory pipeline has no central, documented policy for token budgeting across its scenarios (refine, plan, implement, conformance, code-review). Enforcement values are hardcoded (e.g. `BUDGET_TOKENS = 200_000` in `context_budget.py`), model escalation criteria are embedded in prompts, and context-slicing parameters have no stable schema. Future tickets under epic #663 need a stable config schema to wire against. Without it, each per-scenario optimization ticket must invent its own configuration surface, making the overall policy incoherent.

This ticket introduces the **declaration-first** step: a single `token_optimization:` block in the pipeline's canonical policy file, with safe defaults and documented env-var overrides. No code reads the new block yet — consumption is deferred to per-scenario implementation tickets.

---

## Decision

Add a `token_optimization:` top-level block to `.claude/skills/refinement/config.yaml`, following the established pattern of every other policy block in that file (conformance, code_review, blast_radius, epic_autopilot, main_red_autofix).

### Config block

```yaml
token_optimization:
  enabled: true              # env: TOKEN_OPTIMIZATION_ENABLED overrides
  enforce_budgets: false     # env: TOKEN_OPTIMIZATION_ENFORCE_BUDGETS overrides — false = measure only, never hard-stop
  default_budget_tokens: 24000  # env: TOKEN_OPTIMIZATION_DEFAULT_BUDGET_TOKENS overrides
  architecture:
    mode: slice              # slice = load relevant sections only (full = load entire file)
    max_tokens: 3000
  memory:
    mode: top_k              # top_k = keep the N most-relevant entries
    max_entries: 8
    max_tokens: 1500
  comments:
    digest_after_factory_marker: true   # digest comments after the "Refinement Pipeline" marker
    max_tokens: 2000
  diff:
    max_review_tokens: 6000
  escalation:
    cheap_model_first: true  # env: TOKEN_OPTIMIZATION_CHEAP_MODEL_FIRST overrides
    opus_only_for:
      - security
      - trading
      - auth
      - high_blast_radius
      - material_conformance_uncertainty
```

### Env-var overrides (hot-changeable without image rebuild)

| Config key | Env var | Notes |
|---|---|---|
| `enabled` | `TOKEN_OPTIMIZATION_ENABLED` | Kill-switch — ships `true`; set `false` to disable all optimization behaviours |
| `enforce_budgets` | `TOKEN_OPTIMIZATION_ENFORCE_BUDGETS` | `false` = measure and log only; `true` = hard-enforce budget limits per scenario |
| `default_budget_tokens` | `TOKEN_OPTIMIZATION_DEFAULT_BUDGET_TOKENS` | Per-run token target; each scenario may override locally |
| `escalation.cheap_model_first` | `TOKEN_OPTIMIZATION_CHEAP_MODEL_FIRST` | `false` = always escalate to Opus regardless of scenario |

Deeply nested per-scenario values (`architecture.max_tokens`, `memory.max_entries`, `comments.max_tokens`, `diff.max_review_tokens`, `escalation.opus_only_for`) are baked — no individual env vars. This matches how `code_review.severity_order` and `epic_autopilot` sub-fields are handled.

### What does `enforce_budgets: false` mean today?

`context_budget.py` already probes and records per-run token estimates (`estimated_input_tokens`, `utilization_pct`) without enforcement. The "measurement" acceptance criterion is already met by the existing code. Adding the config block with `enforce_budgets: false` as the canonical default makes the measurement-only intent explicit and gives future enforcement tickets a stable flag to check.

`context_budget.py` will continue using its hardcoded `BUDGET_TOKENS = 200_000` constant until a follow-up ticket wires it to read `default_budget_tokens` from this config.

### Build note

`.claude/skills/refinement/config.yaml` is baked into the Dark Factory Docker image at build time (`COPY`d to `/opt/refinement-skills/config.yaml`). Changing the YAML defaults requires:
```bash
docker compose --profile factory build dark-factory
```
The env-var overrides listed above are hot-changeable via `.archon/.env` without a rebuild.

---

## Alternatives considered

### A — Put it in `.archon/config.yaml` (runtime-read, no rebuild)
**Rejected.** `.archon/config.yaml` is the Archon CLI config, not the factory pipeline policy. All pipeline policy blocks (conformance, code_review, blast_radius, dispatch_ceiling, epic_autopilot, main_red_autofix) live in `.claude/skills/refinement/config.yaml`. Scattering token policy elsewhere breaks the "one file for factory policy" property and violates the established pattern.

### B — Add config + wire `context_budget.py` to read it
**Out of scope for this ticket.** Rewiring `context_budget.py` changes the measurement contract and needs its own test coverage. Per the acceptance criterion "Scheduler/project-board behavior is unchanged" and the size:S scope, the consumer wiring is deferred to per-scenario tickets under epic #663.

### C — No config; document values inline in each command file
**Rejected.** Inlining policy in individual command files (`dark-factory-refine.md`, `dark-factory-implement.md`, etc.) creates N copies of the same defaults, making drift inevitable and future centralisation harder.

---

## Scope and non-goals

**In scope:**
- Single edit to `.claude/skills/refinement/config.yaml`: add `token_optimization:` block with defaults and `# env:` comments.

**Out of scope / deferred to epic #663 child tickets:**
- Wiring `context_budget.py` to read `default_budget_tokens`
- Per-scenario enforcement logic (architecture slicing, top-K memory retrieval, comment digesting, diff capping)
- Model escalation logic reading `escalation.opus_only_for`
- Any scheduler or board state changes

---

## Open questions (non-blocking)

None. The YAML schema is fully specified in the issue and confirmed by Q&A.

---

## Assumptions

1. The `# env:` comment convention in `config.yaml` is sufficient documentation for env override discovery — no separate ENV_VARIABLES.md update is needed for factory-internal vars.
2. `TOKEN_OPTIMIZATION_CHEAP_MODEL_FIRST` is the env var for `escalation.cheap_model_first` (inferred from the key path; confirm during implementation).
3. Future per-scenario tickets will read config via `yaml.safe_load(open('.claude/skills/refinement/config.yaml'))` or equivalent, matching the pattern used in `scheduler.sh`'s `SPEC_GRACE` read-back.

---

## Validation

The deliverable is a config YAML edit — no runtime behavior changes.

- Read-back check: `python3 -c "import yaml; d=yaml.safe_load(open('.claude/skills/refinement/config.yaml')); assert d['token_optimization']['enforce_budgets'] == False; assert d['token_optimization']['enabled'] == True; print('OK')"` passes.
- Docker rebuild smoke check: `docker compose --profile factory build dark-factory` completes without error; `docker compose --profile factory run --rm dark-factory python3 -c "import yaml; yaml.safe_load(open('/opt/refinement-skills/config.yaml'))['token_optimization']"` prints the block.
- Scheduler behavior: no scheduler or board state changes introduced; existing CI passes.

---

## Accepted trade-offs

- Adding config that nothing reads yet is intentional. Declaration-first design lets future tickets wire against a stable schema without requiring coordinated schema changes across multiple PRs.
- The baked-image delivery model means default changes require a rebuild. Env-var overrides mitigate this for the critical toggles (`enabled`, `enforce_budgets`).
