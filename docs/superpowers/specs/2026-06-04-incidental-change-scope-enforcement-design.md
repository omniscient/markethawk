# Incidental-Change Scope Enforcement — Dark Factory

**Status:** Approved (design)
**Date:** 2026-06-04
**Author:** Francois Germain (with Claude)
**Related:** #162 (spec-conformance verification, Gate 2), #174 (the incident)

## Problem

The dark factory makes **out-of-scope incidental changes** — fixing unrelated
defects it happens to notice while implementing a ticket — and those changes
reach the environment via the ticket's PR.

Concrete incident (#174, a documentation-only ticket to add Mermaid diagrams):
the factory also "fixed" a SQL seed defect (`ON CONFLICT` + `pocket_pivot`
simplification) addressing **pre-existing, unrelated test failures**. The
change had nothing to do with the diagrams.

Worse, the existing spec-conformance reviewer (#162) **waved it through**. Its
implementation attestation listed:

> Incidental SQL seed fix (`ON CONFLICT` + pocket_pivot simplification) — **Conforms** —
> "Correctly scoped as out-of-spec fix to pre-existing test failures; does not
> change any spec deliverable."

That is exactly the behavior we want reversed. An unrelated fix is a **deviation
from spec**, not a conformant change.

### Root causes

Two gaps, one per stage:

1. **Prevention gap** (`.archon/commands/dark-factory-implement.md`) — never tells
   the agent to stay in scope. Its "Seed Data Awareness" section actively
   *encourages* creating `ON CONFLICT` seed SQL, which is how the agent
   rationalized the #174 seed edit.
2. **Enforcement gap** (`.claude/skills/refinement/conformance-reviewer-prompt.md`) —
   has a "Scope" dimension but the verdict rubric gives it cover to wave additions
   through: *"an extra helper function … is not material unless it violates a spec
   constraint"* and *"when uncertain, default to MINOR DEVIATION or CONFORMS."*

## Goal

No unrelated fix reaches the environment. When the factory makes (or proposes) an
out-of-scope change:

1. Flag it as **non-conformant / a deviation from spec**.
2. Flag the problem on the **originating ticket**.
3. Capture it as a **linked backlog ticket** with a description (so the fix isn't
   lost — it's triaged, not smuggled).
4. **Excise** it from the branch so the PR — and the environment — stay clean.

## Non-goals

- Not changing how the *deliverable* itself is judged for spec fidelity (that is
  #162's CONFORMS/MINOR/MATERIAL flow, which stays as-is).
- Not blocking the factory's legitimate non-spec housekeeping (docs map, memory,
  tests, migrations, codeindex artifacts).
- Not auto-merging the spillover backlog ticket — it lands as triage work.

## Approach (chosen)

**Approach A — extend the existing #162 conformance machinery** rather than build a
parallel gate. Reuses the spec-location, reconcile, block, and attestation
plumbing that already exists; keeps a single source of truth for "does this match
the spec." Defense in depth: prevent at the implement stage *and* detect/remediate
at the conformance gate.

Rejected alternatives:
- **B — a new dedicated `scope-gate` workflow node.** Cleaner separation but
  duplicates spec-location plumbing, adds a node, and splits "did it match the
  spec" across two gates.
- **C — prevention-only** (just harden implement). Cheapest, but no enforcement:
  if the agent strays anyway nothing stops the change reaching the environment —
  exactly the failure we must prevent.

---

## The scope model

The hard part is not detecting *changes* — it is distinguishing scope-creep from
the factory's **legitimate non-spec activity** (it routinely and correctly touches
files no spec names: `ARCHITECTURE.md`, `.archon/memory/*.md`, tests, migrations,
`codeindex.json`).

A change is **in-scope** if it is any of:

- **(a) Spec-named** — a file/area the spec's "Files / areas" lists, or a
  deliverable the spec describes.
- **(b) Supporting housekeeping** — docs-map updates, memory entries, tests, and
  migrations that **directly support an (a) change**. A migration is in-scope only
  if it backs an in-scope model change; a test only if it covers in-scope
  behavior.
- **(c) Strictly required** — a change with no spec home that the in-scope
  deliverable **cannot work without**, explicitly justified by the agent as
  required. This is a **narrow** escape hatch: a change qualifies only if the
  in-scope work literally cannot ship without it. A "while I'm here" fix never
  qualifies.

Everything else is **out-of-scope**. The rule names the #174 failure mode
explicitly:

> Fixing a **pre-existing, unrelated defect** — even a real and worthwhile one —
> is **out-of-scope**, regardless of whether it is "small," "documented," or
> "makes tests pass." The correct response to an unrelated defect is a backlog
> ticket, never an inline fix.

Under this model the #174 seed fix is out-of-scope: it had no spec home, the docs
deliverable did not depend on it, and it addressed a pre-existing failure.

---

## Section 2 — Prevention (`.archon/commands/dark-factory-implement.md`)

Two edits so the agent rarely strays.

### 2.1 New "Scope Discipline" guard (in Phase 2 PLAN)

Add a subsection stating the (a/b/c) scope rule and the hard line on pre-existing
defects. Core instruction:

> If you encounter an unrelated defect, **do not fix it.** Append it to
> `$ARTIFACTS_DIR/out-of-scope.md` as a candidate backlog item — title,
> description, why it is out of scope, and the minimal fix you would have made —
> then work around it. Only if it **truly blocks** your in-scope work, stop and
> let the conformance gate handle it.

The agent **records** candidates; it never **creates** tickets. Ticket creation
lives in one place (the gate) for idempotency, and the gate independently catches
creep the agent did not self-report.

`out-of-scope.md` format (append one block per candidate):

```
## <short title>
- file(s): <paths>
- why out of scope: <reason — typically "pre-existing/unrelated to issue #N">
- minimal fix: <what you would have changed>
- blocks in-scope work: yes | no
```

### 2.2 Rewrite "Seed Data Awareness"

Keep the additive `99_feature.sql` (`ON CONFLICT DO NOTHING`) pattern **only** for
data the in-scope feature needs to render. Add an explicit prohibition:

> Do **not** edit existing seed modules (`dark-factory/seed/0*.sql`) to fix
> pre-existing or unrelated failures. That is a backlog item (record it in
> `out-of-scope.md`), not a commit on this branch.

---

## Section 3 — Detection

### 3.1 Deterministic pre-triage (`.archon/commands/dark-factory-conformance.md`, Phase 3)

Before spawning the reviewer:

1. `git diff main...HEAD --name-only` → changed-file set.
2. Strip **pure-housekeeping** noise from consideration (never spec deliverables,
   never creep):
   - `.archon/memory/`
   - `codeindex.json`, `symbolindex.json`
   - `docs/codeindex-hotspots.md`
3. Feed the remaining changed-file set **plus** the contents of
   `$ARTIFACTS_DIR/out-of-scope.md` (if present) to the reviewer as additional
   context.

This removes false positives from legitimate housekeeping and gives the reviewer
good signal (including the agent's own self-reported candidates).

### 3.2 Sharpen `.claude/skills/refinement/conformance-reviewer-prompt.md`

- **Remove the cover language**: delete *"an extra helper function, or a
  split/merged task is not material unless it violates a spec constraint"* and
  *"When uncertain, default to MINOR DEVIATION or CONFORMS with a note."* from the
  scope handling.
- **Reframe the Scope dimension** around the (a/b/c) rule and embed the
  pre-existing-defect hard line verbatim.
- **Add a distinct output section**, separate from the deliverable verdict (a run
  can faithfully implement the spec *and* carry creep):

```
## Out-of-Scope Changes

| File | What it is | Proposed backlog title | Proposed description |
|---|---|---|---|
| dark-factory/seed/01_scanner_configs.sql | ON CONFLICT + pocket_pivot fix to pre-existing test failure | Seed: idempotent scanner_configs + pocket_pivot params | <1-3 sentences> |

(If none, write: None found.)
```

The deliverable verdict (CONFORMS / MINOR / MATERIAL) is unchanged and continues
to drive the existing reconcile/block flow.

---

## Section 4 — Remediation (`.archon/commands/dark-factory-conformance.md`)

New phase after the review parses, before PASS (Phase 4) / BLOCK (Phase 5).
Runs only when the reviewer's `## Out-of-Scope Changes` section is non-empty **and**
`scope_enforcement` is enabled.

For the set of out-of-scope changes:

1. **Excise**
   - Whole out-of-scope file → `git checkout main -- <file>` (restore to main).
   - Change mixed inside an otherwise in-scope file → attempt targeted reversal of
     just those hunks.
   - **Re-run the in-scope tests** (`cd backend && python -m pytest`, and/or
     `cd frontend && npx tsc --noEmit` if frontend changed) to confirm the
     in-scope work still passes after excision.

2. **If all excised cleanly and tests still green** (the common case):
   - Commit: `git commit -m "chore: excise out-of-scope changes (see #<backlog>)"`.
   - **Create one linked backlog ticket** (idempotent — first search for an
     existing open issue containing the marker `out-of-scope spillover from
     #<issue>`; reuse it if found). Body includes: the proposed description, the
     **excised diff** in a fenced code block, and a back-link to the origin
     issue/PR. Labels: `needs-discussion` (scheduler skips it until a human
     triages) + the configured `backlog_label` (`scope-spillover`).
   - **Comment on the originating issue**:
     `⚠️ Excised N out-of-scope change(s) → captured in #<backlog>.`
   - Continue to the normal deliverable verdict (PASS / reconcile / block).

3. **If any excision is unsafe** — the revert will not apply, or removing the
   change breaks the in-scope build (a genuine category-(c) dependency): do **not**
   push. Fall back to the existing **Block** path (Phase 5): post a
   "Spec Conformance — Blocked (out-of-scope, unsafe excision)" comment, **still
   create the backlog ticket** capturing the change, add `needs-discussion`, move
   the issue to Blocked, and exit non-zero. Nothing reaches the environment.

### #174 outcome under this design

The four Mermaid-diagram commits ship as a clean PR; the SQL seed fix is reverted
out of the branch and lands as a new `needs-discussion` + `scope-spillover` backlog
ticket; issue #174 carries a visible "excised 1 out-of-scope change → #NNN"
comment.

---

## Section 5 — Config, no-spec handling, report

### 5.1 `config.yaml` — extend the `conformance:` block

```yaml
conformance:
  enabled: true
  max_reconcile_cycles: 3
  block_on_material: true
  scope_enforcement: true      # kill switch for the whole out-of-scope feature
  excise_out_of_scope: true    # false → flag + backlog but do not auto-revert (advisory)
  backlog_label: scope-spillover
```

`scope_enforcement: false` disables detection entirely. `excise_out_of_scope:
false` keeps detection + flagging + backlog but skips the revert (advisory mode) —
a dial-back path that needs no code edits if it ever misfires.

The `scope-spillover` GitHub label does not exist yet and must be created as part
of implementation (`gh label create scope-spillover`); the ticket-creation step
should also create-if-missing to stay self-healing.

### 5.2 No-spec runs (direct `Fix issue #N`, no spec file)

Consistent with #162's fail-open philosophy. Detection + flag + backlog ticket
still happen, and **safe** excision still happens (excision is not "blocking"). But
an **unsafe** excision degrades to an **advisory note rather than a Block** — a
no-spec run never hard-blocks. Scope is judged against the issue body.

### 5.3 Report surfacing (`conformance.md` artifact + `report` node)

`conformance.md` gains a summary line so the existing `report` node can surface it:

```
OUT_OF_SCOPE: <count>
SPILLOVER_TICKETS: #<n>[,#<n>...]
```

The `report` node adds a "Scope" line to the run report, e.g.
*"⚠️ 1 out-of-scope change excised → #190."*

### 5.4 Fail-open

If the reviewer errors, ticket creation fails, or `gh` is unavailable: log a
warning and proceed (matching #162). Scope enforcement never wedges the pipeline on
its own tooling failure.

---

## End-to-end flow

```
implement (records out-of-scope.md, stays in scope)
   → validate
   → conformance:
        deterministic pre-triage (strip housekeeping, gather out-of-scope.md)
        sharpened reviewer → ## Out-of-Scope Changes
        if out-of-scope & scope_enforcement:
            excise → re-test
              clean  → commit, backlog ticket, flag origin, continue
              unsafe → backlog ticket, flag origin, BLOCK (advisory if no-spec)
        deliverable verdict (unchanged) → PASS / reconcile / block
   → push-and-pr (clean branch)
   → status-in-review
   → report (surfaces excised count + spillover ticket #s)
```

## Files touched

| File | Change |
|---|---|
| `.archon/commands/dark-factory-implement.md` | Add Scope Discipline guard; rewrite Seed Data Awareness |
| `.claude/skills/refinement/conformance-reviewer-prompt.md` | Remove cover language; reframe Scope; add `## Out-of-Scope Changes` output |
| `.archon/commands/dark-factory-conformance.md` | Deterministic pre-triage; remediation phase (excise → backlog → flag → fallback Block) |
| `.claude/skills/refinement/config.yaml` | Add `scope_enforcement`, `excise_out_of_scope`, `backlog_label` |
| `.archon/workflows/archon-dark-factory.yaml` (`report` node) | Surface `OUT_OF_SCOPE` / `SPILLOVER_TICKETS` |

## Acceptance criteria

- [ ] An unrelated/pre-existing-defect fix is judged **out-of-scope**, not
      "Conforms" (the #174 case specifically).
- [ ] `dark-factory-implement.md` instructs the agent to record (not fix)
      unrelated defects in `out-of-scope.md`; Seed Data Awareness forbids editing
      existing seed modules for pre-existing failures.
- [ ] Conformance reviewer emits a distinct `## Out-of-Scope Changes` section;
      cover language removed.
- [ ] Conformance command excises out-of-scope changes, re-tests, and on success
      commits the excision, creates one idempotent linked backlog ticket
      (`needs-discussion` + `scope-spillover`), and comments on the origin issue.
- [ ] Unsafe excision falls back to Block (advisory for no-spec), still filing the
      backlog ticket.
- [ ] `config.yaml` gains `scope_enforcement`, `excise_out_of_scope`,
      `backlog_label`; both switches honored.
- [ ] Report surfaces excised count + spillover ticket numbers.
- [ ] Reviewer/tooling errors fail open with a logged warning.
- [ ] Legitimate housekeeping (memory, codeindex artifacts, docs-map updates,
      in-scope tests/migrations) is **not** flagged as out-of-scope.
```
