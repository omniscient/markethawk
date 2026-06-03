# Spec-Conformance Verification (Plan + Code) Design

**Date:** 2026-06-03
**Issue:** #162
**Component:** `.claude/skills/refinement/`, `.archon/commands/dark-factory-plan.md`, `.archon/commands/dark-factory-validate.md`, `.archon/workflows/archon-dark-factory.yaml`, `dark-factory/`

## Overview

The dark-factory refinement pipeline already ships an *architect* subagent intended to confirm that an implementation plan matches its approved spec. In practice the architect acts as a **plan proofreader** — it catches mechanical issues (wrong line numbers, miscounted `grep` matches, `awk`/`sed` ranges, missing commit steps, placeholders) but does not judge whether the plan is **faithful to the spec's intent**. Its single fidelity check ("Spec Coverage") only verifies that *a task exists per requirement* — coverage, not conformance. A plan can map one task to every requirement and still substitute a different design, drop a constraint, or expand scope, and pass.

Two gaps follow:

1. **No real plan-vs-spec fidelity judgment, and no explicit attestation.** The "Plan Generated" comment surfaces the architect's mechanical dialogue, not a clear "✅ this plan implements the spec."
2. **The implementation is never checked against the spec at all.** `implement` does TDD + docs; `validate` confirms tests pass and endpoints return `200`/`401` ("does it run") — never "does it do what the spec asked." Drift can go green, merge, and close undetected.

This design adds **end-to-end spec-conformance verification**: one reusable *conformance reviewer* that judges fidelity (approach, constraints, scope, semantic requirement satisfaction) — distinct from the mechanical architect — gating at two points (plan time and code time) and posting an attestation at each.

## Requirements

1. A single reusable conformance-reviewer persona, parameterized by what it reviews (`PLAN` or `IMPLEMENTATION`), that emits a **tiered verdict**: `CONFORMS` / `MINOR DEVIATION` / `MATERIAL DIVERGENCE`, with a per-requirement table and each deviation classified and justified.
2. **Gate 1 (plan vs spec):** after the architect's mechanical pass approves, run the conformance reviewer on plan-vs-spec. On `MATERIAL`, reuse the existing fix → re-review loop (≤ `max_reconcile_cycles`); if still material, label `needs-discussion`. Append a required `## Spec Conformance` section (verdict + attestation) to the "Plan Generated" comment.
3. **Gate 2 (code vs spec):** a new workflow node after `validate`, before `push-and-pr` (new/continue intents). Locate the spec, diff the branch, run the conformance reviewer on code-vs-spec, and apply the tiered outcome. Append the attestation to the "Dark Factory Run" report.
4. **Tiered divergence handling:** `CONFORMS` or `MINOR`/documented → proceed with an advisory note; `MATERIAL` → implement agent attempts a fix, re-review ≤ `max_reconcile_cycles`; resolved → proceed; still material → move to **Blocked + `needs-discussion`** and skip `push-and-pr`/`status-in-review`.
5. **No-spec fallback:** if no spec exists (a direct `Fix issue #N` that never went through refinement), the code gate degrades to advisory-only against the issue body and **never blocks**.
6. **Fail-open on error:** a reviewer/tooling *crash* (as opposed to a divergence *finding*) logs a warning and proceeds — it never blocks. Only a genuine `MATERIAL` finding blocks.
7. **Config:** a `conformance:` block in `config.yaml` (`enabled`, `max_reconcile_cycles`, `block_on_material`) so the gate is tunable and can be disabled.
8. The architect's overlapping "Spec Coverage" check is refocused to pure mechanics; fidelity moves entirely to the conformance reviewer.

## Architecture

### Clean division of labor

```
Plan phase:
  architect (mechanics)        →  "is this plan executable & self-consistent?"
  conformance reviewer (PLAN)  →  "is this plan faithful to the spec?"      [NEW]

Code phase (after validate):
  conformance reviewer (CODE)  →  "does the implementation match the spec?" [NEW]
```

The architect and the conformance reviewer are **separate subagents** so each stays focused — the architect's attention is no longer split between proofreading and fidelity, and the conformance verdict is always surfaced as its own attestation rather than buried in a mechanical dialogue.

### The reusable conformance reviewer

New persona file `.claude/skills/refinement/conformance-reviewer-prompt.md`. It receives the spec, the artifact (plan or implementation diff + summary), and an `$ARTIFACT_KIND` (`PLAN` | `IMPLEMENTATION`). It judges four dimensions per spec requirement/decision:

- **Approach fidelity** — did the artifact use the spec's *chosen* design, or silently substitute another?
- **Constraint adherence** — are the spec's explicit constraints honored?
- **Scope** — nothing silently added or dropped vs. the spec.
- **Requirement satisfaction** — semantic ("does this actually do X"), not "a task/file exists."

Output format (fixed):

```
## Spec Conformance — {Plan | Implementation}

**Verdict:** ✅ Conforms | ⚠️ Minor deviations (advisory) | ⛔ Material divergence
**Spec:** <path>

| Spec requirement / decision | Status | Note |
|---|---|---|
| ... | Conforms / Deviates | ... |

**Deviations:**
- [MINOR] <what> — <justification / why it's acceptable>
- [MATERIAL] <what> — <how it diverges from the spec>

**Cycles:** <n>   (present only when a reconcile loop ran)
```

`MATERIAL` is reserved for divergence that changes *what gets built* relative to the spec (different approach, dropped/added requirement, violated constraint). `MINOR` covers cosmetic or clearly-documented-and-justified deviations.

