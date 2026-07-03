# Dark Factory Extraction — Standalone Repo + Per-Target Adapters

**Status:** design
**Date:** 2026-07-03
**Epic:** (created from this document; see Decomposition)
**Builds on:** the entire dark-factory lineage in this repo — scheduler/board machinery, refinement pipeline, token-optimization epics #663/#713, memory contract, replay bench suite

---

## Problem

Dark Factory and MarketHawk have diverged in purpose and maturity. The factory is a general autonomous-development harness — scheduler, refinement pipeline, gates, token optimization, agent memory, replay benchmarking — that happens to live inside one trading application's repository. The coupling costs both sides:

- Factory improvements ship through MarketHawk's CI, board, and release cadence.
- MarketHawk's repo carries ~a third of its content as tooling unrelated to trading.
- The factory cannot be pointed at any other project, although nothing in its architecture truly requires MarketHawk.

The factory is mature enough to be reused as-is on other projects. It should live in its own repository with a per-target adapter mechanism.

## Settled decisions (brainstormed 2026-07-03)

1. **Consumption model: standalone instance per target repo.** The factory repo ships an image + a small deploy stack; you run one factory instance per target project. No multi-tenant scheduler, no vendored copies.
2. **Adapters live in the target repo** as a `.factory/` directory. The factory defines the schema and fail-open defaults and reads the adapter from its fresh clone of the target — preserving the clone-read property (config changes live on the next run, no rebuild).
3. **Adapter shape: config + hook scripts.** `adapter.yaml` for everything that is data; an optional `hooks/` directory of named executables for everything that is behavior (smoke-gate, validate, preview-up/down). Chosen over config-only (too weak for real targets: MarketHawk's smoke gate imports the backend app; preview is a compose+BuildKit dance) and over plugin packages (packaging ceremony for two consumers; a hook can invoke anything, so the plugin option stays reachable later).
4. **Migration: strangler with history.** `git filter-repo` extraction preserving history/blame; MarketHawk keeps running its in-repo factory until the extracted one passes the replay bench parity gate; then cut over and delete the in-repo copy.
5. **Dogfooding from day one.** The factory repo gets its own `.factory/` adapter, board, and instance — it develops itself the way it develops MarketHawk today. Adapter #1 (Python/FastAPI trading app) + adapter #2 (bash/Python devops tool) is the proof the contract generalizes.
6. **Name:** `omniscient/dark-factory`, private. Generic image: `ghcr.io/omniscient/dark-factory`.

## Architecture

### The two repos after the split

**`omniscient/dark-factory`** — everything that is machinery:

- `scheduler.sh`, `entrypoint.sh`, `Dockerfile`, `smoke_gate` defaults
- `scripts/` — `factory_core/` (de-hardcoded: repo/owner/board ids come from instance config), token-optimization suite, gates (`check_workflow_dag`, `gate_blast_radius`, diff ranking, comment digest…), memory machinery
- Archon workflow (`archon-dark-factory.yaml`) + `dark-factory-*.md` command prompts
- Refinement skills (today's `.claude/skills/refinement/`)
- `config/` — core config **schema + fail-open defaults**. Today's `refinement/config.yaml` splits: generic defaults live here; target-specific values move to the target's adapter and merge over the defaults.
- Evals framework (`token_opt_eval.py` and friends — generic parts)
- `deploy/` — per-instance compose stack (scheduler + docker-socket-proxy + optional BuildKit) and instance-config template (`TARGET_REPO`, `GH_TOKEN`, `CLAUDE_CODE_OAUTH_TOKEN`, `FACTORY_WIP_LIMIT`, poll interval…). Secrets are instance-local, never committed to either repo.
- Generic operator docs: memory contract, triage-label vocabulary, token-optimization runbook
- Its own `.factory/` adapter + project board (dogfood)
- CI: full test suite + publishes `ghcr.io/omniscient/dark-factory:latest`. Target repos never build the factory image; MarketHawk's `docker-dark-factory` required check moves here.

**MarketHawk (any target)** — everything that is knowledge about the target:

- `.factory/` adapter (below)
- Its board, labels, preview compose — referenced by the adapter, otherwise unchanged
- Target-scoped agent memory (the memory contract's existing scoping matrix already draws this line: codebase-patterns stay with the target; factory-ops patterns move to the factory repo's own memory)

The factory still clones the target and opens PRs against it exactly as today. The extraction changes where the machinery lives, not how it touches targets.

### Adapter contract

```
.factory/
  adapter.yaml        # schema-versioned, validated at dispatch
  hooks/              # optional executables, discovered by name
    smoke-gate        # is target main healthy? (MH: import backend app)
    validate          # post-implement checks (MH: curl endpoints, tsc, alembic)
    preview-up        # per-issue preview stack (MH: compose + BuildKit)
    preview-down
  bench/suite.json    # optional: replay-benchmark corpus for this target
  memory/             # target-scoped agent memory
```

`adapter.yaml` (data only, merged over factory defaults):

- `schema_version`, `repo` (owner/name), board + label ids
- `components:` — component → ARCHITECTURE.md-section map (today's hardcoded `COMPONENT_SECTION_MAP`)
- `safety:` — critical diff-tier path patterns, sensitive keywords, hard-exclude paths, dispatch-ceiling keywords (today's scattered `trading|ibkr`, `auth/`, `migrations` constants)
- `token_optimization:` — per-target overrides of budgets/caps (factory ships defaults; MarketHawk's calibrated values move here)

**Hook contract:** each hook is an executable invoked with a documented environment (`CLONE_DIR`, `ARTIFACTS_DIR`, `ISSUE_NUM`, …) and documented exit-code semantics. Missing hook → generic default (no `smoke-gate` → "does the test command pass"). Hooks declared as *gates* (smoke-gate) may block dispatch; all others fail open — the same philosophy the factory uses everywhere today. No new trust boundary: the factory already executes the target's test suite.

**Validation:** at dispatch, the factory schema-validates `adapter.yaml`. Missing/invalid adapter → clear ticket comment + skip (fail-closed for dispatch: a factory pointed at an unconfigured repo refuses loudly). Unknown extra keys warn but do not fail, so newer adapters run against older factories.

Deliberately **not** in the adapter: secrets (instance `.env` only) and non-target-specific tuning (WIP limits, poll interval — instance config).

### Runtime

One instance = one deploy directory created from the factory repo's `deploy/` template: compose stack + instance `.env`. The scheduler polls the *target's* project board, clones the target fresh per run, and reads `.factory/` from the clone. A `factory init` bootstrap command provisions a new target: creates the label vocabulary + project board via `gh` and opens a scaffold PR adding a starter `.factory/` to the target repo.

## Migration plan (strangler, four phases, each independently shippable)

- **P0 — Extract.** `git filter-repo` the factory paths (`dark-factory/`, `.archon/workflows|commands`, refinement skills, factory docs) into `omniscient/dark-factory` with full history. Stand up CI (tests + image publish). MarketHawk untouched; its in-repo factory keeps running current work.
- **P1 — Generalize.** De-hardcode `factory_core` (repo/owner/board → instance config). Build the adapter loader + schema + defaults. Convert today's MarketHawk-specific constants into the *default values* so behavior is bit-identical when no adapter overrides them. Unit tests + DAG validator throughout.
- **P2 — Parity.** Author MarketHawk's `.factory/` adapter (in the MarketHawk repo). Run the replay bench suite through the **extracted** factory against MarketHawk and compare pass^k with the in-repo baseline. The bench suite is the objective cutover gate.
- **P3 — Cut over + clean up.** Repoint MarketHawk's scheduler instance at the extracted image. Observe a few real tickets. Then delete `dark-factory/` + `.archon/` machinery + refinement skills from MarketHawk. Rollback until this point is trivial: the in-repo factory still exists; reverting = repointing the scheduler image back.
- **P4 — Dogfood.** Give the factory repo its own board + minimal adapter; put its first self-mod ticket through itself.

P0–P2 do not touch MarketHawk's running factory; in-flight epics (e.g. #729) continue undisturbed. The only coordination point is the P3 cutover, done when the board is quiet.

## Testing

- The existing factory test suite moves with the code in P0 (filter-repo preserves it).
- P1 adds adapter-contract tests: schema validation, default-merge semantics, hook discovery and fallback.
- P2's bench-suite parity run is the regression gate for the whole extraction.
- P4's first self-mod ticket is the end-to-end proof of the dogfood loop.

## Error handling

- Invalid/missing adapter: fail-closed at dispatch with a clear ticket comment (never improvise against an unconfigured repo).
- Hooks: fail-open unless declared gates, matching current factory philosophy.
- Adapter schema evolution: `schema_version` + warn-don't-fail on unknown keys.

## Non-goals

- Multi-tenant scheduling (one instance serves one target).
- Open-sourcing / packaging for external users (structure shouldn't preclude it, but nothing is designed for it now).
- Changing how the factory develops targets (workflow DAG, gates, refinement pipeline are moved and parameterized, not redesigned).
- Migrating Archon (already a separate repo).

## Open questions (non-blocking)

1. **Board provisioning idempotency** — `factory init` re-run against an existing target should reconcile, not duplicate. Decide during P1 design.
2. **Shared memory promotion** — when a target-scoped memory entry is really a generic factory lesson, is promotion manual or does memory_maintain suggest it? Follow-up after P4.
3. **Instance supervision** — with 2+ instances (MarketHawk + dogfood), is there any shared dashboard, or is per-instance Seq enough? Defer until it hurts.

## Decomposition

Each phase is its own epic-sized unit of work; P0+P1 could be one epic ("extraction"), P2+P3 a second ("cutover"), P4 a third ("dogfood"). Detailed ticket decomposition happens in the implementation plan, not here — but the phase boundaries above are the intended epic boundaries, and each phase ends in a shippable, observable state.
