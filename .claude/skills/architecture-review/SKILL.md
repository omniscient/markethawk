---
name: architecture-review
description: Generate a point-in-time Architecture & Quality report as self-contained HTML in docs/architecture-reviews/, scored on the frozen 16-dimension rubric so every review is directly comparable to v1 (2026-05-26) and v2 (2026-06-03). Also renders vN-vs-vN+1 comparison reports. Use when the user asks for an architecture review, quality report, re-assessment, quality scorecard, DORA metrics, or "how has the codebase improved".
---

# Architecture & Quality Review

Produces the next report in the series at `docs/architecture-reviews/`. The rubric is **frozen** — never add, remove, or re-anchor scored dimensions, or scores stop being comparable across reviews. New analyses go in unscored evidence sections instead.

## Modes

| Mode | Trigger | Output |
|---|---|---|
| **Full review** (default) | "run an architecture review" | `YYYY-MM-DD-architecture-quality-report-vN.html` |
| **Comparison** | "compare vN vs vM" | `YYYY-MM-DD-architecture-quality-comparison-vM-vs-vN.html` |

A full review of vN≥2 should always end by offering the comparison report as a follow-up.

## Workflow (create a TodoWrite item per step)

1. **Baseline** — Read `docs/architecture-reviews/README.md` and the latest prior report. Extract: all 16 scorecard scores, all 11 §3.x scores, the risk register (IDs + status), god-module line counts, and the roadmap. Determine N = prior + 1. Check which prior roadmap/risk items got GitHub tickets (`gh issue list --search`).
2. **Gather evidence** — follow [ANALYSIS.md](ANALYSIS.md). Launch the parallel Explore agents AND run the live verification commands. Cardinal rule: **score from code and command output, never from commit messages or docs**. Record every command's actual exit code/output for the Limitations section.
3. **Score** — apply [RUBRIC.md](RUBRIC.md). For each scored item write: Score, Δ vs prior, Evidence (file:line), Finding, and what caps the score. Compute the three headline numbers with the exact formulas in RUBRIC.md.
4. **Render** — build the report per [SECTIONS.md](SECTIONS.md) starting from [assets/report-shell.html](assets/report-shell.html). Every factual claim carries a `file:line` or command reference. Self-contained HTML; CDN only for Tailwind/Mermaid.
5. **Index** — update `docs/architecture-reviews/README.md`: add the table row, refresh the headline-movement table, note new follow-up ticket label (`architecture-audit-vN`).
6. **Verify** — open the report in the browser (`Start-Process <path>`); confirm Mermaid renders and the scorebar script has the right data (per superpowers:verification-before-completion).
7. **Hand off** — offer: (a) a commit, (b) the comparison report, (c) creating GitHub issues for new Critical/High findings labeled `architecture-audit-vN` (use `--body-file`, never heredoc).

## Hard rules

- **Frozen rubric**: 16 scorecard dimensions + §3.1–3.11, anchors as written in RUBRIC.md. Headline formulas are fixed.
- **Verified, not claimed**: a fix counts only if the code shows it. v2 caught a "completed" ticket whose artifacts never existed — that's the standard.
- **Δ discipline**: every scored item in vN≥2 carries a delta pill vs the immediately prior review.
- **Traceability**: vN≥2 includes the Ticket → Outcome matrix and explicitly lists prior risks that never received a ticket.
- **Limitations honesty**: list what was NOT executed (tests not run, stack not started, audits skipped) and which numbers come from config rather than measurement.
- **Section numbering**: use the canonical order in SECTIONS.md (it supersedes v1/v2's slightly divergent numbering going forward).

## File conventions

- Reports: `docs/architecture-reviews/YYYY-MM-DD-architecture-quality-report-vN.html` (date-prefixed so a directory listing reads chronologically).
- Footer: generation date, model name, and the `main` commit hash verified against (`git rev-parse --short HEAD`).
- Dark theme + CSS classes come from the shell template — keep them so reports look like a series.
