# Architecture & Quality Reviews

Point-in-time architecture and code-quality assessments of MarketHawk. Each review uses the
same scoring rubric so scores are directly comparable across reviews. Files are date-prefixed,
so a plain directory listing reads chronologically (oldest first).

Open the `.html` files in a browser — they are self-contained (Tailwind/Mermaid via CDN).

## Reviews

| Order | File | Date | What it is |
|------|------|------|------------|
| 1 | [`2026-05-26-architecture-quality-report-v1.html`](2026-05-26-architecture-quality-report-v1.html) | 2026-05-26 | **v1** — the first full assessment. Overall **62/100**, architecture **3.2/5**, scorecard **2.8/5**. Its findings spawned remediation tickets #84–#107. |
| 2 | [`2026-06-03-architecture-quality-report-v2.html`](2026-06-03-architecture-quality-report-v2.html) | 2026-06-03 | **v2** — re-assessment after those tickets shipped, using the identical rubric. Overall **83/100**, architecture **3.9/5**, scorecard **3.75/5**. Includes a refreshed risk register and a ticket→outcome traceability matrix. |
| 3 | [`2026-06-03-architecture-quality-comparison-v1-vs-v2.html`](2026-06-03-architecture-quality-comparison-v1-vs-v2.html) | 2026-06-03 | **Comparison** — visual v1→v2 side-by-side: a diverging delta chart across all 16 dimensions, "dramatically improved" vs "cold spots & regressions", and the new defects the remediation introduced. |
| 4 | [`2026-06-09-architecture-quality-report-v3.html`](2026-06-09-architecture-quality-report-v3.html) | 2026-06-09 | **v3** — re-assessment after round-2 tickets #190–#205. Overall **90/100**, architecture **4.3/5**, scorecard **4.06/5**. First report with the Code Health Deep-Dive, DORA-proxy, and Score Trend sections. Caught one ticket (#195 backups) closed with no implementation. |
| — | [`2026-06-12-security-review.html`](2026-06-12-security-review.html) | 2026-06-12 | **Security Review** (not a quality vN) — comprehensive read-only application-security assessment. Mean posture **2.6/5** on a security-specific 12-category scorecard (independent of the 16-dimension quality rubric). 0 Critical / 4 High / 8 Medium / 2 Low. Confirmed the system can place **live** IBKR bracket orders. Follow-ups labeled `security-audit-2026-06-12`, grouped under an epic. |

> **Note:** the security review reuses the visual shell for consistency but is a **distinct artifact** — it is scored on its own security rubric and does **not** renumber the comparable v1→v2→v3 quality series.

## Headline movement

| Metric | v1 | v2 | v3 |
|---|---|---|---|
| Overall Quality (0–100) | 62 | 83 | **90** |
| Architecture Quality (0–5) | 3.2 | 3.9 | **4.3** |
| Weighted Scorecard (0–5) | 2.8 | 3.75 | **4.06** |

**v1 → v2:** 22 of 24 remediation tickets (#84–#107) closed; auth + observability foundations built.
One ticket (#101 async SQLAlchemy) deliberately **declined** (ADR-0004).
**v2 → v3:** 15 of 17 round-2 tickets (`architecture-audit-v2`) verified done — including the
scanner/futures god-module decomposition, circuit breakers, WebSocket auth, CSRF, and worker-metrics
fix. One closure (#195 automated backups) was **broken** — closed with no artifacts in the repo;
v3 follow-ups carry the `architecture-audit-v3` label.

## Reproducing these reports

The whole format is codified as the project skill **`.claude/skills/architecture-review/`** —
frozen rubric ([RUBRIC.md](../../.claude/skills/architecture-review/RUBRIC.md)), canonical section
spec, evidence-gathering playbook, and the HTML shell template. To produce v(N+1), ask Claude Code
to "run an architecture review"; it reads this README for the baseline, scores against the same
rubric, writes the next date-prefixed report here, and updates this index. From v3 on, reports also
include three unscored evidence sections: a Code Health Deep-Dive (complexity / duplication /
coupling), Delivery Performance (DORA proxies), and a Score Trend across all reviews.

## Methodology

- **Same rubric both times.** 16 scorecard dimensions + an 11-part architecture assessment
  (§3.1–3.11), each scored 0–5. The 0–100 score maps the weighted average onto v1's calibration
  for apples-to-apples comparison.
- **Verified against code, not commit messages.** v2 scores were checked by reading the auth,
  config, metrics, and tracing modules directly and by running `tsc --noEmit` and `eslint`.
- **Reviews are point-in-time** and reflect `main` at the date shown. They are health indicators,
  not certifications — see each report's Limitations section.

## Follow-up tickets

The v2 report surfaced new defects introduced by the remediation work itself (e.g. an empty
default JWT signing key, a WebSocket auth bypass, a red frontend `tsc` gate, a worker-metrics
scrape gap) plus v1 items that never received a ticket (automated DB backups, the Docker socket
mount). These are tracked as the **`architecture-audit-v2`** "round 2" tickets on the
[issue tracker](https://github.com/omniscient/markethawk/issues?q=label%3Aarchitecture-audit-v2).