### Gate 1 — plan vs spec (`.archon/commands/dark-factory-plan.md`)

Insert a new phase after the existing architect review (Phase 3) and before Publish (Phase 4):

1. Build the same `$MEMORY_CONTEXT` already assembled for the architect.
2. Spawn the conformance reviewer with `$ARTIFACT_KIND=PLAN`, `$SPEC_CONTENT`, `$PLAN_CONTENT`.
3. If `MATERIAL`: revise the plan and re-spawn (reuse the architect loop mechanics), up to `max_reconcile_cycles`. Still material → post the conformance report, add `needs-discussion`, exit cleanly.
4. If `CONFORMS`/`MINOR`: proceed.
5. Publish: the "Plan Generated" comment gains a required `## Spec Conformance` section containing the reviewer's attestation (and the cycle dialogue if any).

### Gate 2 — code vs spec (new node in `.archon/workflows/archon-dark-factory.yaml`)

A new `command: dark-factory-conformance` node, `depends_on: [validate]`, `when: intent == new || continue`, placed before `push-and-pr`. The command (`.archon/commands/dark-factory-conformance.md`) runs the reconcile loop *inside* a single node invocation (the workflow is a DAG, not a loop — mirroring how `validate` runs its own Phase 3 FIX loop):

1. **Locate the spec** — via the "Plan Generated" comment's spec link → `$ARTIFACTS_DIR/refinement-status.md` → scan `Docs/superpowers/specs/` for the issue's topic. If none found → **no-spec fallback**: review code vs the issue body, advisory-only, never block; write status and exit `0`.
2. Read the diff (`git diff main...HEAD`) + `$ARTIFACTS_DIR/implementation.md`. Spawn the conformance reviewer with `$ARTIFACT_KIND=IMPLEMENTATION`.
3. Apply the tiered outcome:
   - `CONFORMS`/`MINOR` → write the attestation to `$ARTIFACTS_DIR/conformance.md`, exit `0` (PR proceeds; attestation merged into the run report).
   - `MATERIAL` → the agent fixes the code (TDD: failing test → implement → commit), re-spawns the reviewer, up to `max_reconcile_cycles`. Resolved → exit `0`. Still material → move the issue to **Blocked**, add `needs-discussion`, post a "Spec Conformance — Blocked" comment, exit non-zero so `push-and-pr` and `status-in-review` do not run.
4. The `report` node reads `$ARTIFACTS_DIR/conformance.md` and includes the attestation in the "Dark Factory Run" comment.

### Attestation surfacing

| Gate | Where posted |
|---|---|
| Plan vs spec | `## Spec Conformance` section appended to the "Plan Generated" comment |
| Code vs spec (pass) | `### Spec Conformance` section appended to the "Dark Factory Run" report |
| Code vs spec (block) | Dedicated "Spec Conformance — Blocked" comment + Blocked column + `needs-discussion` |

### Config (`.claude/skills/refinement/config.yaml`)

```yaml
conformance:
  enabled: true
  max_reconcile_cycles: 3
  block_on_material: true
```

`enabled: false` disables both gates (reviewer is skipped, runs proceed unchanged). `block_on_material: false` downgrades the code gate to advisory-only everywhere (attestation still posted, never blocks).

## Alternatives considered

- **Merge fidelity into the existing architect (one subagent).** Rejected: the architect already over-indexes on mechanics; adding fidelity to the same prompt would keep the verdict entangled and the attestation buried. A separate reviewer guarantees a distinct, always-surfaced conformance verdict.
- **Code gate as advisory-only (never blocks).** Rejected per the chosen tiered model — material drift should stop a PR from going ready, otherwise the gap that motivated this work remains open.
- **Hard block on *any* divergence (no auto-fix, no minor tier).** Rejected: it would re-introduce the false-Blocked / spam failure mode this project has been fighting (see #144, #160) by blocking on justified, documented deviations.
- **Fold the code gate into `dark-factory-validate.md`.** Reasonable, but validate's contract is "does it run." A dedicated node keeps "does it match the spec" a separate, independently-skippable concern with its own block semantics.

## Edge cases & safety

- **No spec present** → advisory-only against the issue body; never blocks (protects direct `Fix issue #N` flows).
- **Reviewer/tooling error vs. divergence finding** → a crash fails *open* (logged warning, proceed); only a genuine `MATERIAL` verdict blocks. This prevents a flaky reviewer from halting the line.
- **Runaway loop** → bounded by `max_reconcile_cycles` (default 3); the scheduler-level circuit-breaker (#160) covers anything that slips past.
- **`continue` intent** → the spec is re-located the same way; the gate re-runs against the updated diff.
- **Cost** → one extra subagent per plan run and per implement run, bounded by the cycle cap.

## Assumptions

- Refined issues that reached the plan phase have a spec file committed on their branch (the normal pipeline output); the plan-comment link is the primary discovery path.
- `git diff main...HEAD` is a faithful representation of the change set at validate time (the factory branches from `main` per `setup-branch`).
- The workflow halts dependents when a node exits non-zero (consistent with how `preview-up` failure stops the chain today).

## Open questions (non-blocking)

- Whether to also re-run the **plan** conformance attestation at code time as a 3-way (spec ↔ plan ↔ code) check, or keep the code gate anchored solely to the spec. Anchoring to the spec is the default; the spec is the source of truth.
- Whether `MINOR` deviations should accumulate into a follow-up "spec drift" note for the human reviewer. Deferred — advisory note in the attestation is sufficient for now.
