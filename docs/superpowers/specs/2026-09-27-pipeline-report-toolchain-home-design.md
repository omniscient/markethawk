# Pipeline-Report Toolchain: Consolidate into Dark Factory — Design Spec

**Issue:** #869
**Date:** 2026-09-27
**Status:** Proposed — pending implementation plan (cross-repo; requires a sibling
`omniscient/dark-factory` PR before the MarketHawk half can land)

## 1. Overview / Problem Statement

MarketHawk's Dark Factory automation was extracted to `omniscient/dark-factory` in commit
148652f (#790). A follow-up deep audit (#799) found the **pipeline-report toolchain** —
`scripts/fetch_metrics.py`, `fetch_scorecard.py`, `ceiling_revisit.py`, `generate.sh`,
`render_report.py`, `template.html`, `echarts.min.js`, the committed `metrics.json` /
`scorecard.json` snapshots, `docs/pipeline-report*.html`, `tests/scripts/*`, and the
2026-06-04 pipeline-metrics spec/plan — still fully present in MarketHawk after the
extraction, and flagged it as an undecided item: dark-factory already carries **diverged
forks** of two of the files (`fetch_scorecard.py`, `ceiling_revisit.py`), so leaving both
copies in place risks the two forks silently drifting apart.

Issue #869 asked for a final decision between (1) consolidating into dark-factory or (2)
keeping the toolchain in MarketHawk with anti-drift measures. The repo owner resolved this
directly in an issue comment: **"Pipeline needs to move to dark factory!"** This spec designs
the consolidation: what moves, what stays, in what order, and how to verify the move didn't
silently change behavior before anything is deleted.

This is a **repo-topology decision**, not an application feature — the toolchain measures the
factory's own delivery performance (issue/PR throughput, cost, regression rate) on
MarketHawk's GitHub history; it does not touch scanner, trading, or any customer-facing code
path.

## 2. Requirements (from Q&A)

1. **Move the whole toolchain, not just the two already-forked files.** `fetch_metrics.py`,
   `render_report.py`, `template.html`, `echarts.min.js`, and `generate.sh` — none of which
   have a dark-factory fork today — must be ported and generalized into
   `omniscient/dark-factory` in a sibling PR, following the same generalization pattern
   already used for `fetch_scorecard.py` (hardcoded `REPO`/identity constants become
   env-driven with defaults that reproduce today's MarketHawk-hardcoded behavior when unset).
   `generate.sh` additionally needs a target-dir/output-path argument so it can render into an
   arbitrary target repo's checkout rather than only `omniscient/dark-factory`'s own.
2. **`fetch_scorecard.py` and `ceiling_revisit.py`: consolidation = deletion.** Their
   dark-factory forks are already a strict superset of the MarketHawk copies (verified by
   diff — same logic, generalized identity resolution, `--repo` flag added) and are already
   the live production path: `.archon/commands/ceiling-revisit.md` invokes
   `dark-factory/scripts/fetch_scorecard.py` and `dark-factory/scripts/ceiling_revisit.py`
   directly today. No porting work is needed for these two; only deletion of the MarketHawk
   copies, gated on the verification in Requirement 4.
3. **Rendered report artifacts stay in MarketHawk; intermediate JSON does not.**
   `docs/pipeline-report.html` and `docs/pipeline-report-comparison-2026-06-04-vs-2026-06-26.html`
   remain committed in MarketHawk — this repo's own delivery history, on the same footing as
   `.archon/memory/` and `.factory/adapter.yaml` staying per-target after the main extraction
   (CLAUDE.md). Root `metrics.json` and `scorecard.json` are deleted: they are intermediate
   render inputs, not the product, and the already-live `ceiling-revisit` flow treats
   equivalent scorecard data as ephemeral (writes to `/tmp/`, never commits it). The original
   design spec (`docs/superpowers/specs/2026-06-04-pipeline-metrics-report-design.md`) and its
   plan stay as historical record, with a tombstone note (Requirement 6).
4. **Gate MarketHawk deletion on a structural parity check**, not a live-run diff (a live diff
   would spuriously fail on `generated_at` timestamps and live GitHub data drift):
   - **Render parity:** feed the committed `metrics.json`/`scorecard.json` (frozen inputs) to
     both the old MarketHawk `render_report.py` and the new dark-factory `render_report.py`;
     the two `pipeline-report.html` outputs must be **byte-identical** (sha256 compare).
   - **Fetch parity:** run the old and new `fetch_metrics.py`/`fetch_scorecard.py`
     back-to-back against `omniscient/markethawk`; JSON outputs must match once
     `generated_at` is stripped (`jq -S 'del(.generated_at)'`).
   - **End-to-end run:** dark-factory's `generate.sh`, invoked with its new target-dir/output
     argument pointed at the MarketHawk checkout, must produce `docs/pipeline-report.html`
     without error, and the ported `render_smoke.cjs` must pass against it. This refreshed
     report is committed as part of the MarketHawk deletion PR.
   - Hashes and diff results are recorded as evidence in the MarketHawk PR description.
5. **Tests move with the code, and consolidate rather than duplicate.**
   `tests/scripts/test_fetch_metrics.py`, `test_fetch_scorecard.py`, `test_render_report.py`,
   and `render_smoke.cjs` port into dark-factory's test suite (which should wire them into its
   own CI — MarketHawk's CI never collected `tests/scripts/*` anyway, since the CI pytest step
   runs with `working-directory: backend`). The root-level `scripts/test_ceiling_revisit.py` is
   deleted outright without porting: dark-factory already has its own
   `test_ceiling_revisit.py` + `test_ceiling_revisit_command.py` for that fork.
6. **Old spec/plan get a tombstone, not a rewrite.** Add a short blockquote under the Status
   line of `docs/superpowers/specs/2026-06-04-pipeline-metrics-report-design.md` and its
   matching plan noting the toolchain moved to `omniscient/dark-factory` on `<merge date>` via
   #869 / dark-factory PR `#<n>`, and that file paths in the body refer to the pre-extraction
   MarketHawk layout. Leave the rest of the body untouched. This is added in the MarketHawk
   deletion PR (it needs the real merge date and PR number, not available at spec time).
7. **Preserve the two named contracts across the move** (issue-mandated): the
   `<!-- dark-factory-cost-report -->` marker and the `factory@markethawk` author-email
   fingerprint.
   - Only `fetch_metrics.py` reads the marker (currently a hardcoded literal at two call
     sites); the marker is *written*/owned by `dark-factory/scripts/factory_core/cost_report.py`
     (`COST_MARKER`) and re-hardcoded again in `cost_report_marker_check.py`, `comment_digest.py`,
     and `factory_core/identity.py`. The ported `fetch_metrics.py` **must import `COST_MARKER`**
     from `factory_core/cost_report.py` instead of redefining the literal string — if that's
     too invasive for the sibling PR, it must instead add a test asserting the two stay equal.
   - Only `fetch_scorecard.py` reads the email (hardcoded `factory@markethawk` in the
     MarketHawk copy); the dark-factory fork already generalizes it via `FACTORY_EMAIL` env
     with a default that reproduces `factory@markethawk` for this repo. The sibling PR must
     add a test asserting `fetch_scorecard.py`'s default `FACTORY_EMAIL` resolves to the same
     email the factory actually uses as commit author for a given `FACTORY_REPO`.
   - `ceiling_revisit.py` and `render_report.py` reference neither contract directly (the
     former depends on the email only indirectly, by invoking `fetch_scorecard.py` as a
     subprocess). Neither contract is enforced by MarketHawk CI or pre-commit today, so nothing
     needs to be kept in place there after deletion.
8. **Sequencing is a hard dependency, not a suggestion.** The MarketHawk PR deletes nothing
   until (a) the dark-factory sibling PR has merged, and (b) the Requirement 4 verification
   run has passed against this checkout. Only then does the MarketHawk PR delete
   `scripts/fetch_metrics.py`, `fetch_scorecard.py`, `ceiling_revisit.py`, `generate.sh`,
   `render_report.py`, `template.html`, `echarts.min.js`, `metrics.json`, `scorecard.json`,
   `tests/scripts/test_fetch_metrics.py`, `test_fetch_scorecard.py`, `test_render_report.py`,
   `render_smoke.cjs`, and `scripts/test_ceiling_revisit.py`; commit the refreshed
   `docs/pipeline-report.html`; add the tombstone notes; and update any doc references (e.g.
   `PROJECT_STRUCTURE.md`) that point at the deleted `scripts/` paths.

## 3. Architecture / Approach

Two sequential PRs, executed in this order:

**PR 1 — `omniscient/dark-factory` (sibling, out of this repo's scope):**
- Port `fetch_metrics.py`, `render_report.py`, `template.html`, `echarts.min.js` into
  `dark-factory/scripts/`, generalized the same way `fetch_scorecard.py` already was:
  `REPO = "omniscient/markethawk"` → resolved from `FACTORY_REPO_SLUG` (or a `--repo` flag),
  defaulting to reproduce today's MarketHawk-hardcoded value when unset.
- Port `generate.sh`, adding a target-dir/output-path argument so it writes into an arbitrary
  target repo's checkout (mirroring how `ceiling-revisit.md` already calls the dark-factory
  scorecard/ceiling scripts against MarketHawk without them living here).
- `fetch_metrics.py` imports `COST_MARKER` from `factory_core/cost_report.py` rather than
  redefining the marker literal (Requirement 7).
- Port `tests/scripts/test_fetch_metrics.py`, `test_fetch_scorecard.py`, `test_render_report.py`,
  `render_smoke.cjs` into dark-factory's test suite and wire them into dark-factory's CI. Add
  the `FACTORY_EMAIL` default-resolution test and (if `COST_MARKER` isn't imported directly)
  the marker-equality test from Requirement 7.
- No changes needed to `fetch_scorecard.py`/`ceiling_revisit.py` — already generalized — or to
  `.archon/commands/ceiling-revisit.md` — already calls the dark-factory forks.

**PR 2 — `omniscient/markethawk` (this repo, after PR 1 merges):**
- Run the Requirement 4 parity check against this checkout using the merged dark-factory
  tooling; record hashes/diffs in the PR description.
- Delete the MarketHawk copies listed in Requirement 8.
- Commit the freshly-regenerated `docs/pipeline-report.html` (produced by the new
  dark-factory-hosted `generate.sh` targeting this checkout).
- Add tombstone blockquotes to the 2026-06-04 spec and plan (Requirement 6).
- Update stale path references (e.g. `PROJECT_STRUCTURE.md`, any remaining CLAUDE.md/
  ARCHITECTURE.md mentions of the deleted `scripts/` files) to point at
  `omniscient/dark-factory`.

This mirrors the exact pattern #799/#800/#802 already used for the rest of the factory
extraction: generalize-and-fork first, verify equivalence, then delete the residue — rather
than a single big-bang cutover.

## 4. Alternatives Considered

- **Keep in MarketHawk, stop the fork drift (issue's option 2).** Rejected: overridden by the
  owner's explicit "Pipeline needs to move to dark factory!" comment, and inconsistent with
  the extraction principle already applied to every other piece of factory tooling (#790,
  #799). Would also require actively working to *re-converge* `fetch_scorecard.py`/
  `ceiling_revisit.py` back into MarketHawk from the already-diverged, already-live
  dark-factory forks — more work than deleting the MarketHawk copies.
- **Move the rendered report artifacts too (fully multi-tenant dashboard in dark-factory).**
  Rejected for this pass: `docs/pipeline-report.html` and its data represent MarketHawk's own
  delivery history specifically, analogous to `.archon/memory/` and `.factory/adapter.yaml`
  staying per-target. Centralizing report *output* across all onboarded target repos is a
  bigger, separate design question (multi-tenant storage, cross-repo comparison views) not
  raised by this issue.
- **Live-run byte-diff as the verification gate.** Rejected: `fetch_metrics.py` stamps
  `generated_at` with `datetime.now()` and re-pulls live GitHub state on every run, so two
  live runs at different times would diverge for reasons unrelated to the code move. The
  frozen-input structural parity check (Requirement 4) isolates the comparison to the code
  itself.
- **Keep root `metrics.json`/`scorecard.json` committed for provenance.** Considered, since
  #799's audit methodology values hash-verifiable history. Rejected as the default: they are
  regenerable intermediate artifacts, the rendered HTML already embeds their data, and the
  already-live `ceiling-revisit` flow treats equivalent data as ephemeral. Flagged below as
  the one call the owner may want to override.

## 5. Open Questions (non-blocking)

- Should `docs/pipeline-report-comparison-2026-06-04-vs-2026-06-26.html` (a point-in-time
  diff between two historical snapshots) be regenerated going forward via dark-factory
  tooling, or was it a one-off and can be left as-is indefinitely? No cadence for
  regenerating comparison reports is documented anywhere in the codebase.
  - **Recommended default absent further input:** treat it as a one-off; no action required
    unless/until someone requests a new comparison.
- Exact form of the `FACTORY_EMAIL`-resolution test (Requirement 7) — whether it lives as a
  dark-factory unit test with a fixture `FACTORY_REPO`, or as an integration check against the
  live factory identity script (`identity.sh`) — is left to the sibling PR's author, since it
  touches dark-factory-internal test conventions this repo doesn't own.

## 6. Assumptions (flagged)

- **Deleting root `metrics.json`/`scorecard.json` is assumed correct** (Requirement 3); this
  was an explicit judgment call during brainstorming, not something the issue or owner
  comment stated directly. If the owner disagrees at spec-review time, the only change needed
  is dropping that bullet from Requirement 8 — everything else in this spec is unaffected.
- **The dark-factory repo is assumed to accept the sibling PR before MarketHawk's half lands**
  — this spec cannot implement or merge anything in `omniscient/dark-factory` (out of this
  refine phase's scope), so PR 1 is a dependency this spec documents but does not control the
  timeline of.
- **`.archon/commands/ceiling-revisit.md` is assumed to need no changes** — verified it already
  calls the dark-factory forks directly; re-confirm this at implementation time in case it has
  changed since this spec was written.
