# Report Sections — Canonical Spec

Canonical section order for v3 onward. It preserves every v1/v2 section (so readers can map
old reports onto new ones) and adds three evidence sections (§11–§13). Sections marked
*(re-assessment only)* are omitted in a hypothetical fresh-start review.

Every scored card uses the house pattern: **Score + badge + Δ pill + meter bar**, then
**Change** (re-assessments first), **Evidence** (`file:line`), **Finding**, **Risk**,
**Recommendation**. Prose is dense and specific; no filler.

## §1 Executive Summary

- 4 score-cards: Overall /100, Architecture /5, Scorecard /5, one project-scale stat (LOC or Docker services). Re-assessments: each carries a delta pill + "was X" subtext.
- **Overall Health** card: 2 paragraphs. Para 1 = what the system is and what materially changed. Para 2 = the character of the current risk (v2's "missing foundations → unfinished edges" framing is the model — name the risk *theme*, not just a list).
- **Top 5 Strengths** (re-assessments: "new since vN-1"), **Top 5 Risks** (with severity tags), **Top 5 Recommended Actions** (each with Effort and what it closes).

## §2 Repository & Technology Overview

- Re-assessments: "What Changed in the Stack" table (Area | vN-1 | vN) replaces the full stack table; fresh reviews list the full stack with versions.
- Codebase Metrics table (the supplementary tracked metrics from RUBRIC.md — always all of them, with prior-review column).
- Architectural Pattern paragraph + a Mermaid system-topology flowchart.

## §3 Architecture Assessment

Eleven cards, §3.1–§3.11 per RUBRIC.md. Each self-contained; "caps the score" sentence mandatory when score < 5.

## §4 Maintainability Assessment

- Code Organization card (scored).
- **Complexity Hotspots table** — god modules with vN-1 → vN line counts and Δ column (green ↓ / red ↑). This table is the longitudinal spine of the maintainability story; never drop files from it once tracked, mark decomposed files as such.
- Naming / Duplication / Framework Usage cards (scored).
- Exemplary Files and Problematic Files tables (with one-line "why" each).

## §5 Testability & Code Coverage

Backend card, Frontend card (both scored), Test Quality Signals table (Signal | vN-1 | vN badges). Call out coverage-denominator games explicitly (exclusions, hand-pinned includes, threshold vs. measured).

## §6 Reliability & Operational Readiness

The 13-capability table: Logging, Health Checks, Retry Behavior, Timeout Handling, Graceful Degradation, Startup/Shutdown, Database Migrations, Connection Pooling, Metrics, Distributed Tracing, Circuit Breakers, Backup/Recovery, Feature Flags. Each scored /5 with vN-1 column and evidence note.

## §7 Security & Compliance Review

The 10-area table: Authentication, Authorization, CORS, Input Validation, Secrets Management, Rate Limiting, Dependency Vulnerabilities, Transport Security, Docker Security, Sensitive Data in Logs. Each scored /5 with vN-1 column and `file:line` finding. Regressions get an explicit red "Regression" tag.

## §8 Performance & Scalability

"Resolved since vN-1" card + "Still open" card (re-assessments), or Strengths/Bottlenecks cards (fresh). Scalability Model card (horizontal/vertical/verdict).

## §9 API, Data & Integration Quality

API Consistency, Data Model Clarity, Migration Approach (scored, table with vN-1). External-integrations paragraph naming the most fragile dependency.

## §10 Developer Experience

The 9-aspect table: Local Setup, README/Documentation, Build Simplicity, Linting/Formatting, Type Checking, CI Feedback, Debugging Support, Onboarding Friction (+ Documentation if split). Scored with vN-1 column.

## §11 Code Health Deep-Dive *(NEW, unscored)*

Replaces ad-hoc complexity work with a standing section. Sourced from the ANALYSIS.md agents.

- **Cyclomatic complexity top-10**: Function | File | Lines | Branches | Primary issue. Compare against prior review's table — note functions that left/entered the list.
- **Duplication top-8**: Pattern | Occurrences | Layer | Proposed consolidation. Track occurrence counts over time (e.g. "UTC normalization: 41 files → 12 files").
- **Coupling map**: one Mermaid graph of service-to-service imports; color circular/cross-layer edges red.
- **Module depth candidates**: up to 5 cards naming shallow modules worth deepening (interface nearly as complex as implementation), each with files, problem, proposed deepening, and a Strong / Worth exploring / Speculative badge. Reuse the vocabulary of the `improve-codebase-architecture` skill (module, interface, seam, depth, leverage, locality).
- If repowise is available (`scripts/repowise.sh`), include its top-10 worst-health files and churn-vs-complexity hotspots; if codeindex MCP is available, include blast-radius notes for files being recommended for refactor.

## §12 Delivery Performance (DORA) *(NEW, unscored)*

Four DORA metrics computed over the window since the prior review (and same-length window before it, for trend). All are **proxies** in a single-repo, no-prod-telemetry context — label them as such and show the derivation. Commands in ANALYSIS.md §4.

| Metric | Proxy |
|---|---|
| Deployment Frequency | Merges to `main` per week (+ publish-workflow runs if present) |
| Lead Time for Changes | Median hours, PR `createdAt` → `mergedAt` |
| Change Failure Rate | % of merged PRs followed ≤7 days by a `fix:`/`revert:` commit touching the same files (fallback: fix-typed commits ÷ total) |
| MTTR | Median `bug`-labeled issue open → close time |

Plus delivery extras: commits/week, human vs. dark-factory commit share, median PR size (additions+deletions), PR count, % PRs merged by the factory pipeline. Render as KPI cards + one trend sentence each. Map onto DORA performance bands (Elite/High/Medium/Low) with the caveat that bands assume production deployment, which this proxy does not measure.

## §13 Score Trend *(NEW, from v3 on)*

- Headline chart: Overall /100 across all reviews (simple HTML/CSS bar or line per shell template).
- 16-dimension table: one row per dimension, one column per review, sparkline-style coloring.
- One paragraph: which dimensions are structurally stuck (flat ≥3 reviews) — these are the candidates for the next roadmap's focus.

## §14 Ticket → Outcome Traceability *(re-assessment only)*

Table: # | Ticket | Maps to prior risk/roadmap item | **Verified outcome** (badge per RUBRIC.md: Done / Partial / Declined / Broken) with the caveat inline. Verification means reading the code, running the gate, or confirming the artifact exists. End with the yellow callout listing prior risks that **never received a ticket**.

## §15 Risk Register

Re-assessments split into "Newly introduced" and "Carried over (not yet addressed)" tables.
Columns: ID | Description | Category | Severity | Likelihood | Evidence (`file:line`) | Impact | Mitigation | Priority. IDs restart per review (R01…) — cross-reference prior IDs as "R08 (v1)".

## §16 Quality Scorecard

16 dimensions per RUBRIC.md. Render via the shell template's scorebar script (data array `[name, vPrev, vNow]`). Below: the weighted-average card with prior value and delta.

## §17 Prioritized Improvement Roadmap

Horizon tables: Immediate (0–1/2 wk) · Short-term · Medium-term · Strategic. Columns: Action | Closes (risk IDs) | Effort (| Benefit | Owner | Dependencies for fresh reviews). Re-assessment Immediate sections should carry a theme line (e.g. "finish-quality on the new infrastructure").

## §18 Final Recommendations

Four cards: Most important **decision** · most important **practice** · most important **testing gap** *or* second decision · most important **operational risk**. Then a 2–3 paragraph Conclusion that names the trajectory, not just the state.

## §19 Evidence Index

Table of every file/directory reviewed with purpose. Cheap to produce, makes the review auditable.

## §20 Limitations

Bullet list, brutally honest: what was executed vs. inferred, which numbers come from config not measurement, severity judgment calls, anything out of scope. Carry the standing line about scores being a comparative rubric, not a certification.

---

# Comparison report (separate file)

`YYYY-MM-DD-architecture-quality-comparison-vM-vs-vN.html` — glassmorphism style per the v1-vs-v2 file, data-driven via JS arrays:

1. Hero: question-as-title ("Did the quality actually improve?"), chips (window, commits, tickets), one-sentence answer.
2. 4 headline KPI cards with strikethrough-old → big-new.
3. Diverging movement chart across all 16 dimensions (sorted by delta; dual track bars vM grey / vN gradient).
4. Two columns: 🚀 Dramatically improved vs 🧊 Cold spots & regressions (cards with ticket chips).
5. ⚠️ New cracks: defects introduced *by* the remediation (severity-chipped cards, `file:line` in mono).
6. Ticket scoreboard grid (Done/Partial/Declined/Broken).
7. "Shape of the change" — two Mermaid diagrams contrasting the old vs new risk profile.
8. Verdict card: did the org respond well, what's the honest caveat, what closes the gap.
