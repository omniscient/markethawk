# Dark Factory Memory Contract — structured schema and lifecycle rules

**Status:** design
**Date:** 2026-06-27
**Issue:** #645
**Epic:** #643 (Dark Factory platform)
**Labels:** documentation, foundation, size: S

## Problem

The `.archon/memory/*.md` files are the sole durable knowledge store for the Dark
Factory's agent pipeline. They are already consumed and written by four pipeline
phases (refine, implement, conformance, code-review), but the rules governing what
may be written, by whom, and how entries age or get invalidated exist only as
scattered inline comments inside each phase's prompt. There is no single reference
that defines the stable contract between:

1. The flat-file format in `.archon/memory/*.md` (the current store)
2. The Dark Factory gates that read and write it (`gate_lib.sh`, `route_memory_file`)
3. A future structured backend that would replace or sit beneath the flat files

Without a stable contract, evolving the storage layer risks silent incompatibilities
between what the prompts enforce and what the gates actually implement.

## Requirements

Derived from issue #645 acceptance criteria and Q&A:

1. A document at `docs/agents/dark-factory-memory-contract.md` covering all six
   acceptance criteria (schema fields, tag mapping, write bar, lifecycle rules,
   scoping matrix, backwards compatibility).
2. A one-line pointer added to CLAUDE.md's "Agent Skills" section.
3. The document serves both human developers (understanding the system) and agent
   operators (the source of truth that prompts and gates must conform to).
4. No changes to `.archon/memory/*.md` files or any pipeline scripts — this is a
   documentation-only deliverable.
5. Backwards compatibility clause must be explicit: the existing flat-file format
   remains the authoritative read/write interface until a structured backend is
   formally adopted.

## Approach

Write a single reference document at `docs/agents/dark-factory-memory-contract.md`.
Organise it into five sections, one per acceptance criterion, plus a backward-compat
section:

### 1 — Schema field table

Define all fields the future structured backend must support. Map each to its
current flat-file representation:

| Field | Type | Flat-file representation |
|---|---|---|
| `id` | string (UUID/slug) | (none — positional; use file + line number as surrogate) |
| `type` | enum: `pattern`, `avoidance`, `fix` | `[PATTERN]`, `[AVOID]`, `[FIX]` tag prefix |
| `status` | enum: `active`, `provisional`, `invalid`, `superseded` | `[PROVISIONAL]`, `[INVALID: reason]` prefix; `active` is implicit |
| `confidence` | float 0–1 | provisional = low (< 0.5); active/pattern = high (≥ 0.8) |
| `source` | enum: `bootstrap`, `refine`, `implement`, `conformance`, `code-review` | `source:` inline comment token |
| `created_at` | ISO-8601 date | `date:YYYY-MM-DD` inline comment token |
| `updated_at` | ISO-8601 date | (none — immutable in flat-file; use `created_at` as surrogate) |
| `expires_at` | ISO-8601 date | `expires:YYYY-MM-DD` inline comment token |
| `supersedes` | string (id of replaced entry) | (implicit — dedup/cap-drop in favour of newer entry; no explicit flat-file tag) |
| `project` | string | (implicit — file lives in the repo; `omniscient/markethawk` by convention) |
| `agent_id` | string | (implicit — phase + issue_number identifies the run; no flat-file tag) |
| `phase` | enum: `refine`, `implement`, `conformance`, `code-review` | overlaps with `source:` |
| `issue_number` | int | `issue:#N` inline comment token |
| `pr_number` | int | (none — not tracked in flat-file) |
| `files` | string[] | `path:file/prefix` inline comment token |
| `concepts` | string[] | (none — free-text tagging not yet in flat-file) |
| `content` | string | The text body of the entry after the `[TAG]` prefix |
| `rationale` | string | **Why:** line in the entry body (for feedback-type entries) |

### 2 — Tag and lifecycle state mapping

Four terminal/transitional states:

