# Implementation Plan: Dark Factory vs. Agyn Paper Comparison (#184)

**Date**: 2026-06-04
**Issue**: [#184](https://github.com/omniscient/markethawk/issues/184) — Compare Dark Factory against Agyn (arXiv:2602.01465v2)
**Goal**: Produce `docs/dark-factory-agyn-comparison.md` — an alignment matrix, gap analysis, and prioritized improvement list comparing Dark Factory with the Agyn multi-agent SE paper.
**Architecture**: Documentation-only task. No backend, frontend, or Docker changes. Source material is in-repo Dark Factory files plus the Agyn PDF fetched at run time. Output is a single markdown document.
**Tech Stack**: Markdown, bash (verification), Read tool (PDF), curl (fetch paper)

---

## File Structure

| File | Action | Purpose |
|------|--------|---------|
| `docs/dark-factory-agyn-comparison.md` | Create | Main deliverable — alignment matrix, gaps, improvements |

---

## Source Files to Read

| File | Relevance |
|------|-----------|
| `dark-factory/Dockerfile` | Container model / isolation boundary |
| `dark-factory/entrypoint.sh` | Pipeline entry, credential injection, user isolation |
| `dark-factory/scheduler.sh` | Task ingestion, scheduling, retry logic |
| `dark-factory/docker-compose.preview.yml` | Preview stack / per-issue infra |
| `.archon/commands/dark-factory-refine.md` | Stage 1: Refine (brainstorm + spec) |
| `.archon/commands/dark-factory-plan.md` | Stage 2: Plan (implementation plan) |
| `.archon/commands/dark-factory-implement.md` | Stage 3: Implement (code agent) |
| `.archon/commands/dark-factory-conformance.md` | Stage 4: Conformance (spec-fidelity gate) |
| `.archon/commands/dark-factory-validate.md` | Stage 5: Validate (live verification) |
| `.archon/workflows/archon-dark-factory.yaml` | Workflow orchestration (node graph) |
| `.archon/memory/dark-factory-ops.md` | Accumulated ops learnings |
| `docs/adr/0008-dark-factory-autonomous-development.md` | Architecture rationale, trust model |
| `docs/adr/0010-dark-factory-gelf-logging.md` | Logging design |

---

## Task 1: Scaffold the comparison document

**Files**: `docs/dark-factory-agyn-comparison.md` (create)

**Purpose**: Create the document skeleton with all required sections — alignment matrix, 7 dimension headers, gaps, and improvements. Subsequent tasks fill in content rather than arguing about structure.

**Step 1 — Write failing check (file must not exist yet):**

```bash
test ! -f docs/dark-factory-agyn-comparison.md \
  && echo "PASS: file absent — ready to scaffold" \
  || { echo "FAIL: file already exists"; exit 1; }
```

Expected output: `PASS: file absent — ready to scaffold`

**Step 2 — Create the scaffold:**

```bash
cat > docs/dark-factory-agyn-comparison.md << 'ENDDOC'
# Dark Factory vs. Agyn: Structured Comparison

**Date**: 2026-06-04
**Issue**: [#184](https://github.com/omniscient/markethawk/issues/184)
**Reference**: Benkovich & Valkov, "Agyn: A Multi-Agent System for Team-Based Autonomous Software Engineering", arXiv:2602.01465v2

---

## Executive Summary

<!-- FILL: 3–5 sentence synthesis after Tasks 2–4 are complete -->

---

## Alignment Matrix

| # | Dimension | Dark Factory | Agyn | Alignment |
|---|-----------|-------------|------|-----------|
| 1 | Agent topology | | | |
| 2 | Coordination / communication | | | |
| 3 | Task ingestion | | | |
| 4 | Isolation & infrastructure | | | |
| 5 | Verification / quality gates | | | |
| 6 | Evaluation / benchmarking | | | |
| 7 | Resumability & statelessness | | | |

Alignment key: **Aligned** / **Partial** / **Differs** / **Gap** (we lack) / **Advantage** (we lead)

---

## Dimension Analysis

### 1. Agent Topology

**Dark Factory:**
<!-- FILL: how many agents, roles, concurrency model, pipeline structure -->

**Agyn:**
<!-- FILL: team/role model, concurrency, specialization -->

**Comparison:**
<!-- FILL: where they converge, where they diverge -->

---

### 2. Coordination / Communication

**Dark Factory:**
<!-- FILL: how state flows between stages (GitHub branch, issue comments, reconstruct-from-branch) -->

**Agyn:**
<!-- FILL: inter-agent communication semantics, message passing, shared state -->

**Comparison:**
<!-- FILL -->

---

### 3. Task Ingestion

**Dark Factory:**
<!-- FILL: GitHub Issues + backlog scheduler (scheduler.sh), label-based dispatch, WIP limit -->

**Agyn:**
<!-- FILL: Agyn's task intake mechanism -->

**Comparison:**
<!-- FILL -->

---

### 4. Isolation & Infrastructure

**Dark Factory:**
<!-- FILL: ephemeral --rm container, docker-socket-proxy, per-issue mh-preview-* stacks, port scheme -->

**Agyn:**
<!-- FILL: Agyn's infra/resource management, isolation model -->

**Comparison:**
<!-- FILL -->

---

### 5. Verification / Quality Gates

**Dark Factory:**
<!-- FILL: conformance stage, validate stage, CI-failure gate, spec-fidelity checks -->

**Agyn:**
<!-- FILL: evaluation/repair loop, review agents, quality mechanisms -->

**Comparison:**
<!-- FILL -->

---

### 6. Evaluation / Benchmarking

**Dark Factory:**
<!-- FILL: current state — no quantitative benchmark -->

**Agyn:**
<!-- FILL: SWEBench results, comparison vs SWE-Agent / OpenHands / miniSWEAgent -->

**Comparison:**
<!-- FILL -->

---

### 7. Resumability & Statelessness

**Dark Factory:**
<!-- FILL: "Continue issue #N" reconstruct-from-branch, stateless container, GitHub as durable state -->

**Agyn:**
<!-- FILL: Agyn's approach to interrupted/resumed tasks -->

**Comparison:**
<!-- FILL -->

---

## Notable Gaps

<!-- FILL: G1, G2, ... — each gap with Severity and Context -->

---

## Prioritized Improvements (Agyn-Inspired)

<!-- FILL: P1, P2, ... — each improvement with Priority, Effort, and Source dimension -->

ENDDOC
```

**Step 3 — Verify all 7 dimension sections exist:**

```bash
MISSING=0
for i in 1 2 3 4 5 6 7; do
  grep -q "^### $i\." docs/dark-factory-agyn-comparison.md \
    && echo "OK: dim $i" \
    || { echo "MISSING: dim $i"; MISSING=$((MISSING+1)); }
done
[ "$MISSING" -eq 0 ] && echo "PASS: all 7 dimensions present" || { echo "FAIL: $MISSING missing"; exit 1; }
```

Expected output: 7 `OK: dim N` lines, then `PASS: all 7 dimensions present`

**Step 4 — Commit:**

```bash
git add docs/dark-factory-agyn-comparison.md
git commit -m "docs(#184): scaffold dark-factory vs agyn comparison document"
```

---

## Task 2: Inventory the Dark Factory implementation

**Files** (read): all 13 source files listed in the Source Files table above
**Files** (write): `docs/dark-factory-agyn-comparison.md`

**Purpose**: Read every Dark Factory implementation file and fill in the "Dark Factory" subsections for all 7 dimensions. Also populate the "Dark Factory" column in the alignment matrix.

**Step 1 — Write failing check (Dark Factory subsections still placeholder):**

```bash
# Pattern "<!-- FILL" (no colon) matches both '<!-- FILL: text -->' (18 total) and bare '<!-- FILL -->' (6, Comparison dims 2-7)
COUNT=$(grep -c "<!-- FILL" docs/dark-factory-agyn-comparison.md)
echo "Placeholder lines: $COUNT"
[ "$COUNT" -ge 20 ] && echo "PASS: document is still scaffold" || echo "FAIL: unexpected content already present"
```

Expected output: `Placeholder lines: 24`, then `PASS`

**Step 2 — Read all Dark Factory source files:**

Use the Read tool (not cat) to read each file so Claude can see the full content. Read these files:
- `dark-factory/Dockerfile`
- `dark-factory/entrypoint.sh`
- `dark-factory/scheduler.sh`
- `dark-factory/docker-compose.preview.yml`
- `.archon/commands/dark-factory-refine.md`
- `.archon/commands/dark-factory-plan.md`
- `.archon/commands/dark-factory-implement.md`
- `.archon/commands/dark-factory-conformance.md`
- `.archon/commands/dark-factory-validate.md`
- `.archon/workflows/archon-dark-factory.yaml`
- `.archon/memory/dark-factory-ops.md`
- `docs/adr/0008-dark-factory-autonomous-development.md`
- `docs/adr/0010-dark-factory-gelf-logging.md`

> **Memory lesson (dark-factory-ops.md)**: Do not trust enumeration — if the file list above has drifted from what actually exists on disk, re-run `ls .archon/commands/dark-factory-*.md` to get the authoritative list before reading.

**Step 3 — Extract findings for each dimension:**

From the files read in Step 2, extract the following facts and write them into `docs/dark-factory-agyn-comparison.md`, replacing the `<!-- FILL: ... -->` comments in the "Dark Factory" subsections:

| Dimension | What to extract |
|-----------|----------------|
| 1. Agent topology | Number of pipeline stages, whether they run sequentially or concurrently, role of each stage (refine/plan/implement/conformance/validate) |
| 2. Coordination / communication | How state passes between stages: GitHub branch as state, issue comments as handoff signals, reconstruct-from-branch semantics |
| 3. Task ingestion | `scheduler.sh` logic: label-based dispatch (`ready-for-agent`), WIP limit, retry counters, circuit-breaker |
| 4. Isolation & infra | `--rm` ephemeral container, `docker-socket-proxy` surface (allowed API verbs), per-issue `mh-preview-{N}` stack, port formula `1{NN}XX` |
| 5. Verification / quality gates | Conformance stage (spec-fidelity), validate stage (live curl checks), CI-failure gate, architect reviewer |
| 6. Evaluation / benchmarking | No quantitative benchmark — note this explicitly as a gap |
| 7. Resumability & statelessness | "Continue issue #N" command, branch + PR as durable state, stateless container per run |

Also populate the alignment matrix "Dark Factory" column with 1–2 sentence summaries derived from the above.

**Step 4 — Verify Dark Factory content is present in each dimension section:**

```bash
# Scaffold has 24 <!-- FILL: --> markers total:
#   1 Executive Summary + 7×3 dimension subsections + 1 Notable Gaps + 1 Prioritized Improvements
# Task 2 fills the 7 "Dark Factory" subsections → 24 - 7 = 17 should remain.
REMAINING=$(grep -c "<!-- FILL" docs/dark-factory-agyn-comparison.md)
echo "Remaining placeholders: $REMAINING"
[ "$REMAINING" -le 17 ] && echo "PASS: dark factory sections filled" || echo "FAIL: $REMAINING placeholders remain (expected <= 17)"
```

Expected output: `PASS: dark factory sections filled`

**Step 5 — Commit:**

```bash
git add docs/dark-factory-agyn-comparison.md
git commit -m "docs(#184): fill dark factory implementation inventory into comparison doc"
```

---

## Task 3: Research the Agyn paper and fill in Agyn sections

**Files** (fetch): `https://arxiv.org/pdf/2602.01465v2` → `/tmp/agyn-paper.pdf`
**Files** (write): `docs/dark-factory-agyn-comparison.md`

**Purpose**: Fetch and read the Agyn paper; fill in the "Agyn" subsections and "Comparison" subsections for all 7 dimensions; populate the "Agyn" and "Alignment" columns in the matrix.

**Step 1 — Write failing check (Agyn subsections still placeholder):**

```bash
COUNT=$(grep -c "<!-- FILL" docs/dark-factory-agyn-comparison.md)
echo "Placeholder lines: $COUNT"
[ "$COUNT" -ge 14 ] && echo "PASS: Agyn sections not yet written" || echo "FAIL: unexpected content"
```

Expected output: `PASS: Agyn sections not yet written`

**Step 2 — Fetch the paper and validate it is a real PDF:**

```bash
HTTP_STATUS=$(curl -L -w "%{http_code}" -o /tmp/agyn-paper.pdf "https://arxiv.org/pdf/2602.01465v2")
echo "HTTP status: $HTTP_STATUS"
[ "$HTTP_STATUS" = "200" ] || { echo "FAIL: non-200 response ($HTTP_STATUS)"; exit 1; }
ls -lh /tmp/agyn-paper.pdf
file /tmp/agyn-paper.pdf | grep -q "PDF" && echo "PASS: valid PDF" || { echo "FAIL: downloaded file is not a PDF (may be an error page)"; exit 1; }
```

Expected output: `HTTP status: 200`, file size > 100K, `PASS: valid PDF`

If the fetch fails (arxiv returns an error page or 403), try the HTML abstract page as a fallback:
```bash
curl -L "https://arxiv.org/abs/2602.01465v2" -o /tmp/agyn-abstract.html
grep -o 'Abstract.*' /tmp/agyn-abstract.html | head -5
```

**Step 3 — Read the paper in sections:**

PDFs over 10 pages require the `pages` parameter with the Read tool. Use this sequence:

```
# Pass 1: Read pages 1–5 (abstract, introduction, high-level architecture)
Read /tmp/agyn-paper.pdf pages=1-5

# Pass 2: Read pages 6–12 (agent topology, coordination, task management)
Read /tmp/agyn-paper.pdf pages=6-12

# Pass 3: Read pages 13–20 (evaluation, benchmarks, infrastructure)
Read /tmp/agyn-paper.pdf pages=13-20
```

If the paper is fewer than 20 pages, adjust the final range down to the actual page count (check the total from Pass 1's header). Focus extraction on:
- Pages 1–5 for the high-level model (dimensions 1, 2)
- Middle sections for task management and coordination (dimensions 3, 7)
- Evaluation/results sections for SWEBench data (dimension 6)
- Infrastructure / execution environment sections (dimensions 4, 5)

**Step 4 — Extract Agyn findings for each dimension:**

From the paper, fill in the "Agyn" and "Comparison" subsections in `docs/dark-factory-agyn-comparison.md`, and update the alignment matrix "Agyn" and "Alignment" columns:

| Dimension | What to extract from Agyn |
|-----------|--------------------------|
| 1. Agent topology | Team structure, role specialization (PM, developer, reviewer agents?), concurrency model |
| 2. Coordination | Inter-agent communication protocol, message format, coordination semantics |
| 3. Task ingestion | How Agyn receives issues/tasks, assignment to teams |
| 4. Isolation & infra | Container/sandbox model, resource constraints, security boundary |
| 5. Verification | Review/repair loop, automated quality checks, how failures surface |
| 6. Evaluation | SWEBench scores, baseline comparisons (SWE-Agent, OpenHands, miniSWEAgent), task set |
| 7. Resumability | How Agyn handles interrupted tasks, checkpointing, retry model |

For the "Alignment" column, use:
- **Aligned** — both systems handle the dimension with similar approach
- **Partial** — meaningful overlap but meaningful differences
- **Differs** — both handle it but with fundamentally different approaches
- **Gap** — Agyn has it; we lack it entirely
- **Advantage** — we handle this dimension better or with more sophistication

**Step 5 — Verify Agyn and Comparison sections are filled, and alignment ratings are present:**

```bash
# After Task 3: Agyn (7) + Comparison (7) subsections filled → 17 - 14 = 3 should remain
# (Executive Summary, Notable Gaps, Prioritized Improvements belong to Task 4)
REMAINING=$(grep -c "<!-- FILL" docs/dark-factory-agyn-comparison.md)
echo "Remaining placeholders: $REMAINING"
[ "$REMAINING" -le 3 ] && echo "PASS: Agyn sections filled" || echo "FAIL: $REMAINING remain (expected <= 3)"

# Verify the alignment matrix contains at least one valid rating keyword in each row
for RATING in "Aligned" "Partial" "Differs" "Gap" "Advantage"; do
  grep -q "$RATING" docs/dark-factory-agyn-comparison.md && echo "RATING PRESENT: $RATING" || true
done
RATING_COUNT=$(grep -cE "\| (Aligned|Partial|Differs|Gap|Advantage)" docs/dark-factory-agyn-comparison.md)
echo "Alignment cells with ratings: $RATING_COUNT"
[ "$RATING_COUNT" -ge 7 ] && echo "PASS: all 7 dimensions have alignment ratings" || echo "FAIL: expected >= 7 rated rows, found $RATING_COUNT"
```

Expected output: `PASS: Agyn sections filled` and `PASS: all 7 dimensions have alignment ratings`

**Step 6 — Commit:**

```bash
git add docs/dark-factory-agyn-comparison.md
git commit -m "docs(#184): fill agyn paper research into comparison doc"
```

---

## Task 4: Write gaps analysis, prioritized improvements, and executive summary

**Files**: `docs/dark-factory-agyn-comparison.md`

**Purpose**: Synthesize the comparison into the three high-value deliverables: Notable Gaps, Prioritized Improvements, and Executive Summary.

**Step 1 — Write failing check (synthesis sections still empty):**

```bash
# Notable Gaps and Prioritized Improvements should have no G1/P1 headers yet
! grep -q "^### G1:" docs/dark-factory-agyn-comparison.md \
  && ! grep -q "^### P1:" docs/dark-factory-agyn-comparison.md \
  && echo "PASS: synthesis sections empty" \
  || echo "FAIL: unexpected content already present"
```

Expected output: `PASS: synthesis sections empty`

**Step 2 — Write the Notable Gaps section:**

Replace the `<!-- FILL: ... -->` comment under `## Notable Gaps` with gap entries in this format:

```markdown
### G1: <Gap name>
**Severity**: Critical | High | Medium | Low
<2–3 sentence description of what we lack, why it matters, and which Agyn dimension it maps to.>

### G2: <Gap name>
...
```

Write at least 2 gaps. Candidate gaps based on the issue's own observations (validate against what was found in Tasks 2 and 3):
- No quantitative benchmark (SWEBench-equivalent) — dimension 6
- Single-agent sequential pipeline vs concurrent team topology — dimension 1
- Any additional gaps revealed by the Agyn research

**Step 3 — Write the Prioritized Improvements section:**

Replace the `<!-- FILL: ... -->` comment under `## Prioritized Improvements` with entries in this format:

```markdown
### P1: <Improvement name>
**Priority**: High | Medium | Low
**Effort**: S | M | L
**Source**: Dimension N
<2–3 sentence description: what to adopt, how it maps to our system, and expected benefit.>

### P2: <Improvement name>
...
```

Write at least 2 improvements. Order by impact-to-effort ratio (highest first). For each gap found in Step 2, there should be at least one corresponding improvement.

**Step 4 — Write the Executive Summary:**

Replace the `<!-- FILL: ... -->` comment under `## Executive Summary` with a 4–6 sentence paragraph that:
- Names both systems and their shared purpose
- States the single biggest architectural difference
- Notes the most actionable gap (the one most worth addressing)
- Briefly characterizes the overall comparison (complementary? divergent? similar?)

**Step 5 — Verify completeness:**

```bash
# All required sections present and non-empty
for section in "Executive Summary" "Alignment Matrix" "Dimension Analysis" "Notable Gaps" "Prioritized Improvements"; do
  grep -q "^## $section" docs/dark-factory-agyn-comparison.md \
    && echo "PRESENT: $section" \
    || echo "MISSING: $section"
done

# At least 2 gaps
GAPS=$(grep -c "^### G[0-9]" docs/dark-factory-agyn-comparison.md)
echo "Gaps: $GAPS"
[ "$GAPS" -ge 2 ] && echo "PASS: gaps count" || echo "FAIL: expected >= 2 gaps"

# At least 2 improvements
IMPROVEMENTS=$(grep -c "^### P[0-9]" docs/dark-factory-agyn-comparison.md)
echo "Improvements: $IMPROVEMENTS"
[ "$IMPROVEMENTS" -ge 2 ] && echo "PASS: improvements count" || echo "FAIL: expected >= 2 improvements"

# No remaining FILL placeholders
REMAINING=$(grep -c "<!-- FILL" docs/dark-factory-agyn-comparison.md)
[ "$REMAINING" -eq 0 ] && echo "PASS: no placeholders" || echo "FAIL: $REMAINING placeholders remain"

# No TBD or TODO
! grep -qi "TBD\|TODO\|implement later" docs/dark-factory-agyn-comparison.md \
  && echo "PASS: no placeholder text" \
  || echo "FAIL: TBD/TODO found"
```

Expected output: all 5 sections PRESENT, `PASS` for gaps count, improvements count, no placeholders, no TODO text.

**Step 6 — Final commit:**

```bash
git add docs/dark-factory-agyn-comparison.md
git commit -m "docs(#184): complete dark-factory vs agyn comparison with gaps and improvements"
```
