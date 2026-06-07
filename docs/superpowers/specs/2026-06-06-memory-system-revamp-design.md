# Dark Factory Memory System Revamp — Design

**Date:** 2026-06-06 (updated 2026-06-07)
**Status:** Pending review
**Author:** Brainstormed with Claude (Opus 4.8)
**Issue:** [#254](https://github.com/omniscient/markethawk/issues/254)
**Epic:** [#262 — Harden the Dark Factory self-improvement loop](https://github.com/omniscient/markethawk/issues/262)
**Downstream:** [#213](https://github.com/omniscient/markethawk/issues/213) gate→memory write-paths must conform to R2–R6 (see Contract Ownership section)
**Component:** `.archon/memory/`, `.archon/commands/dark-factory-implement.md`, `.archon/commands/dark-factory-refine.md`

## Problem

The `.archon/memory/` system persists lessons from each dark-factory run to guide future runs,
but it accumulates unverified, low-value, and occasionally wrong entries because:

1. **No correctness gate.** Empirical runtime claims ("X behaves like Y") are persisted as
   fact with no evidence requirement. Exhibit A: PR #244 added an entry asserting `Caddy exits
   cleanly when DOMAIN is unset` — empirically false, yet phrased as settled guidance for all
   future infra runs.
2. **Eagerness by construction.** The write prompt ("what did you learn this run?") biases
   toward writing something on every run. Most runs should add nothing.
3. **Factory-plumbing noise.** ~40% of `dark-factory-ops.md` is environment-specific bash/awk
   quirks (mawk vs gawk, `grep -c` exit codes, `set -e` gotchas) — one-off factory trivia
   injected as authoritative product-change context.
4. **Unbounded, undifferentiated growth.** Files are only pruned after 6-month TTL expiry.
   `dark-factory-ops.md` grew to 130 lines / ~18 KB and is pasted wholesale into every
   infrastructure-area plan and implement prompt.
5. **No invalidation path.** A proven-wrong entry cannot be marked or removed without a
   manual git edit; nothing prevents the same wrong claim from being re-added.

Current footprint: **5 files, ~293 lines, ~36 KB total** (as of 2026-06-06).

## Goal

Deliver a single PR that:

1. **Audits and prunes** all ~79 existing entries to a high-signal core, with documented
   before/after entry counts per file.
2. **Revamps the write/curate/consume loop** in both command files (`dark-factory-implement.md`
   Phase 5, `dark-factory-refine.md` Phase 5) so the system stops accumulating noise
   going forward.

## Contract Ownership — Epic #262 and #213

This spec's requirements (R2–R6) constitute the **canonical memory write contract** for the Dark Factory. Per [Epic #262 — Harden the Dark Factory self-improvement loop](https://github.com/omniscient/markethawk/issues/262) sequencing (#213 audit → **#254** → #213 write-paths → #224/#215):

- Any memory write path introduced or modified by [#213](https://github.com/omniscient/markethawk/issues/213) must emit entries conforming to this contract — same entry tags (`[PATTERN]`/`[PROVISIONAL]`/`[INVALID]`), same `evidence:` comment format (R2), same cap/dedup rules (R3/R4), same provisional-section placement (R2). #213 must not introduce a second write-format or categorisation scheme.
- #213's `path:<prefix>` routing/relevance-filtering scheme is #213's mechanism to own; this spec does not implement it. However, any entries that #213's gate→memory writes produce must land in conforming format under this contract.
- This spec's answer to "product lessons vs. factory-ops trivia separation" is **deletion**: ops trivia is dropped (R1/R3), not routed to a separate file. That resolves the overlap with #213's "path:<prefix>" concept — no ops-routing file will be created here; #213's implementation must reconcile with that decision.

## Non-Goals (v1)

- A separate scheduled compaction task or new Docker service.
- A "memory reviewer" subagent that runs on every issue.
- A factory runbook file (non-injected trivia storage) — dropped entries are simply deleted.
- Semantic similarity / vector search for deduplication.
- Implementing `path:<prefix>` routing (that is #213's scope; it must conform to this contract).

## Requirements

### R1 — One-time audit and prune (scope part 1)

Classify every existing entry across all 5 memory files as **keep**, **fix**, **demote**, or
**drop** using the rubric below (same rubric that governs new writes going forward):

| Verdict | Criterion |
|---------|-----------|
| keep    | Correct, general beyond one run, reusable, decision-changing for a future agent |
| fix     | True fact, but mis-stated or imprecisely worded — rewrite the entry, keep it |
| demote  | Correct but factory-environment trivia (bash quirks, awk compat, etc.) — delete |
| drop    | Wrong, stale, redundant, or so situational it cannot recur — delete |

For every entry, record the verdict and one-line rationale in the PR description (not in the
memory files themselves). Before/after counts per file must appear in the PR description.

**Correctness verification requirement:** Any "keep" entry that asserts runtime behavior
(i.e., "X does Y when Z") must have its claim quickly verified against the current codebase or
a quick `docker exec` before being kept. Any claim that cannot be confirmed is downgraded to
provisional (see R2) or dropped.

### R2 — Provisional tier for empirical claims (new entry type)

Introduce a `[PROVISIONAL]` entry type. Rules:

- Any entry asserting runtime behavior (container behavior, CLI tool output, framework quirks)
  that the writing agent observed on **this run only** must be written as `[PROVISIONAL]`, not
  `[PATTERN]`.
- `[PROVISIONAL]` entries must carry an `evidence:` field in the inline comment describing
  *how* the behavior was observed, e.g.:
  ```
  <!-- evidence:docker-exec:caddy caddy adapt ... issue:#254 date:2026-06-06 expires:2026-12-06 source:implement -->
  ```
- `[PROVISIONAL]` entries are **excluded from authoritative prompt injection**. They live in a
  clearly-labelled fenced section at the bottom of the relevant memory file:
  ```markdown
  ---
  <!-- PROVISIONAL — unverified; do not treat as authoritative guidance -->
  - [PROVISIONAL] ...
  ```
  When the plan/implement workflows cat a memory file into a prompt, they must skip this
  section (or include it with the same "unverified" header so agents know not to rely on it).
- **Promotion to `[PATTERN]`:** A `[PROVISIONAL]` entry is promoted only when a subsequent run
  (different issue number) observes the same behavior and adds its own `evidence:` comment.
  The promoting agent rewrites the entry as `[PATTERN]` and adds the second evidence tag.
- **Non-promotion expiry:** Provisional entries that are not promoted within their TTL
  (standard 6 months) are dropped during the next expiry cleanup — no manual review needed.

### R3 — Raise the write bar (Phase 5 rubric change)

Replace the current Phase 5 write prompt ("what patterns did you discover…?") with an
explicit **default-to-nothing** rule:

> Before adding any memory entry, ask: "Would a future agent make a materially different
> decision because of this entry, compared to reading CLAUDE.md and ARCHITECTURE.md alone?"
> If no, skip the entry. Most runs should add zero entries.

Additional filters (already partially present; made explicit):
- **Not factory trivia.** Shell compatibility quirks, environment-specific workarounds, and
  one-off debugging steps are deleted, not written.
- **Not in CLAUDE.md / ARCHITECTURE.md.** Entries that duplicate documented conventions are
  silently dropped.
- **Not a near-duplicate.** The existing `grep -F` dedup check remains; agents must also
  visually scan the nearby entries for near-duplicates before writing.
- **Empirical → provisional.** Any runtime-behavior claim goes through the provisional tier
  (R2) first.

### R4 — Per-file entry cap (consolidation)

Each memory file has a hard **30-entry cap** on `[PATTERN]`, `[AVOID]`, and `[FIX]` lines
combined (provisional entries are counted separately and capped at 10 per file).

After appending a new entry, if the authoritative entry count exceeds 30, the implement
agent must drop the oldest expired or lowest-signal entries before committing. Drop criteria
(in order): expired TTL first, then entries whose scope is entirely covered by a
newer/broader entry, then the oldest entries by date.

This is enforced inline in Phase 5 — no separate tooling.

### R5 — Invalidation path for promoted [PATTERN] entries

When an implement or refine agent proves an existing `[PATTERN]` is wrong:

1. Replace the `[PATTERN]` tag with `[INVALID]`.
2. Append a brief reason inline: `[INVALID: <one-phrase reason>]`.
3. The consume-side injection filter must skip `[INVALID]` entries (same as `[PROVISIONAL]`).
4. `[INVALID]` entries are tombstones — they count toward the cap and expire on their original
   TTL, preventing the same wrong claim from being re-added during the validity window.

For provisional entries: non-confirmation (a second run observes the opposite) simply deletes
the provisional entry. No `[INVALID]` tombstone needed — it never became authoritative.

### R6 — Consume-side injection filter updates

Both `dark-factory-plan.md` (Phase 3 `$MEMORY_CONTEXT` block) and any other command file
that cats memory files into prompts must be updated to:

1. Strip the `<!-- PROVISIONAL … -->` fenced section from the pasted content **or** include
   it with an explicit `<!-- UNVERIFIED: do not rely on these entries -->` header.
2. Skip `[INVALID]` tagged lines entirely.

The simplest implementation: use `grep -v '^\- \[PROVISIONAL\]\|^\- \[INVALID\]'` when
building `$MEMORY_CONTEXT`, and separately include the provisional section with the unverified
header.

## Architecture / Approach

### Implementation sequence (within a single PR)

**Step 1 — Define rubric** (this spec). Commit the spec file.

**Step 2 — Audit existing entries.** Read every entry across all 5 memory files. Apply the
keep/fix/demote/drop rubric from R1. For any empirical "keep" entry, verify or downgrade to
provisional. For any "fix" entry, rewrite it. Delete all "demote" and "drop" entries.
Commit with message `memory: audit and prune (issue #254, <before>→<after> entries)`.

**Step 3 — Update Phase 5 (implement agent).** Rewrite Phase 5 of
`.archon/commands/dark-factory-implement.md` to:
- Replace the write prompt with the default-to-nothing rubric (R3).
- Add the provisional tier rules (R2) with the evidence comment format.
- Add the per-file cap check and trim logic (R4).
- Document the `[INVALID]` tombstone procedure (R5).

**Step 4 — Update Phase 5 (refine agent).** Apply the same rubric changes to the memory
write section of `.archon/commands/dark-factory-refine.md` (the refine agent's equivalent
of Phase 5).

**Step 5 — Update consume-side injection filters.** Update the `$MEMORY_CONTEXT` building
blocks in `dark-factory-plan.md` (and any other consume site) to filter `[PROVISIONAL]` and
`[INVALID]` lines per R6.

**Step 6 — Verify.** Run `wc -l .archon/memory/*.md` before and after. Confirm the footprint
is substantially reduced (target: `dark-factory-ops.md` ≤ 30 authoritative entries, overall
total ≤ 120 lines across all 5 files). Confirm the provisional section format renders
correctly.

### Entry count targets (post-audit)

| File                   | Current lines | Target authoritative entries |
|------------------------|---------------|------------------------------|
| architecture.md        | 23            | ≤ 10                         |
| backend-patterns.md    | 54            | ≤ 20                         |
| codebase-patterns.md   | 26            | ≤ 10                         |
| dark-factory-ops.md    | 130           | ≤ 30                         |
| frontend-patterns.md   | 60            | ≤ 20                         |

These are ceilings, not targets — fewer is better.

### Provisional section format

```markdown
---
<!-- PROVISIONAL — entries below are from a single observed run; unverified.
     Do not rely on these as authoritative guidance. They are excluded from
     plan/implement prompt injection except as advisory context.
     Each will be promoted to [PATTERN] on second-run confirmation or dropped at TTL. -->

- [PROVISIONAL] <claim> <!-- evidence:<method> issue:#N date:YYYY-MM-DD expires:YYYY-MM-DD source:implement -->
```

## Alternatives Considered

### Alt A — Reviewer subagent gate (rejected)

A "memory reviewer" LLM call that approves/rejects entries before commit. Rejected because:
it's LLM-policing-LLM (the same model that wrote the entry reviews it — low independence),
adds cost on every run, and introduces factory-plumbing complexity (the root cause 3 we're
trying to eliminate). The provisional tier achieves correctness through independent confirmation
over time, which is higher-signal.

### Alt B — Factory runbook file for trivia (rejected)

A `.archon/memory/factory-runbook.md` that stores bash/awk quirks without being injected
into prompts. Rejected because: no agent reads it (operator model is LLM-only), it creates
an ambiguous "memory that isn't memory" category, and low-durability environment quirks rot
silently. Entries that don't meet the write bar are simply deleted.

### Alt C — Separate audit PR, then mechanism revamp PR (rejected)

Shipping the prune first and the mechanism revamp later. Rejected because: (a) the prune
rubric requires defining the new write bar first — you can't audit without the criteria,
(b) if the mechanism lands late, the unguarded loop re-pollutes the pruned files immediately,
and (c) both scopes are localized to the same 2 command files + 5 memory files, making the
combined PR tractable.

## Open Questions (non-blocking)

1. **`dark-factory-plan.md` and other command files** — the plan file references `cat` of
   full memory files at lines 48-65. The R6 filter should be applied there, but it may also
   touch `dark-factory-conformance.md` and `dark-factory-code-review.md` if those files
   consume memory. Implement agent should grep for all consume sites before Step 5.

2. **Near-duplicate merge during audit** — the rubric says "merge near-duplicates," but the
   exact-substring `grep -F` dedup didn't catch these. If two entries cover 90% of the same
   ground, the implement agent should merge them into one, not keep both. No tooling needed —
   judgment call per entry during Step 2.

3. **Provisional-section injection behavior for `dark-factory-refine.md`** — the refine
   agent currently loads memory in Phase 1. It should apply the same `[PROVISIONAL]`/
   `[INVALID]` filter. Confirm during Step 4 that the refine Phase 1 load section is updated
   alongside Phase 5.

## Assumptions

- [A1] The awk prune script in Phase 5 stays `mawk`-compatible (three-argument `match()` must
  not be used). The existing two-argument form with `substr()` remains correct — no change
  needed to the expiry cleanup script.
- [A2] The 30-entry cap per file is a hard limit on authoritative (`[PATTERN]`/`[AVOID]`/
  `[FIX]`) entries; provisional entries (capped at 10) are tracked separately. The cap is
  evaluated by the agent counting `^\- \[PATTERN\]\|^\- \[AVOID\]\|^\- \[FIX\]` bullets.
- [A3] "Different issue number" is the minimum bar for second-run confirmation. Same-issue
  re-runs (e.g., `continue` runs) do not count as confirmation — they would introduce a
  same-context echo chamber.
- [A4] The consume-side filter (`grep -v`) is applied by the orchestrating shell script
  building `$MEMORY_CONTEXT`, not by the subagent reading the memory. The subagent always
  receives clean, pre-filtered content.