| Flat-file tag | Structured status | Meaning |
|---|---|---|
| `[PATTERN]` | `type=pattern, status=active` | Observed, validated approach — use it |
| `[AVOID]` | `type=avoidance, status=active` | Confirmed anti-pattern — never do this |
| `[FIX]` | `type=fix, status=active` | Specific corrective action for a known class of bug |
| `[PROVISIONAL]` (in provisional section) | `status=provisional` | Single-run observation; unvalidated |
| `[INVALID: reason]` | `status=invalid` | Claim was factually wrong; tombstoned |
| (implied by dedup/cap-drop) | `status=superseded` | Claim was once correct; replaced by a broader/newer entry |

**Lifecycle transitions** (four distinct paths — must not be conflated):

1. **Expiry**: `active` or `provisional` → auto-dropped when `expires_at < today`.
   Implemented by the awk block run before any file append.

2. **Invalidation (R5)**: `active` → `status=invalid`. Entry text is rewritten from
   `[PATTERN]` to `[INVALID: reason]`. Used when the claim is factually wrong.
   The tombstone stays to prevent re-addition of the same wrong claim during its TTL.
   Does **not** imply there is a replacement entry.

3. **Supersession**: `active` → `status=superseded`. The newer (B) entry has broader
   or more accurate scope; A was correct in its time. In the flat-file, supersession
   is expressed implicitly: B is appended, A is removed by the R4 cap-drop or R3
   dedup with "scope covered by newer entry." In the structured backend, B carries
   `supersedes: A.id` and A transitions to `superseded`. **Supersession is not
   invalidation** — A was never wrong; it is merely outdated.

4. **Promotion**: `provisional` → `active`. A `[PROVISIONAL]` entry is promoted to
   `[PATTERN]` when confirmed by a *different* issue number in a later pipeline run.
   Implemented by the implement agent's cross-run confirmation check.

### 3 — Write bar

An entry may only become durable memory if it passes the write bar: **"Would a
future agent make a materially different architectural decision because of this
entry, compared to reading `CLAUDE.md` and `ARCHITECTURE.md` alone?"** If no → skip.

Per-phase thresholds:

- **Refine**: Add entries only when a trade-off between two approaches was
  explicitly weighed in Phase 4 Q&A. Most runs add zero entries.
- **Implement**: Add entries only when a pattern is runtime-proven in the delivered
  code. Single-run observations that can't be verified via code go to
  `[PROVISIONAL]`; they are promoted only when a different issue confirms them.
- **Conformance**: Add `[AVOID]` entries only when a MATERIAL violation was found
  and successfully remediated in the same run (CONFORMANCE_CYCLE > 0).
- **Code-review**: Add `[AVOID]` entries only when STATUS=BLOCKED (confirmed
  blocking findings that were acted on).

Prohibited at all times: entries that duplicate content already in `CLAUDE.md` or
`ARCHITECTURE.md`, ephemeral task details, current-conversation context, debug
solutions already in the code, git history summaries.

### 4 — Scoping rules: writer-role × memory-file matrix

| Memory file | Authorised writers | Trigger condition |
|---|---|---|
| `architecture.md` | **refine only**; bootstrap (seed) | Trade-off explicitly weighed in Phase 4 Q&A |
| `backend-patterns.md` | implement, conformance, code-review; refine (PATTERN only) | Runtime-proven pattern / material AVOID finding |
| `frontend-patterns.md` | implement, conformance, code-review; refine (PATTERN only) | Runtime-proven pattern / material AVOID finding |
| `dark-factory-ops.md` | implement, conformance, code-review; refine (PATTERN only) | Runtime-proven pattern / material AVOID finding |
| `codebase-patterns.md` | implement, conformance, code-review — **refine is forbidden** | Runtime-proven cross-cutting lessons only |

**Read-only roles**: plan, validate, revise-advisory. They load memory at Phase 1
via `load_memory` but never write (`git add .archon/memory/` is absent from their
scripts).

**`bootstrap` provenance**: A one-time seed origin for entries written before the
pipeline ran. Not a recurring role; no command file exists for it.

