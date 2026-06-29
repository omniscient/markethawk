# Domain Docs

How the engineering skills should consume this repo's domain documentation when exploring the codebase.

## Before exploring, read these

- **`CONTEXT.md`** at the repo root — project glossary and domain language.
- **`docs/adr/`** — Architecture Decision Records for past design choices.

If any of these files don't exist, **proceed silently**. Don't flag their absence; don't suggest creating them upfront. The producer skill (`/grill-with-docs`) creates them lazily when terms or decisions actually get resolved.

## File structure

Single-context repo:

```
/
├── CONTEXT.md
├── docs/adr/
│   ├── 0001-polygon-for-market-data.md
│   └── 0002-celery-for-background-tasks.md
├── docs/agents/          ← you are here (skill configuration)
├── docs/superpowers/     ← feature specs and implementation plans
└── src/
```

Note: `docs/superpowers/specs/` holds **in-flight** feature specifications; `docs/superpowers/plans/` holds **in-flight** implementation plans. Both are write-once artifacts — shipped specs/plans are archived to `docs/archive/` automatically when an implementation PR is created. These are *not* ADRs; ADRs record architectural decisions and their rationale.

## Use the glossary's vocabulary

When your output names a domain concept (in an issue title, a refactor proposal, a hypothesis, a test name), use the term as defined in `CONTEXT.md`. Don't drift to synonyms the glossary explicitly avoids.

If the concept you need isn't in the glossary yet, that's a signal — either you're inventing language the project doesn't use (reconsider) or there's a real gap (note it for `/grill-with-docs`).

## Flag ADR conflicts

If your output contradicts an existing ADR, surface it explicitly rather than silently overriding:

> _Contradicts ADR-0007 (event-sourced orders) — but worth reopening because…_

## Memory Isolation and Agent Role Scoping

Dark Factory memory entries carry `project:` and `agentId:` tags:

- `project:markethawk` — all entries in this repo belong to this project; a future multi-project deployment can filter by project without modifying the files.
- `agentId:<role>` — the role identity that wrote the entry (e.g. `planning-agent`, `implementation-agent`). Distinct from `source:` which records the pipeline phase.

### Cross-agent read convention

**Validation, security, and gate agents MUST NOT call `load_memory()` for entries written by `implementation-agent` or `planning-agent` unless the caller explicitly declares the need.**

Today, `dark-factory-validate.md` and `dark-factory-conformance.md` do not read memory at all, so no leak is possible. When a validation or security agent begins reading memory, a follow-up ticket must add an `allow_agent_ids=` parameter to `load_memory()` that filters by `agentId:` at load time. Until that ticket is implemented, validation/security agents must not call `load_memory()`.

Role ID constants are defined in `dark-factory/scripts/agent_roles.sh`. The current 13 stable roles are:

| Constant | Value |
|---|---|
| `AGENT_ID_FACTORY_DIRECTOR` | `factory-director` |
| `AGENT_ID_INTAKE_TRIAGE` | `intake-triage-agent` |
| `AGENT_ID_REFINEMENT` | `refinement-agent` |
| `AGENT_ID_PLANNING` | `planning-agent` |
| `AGENT_ID_IMPLEMENTATION` | `implementation-agent` |
| `AGENT_ID_VALIDATION` | `validation-agent` |
| `AGENT_ID_CODE_REVIEW` | `code-review-agent` |
| `AGENT_ID_SECURITY` | `security-agent` |
| `AGENT_ID_DECONFLICT` | `deconflict-agent` |
| `AGENT_ID_CI_RESCUE` | `ci-rescue-agent` |
| `AGENT_ID_MERGE_GATE` | `merge-gate-agent` |
| `AGENT_ID_COST_TELEMETRY` | `cost-telemetry-agent` |
| `AGENT_ID_HUMAN_LIAISON` | `human-liaison-agent` |

Adding a new role requires a code change to `agent_roles.sh`; there is no dynamic registration.