**Scoping primitives** in the inline comment:
- `source:<role>` — identifies the writer role (provenance)
- `path:<prefix>` — area scoping; entries with `path:` are filtered at load time
  against `AFFECTED` (files changed on the branch). Entries without `path:` are
  always included.
- `issue:#N` — ties the entry to the originating issue for audit and expiry TTL tracking
- `expires:YYYY-MM-DD` — absolute expiry; typical TTL is 6 months from `date:`

**Quota limits**:
- Authoritative entries per file (`[PATTERN]` + `[AVOID]` + `[FIX]`): cap 30 (R4).
- Provisional entries per file: cap 10.
- When a cap is reached, the oldest/lowest-signal entries are dropped before
  committing. This is the flat-file implementation of supersession.

### 5 — Backwards compatibility

The `.archon/memory/*.md` flat-file format is the authoritative read/write interface
until a structured backend is formally adopted. The contract document must state this
explicitly so future implementers do not silently break the pipeline by migrating
storage before establishing equivalence.

Specific backward-compat guarantees:
- The `[PATTERN]`, `[AVOID]`, `[FIX]`, `[PROVISIONAL]`, `[INVALID]` tag prefixes
  are stable — no renames.
- The inline comment tokens (`source:`, `date:`, `expires:`, `issue:`, `path:`)
  are stable — the flat-file is the source of truth for any migration mapping.
- Any structured backend must be able to ingest all entries in the current
  `.archon/memory/*.md` files without data loss.
- The `---` delimiter separating authoritative entries from the provisional section
  is a format invariant; tooling must not delete it.

## Deliverable structure

The implement agent writes exactly two files:

1. **`docs/agents/dark-factory-memory-contract.md`** — the full contract document,
   organised by the five sections above. Should include all field tables, tag
   mappings, lifecycle diagrams (mermaid state chart for the four lifecycle
   transitions is appropriate), scoping matrix, and backwards-compat clause.

2. **`CLAUDE.md`** — add one line to the "Agent Skills" bullet list:
   `- **Memory contract** — stable schema, lifecycle rules, and scoping matrix for `.archon/memory/*.md`. See \`docs/agents/dark-factory-memory-contract.md\`.`

No other files should be created or modified.

## Alternatives considered

**A. ADR + separate detail doc**
Add a short ADR recording the decision plus the full doc. Rejected: the existing
`docs/adr/` convention records decisions tersely; the full schema/lifecycle content
is better served by a standalone reference doc that can be updated without
re-litigating the decision. An ADR could be added later if the parent epic mandates
it.

**B. Embed in CLAUDE.md**
Put the schema and rules directly in CLAUDE.md. Rejected: CLAUDE.md is already the
primary developer reference and adding machine-generated schema tables would make it
harder to read. The `docs/agents/` directory exists precisely for this kind of
detailed agent-operational contract.

**C. Scatter across existing memory file headers**
Put the lifecycle rules in each file's existing "This file is maintained
automatically..." header. Rejected: the headers are intentionally minimal; the full
contract is multi-file and needs a single place to look it up.

## Open questions (non-blocking)

1. Should `confidence` be a derived field (computed from `status`) or an explicit
   float that writers set? The structured backend design can decide this; the flat
   file has no explicit confidence score beyond the PROVISIONAL/ACTIVE distinction.

2. Should the `concepts` field be introduced in the flat-file format now (e.g. as a
   `concepts:foo,bar` inline token), or left as a future-only field for the
   structured backend?

3. Does the parent epic #643 require an ADR to record the decision to adopt the
   structured schema? If yes, it is a one-paragraph addition to `docs/adr/`.

## Assumptions

- The implement agent does NOT change any `.archon/memory/*.md` file or pipeline
  script — this is a doc-only issue.
- The `docs/agents/` directory already exists (confirmed: `docs/agents/issue-tracker.md`,
  `docs/agents/triage-labels.md`, `docs/agents/domain.md`).
- No new tech dependencies are needed; the deliverable is pure Markdown.
