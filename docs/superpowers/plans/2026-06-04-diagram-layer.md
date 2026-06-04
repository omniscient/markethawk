# Plan: Add Missing Diagram Layer

**Tracking issue:** [#174](https://github.com/omniscient/markethawk/issues/174)

**Goal:** Replace the orphaned `docs/Diagram.md` and add four high-value Mermaid diagrams co-located in the docs that own their facts — service topology and scan-execution flow in `ARCHITECTURE.md`, domain-model ERD in `CONTEXT.md`, and dark-factory pipeline in `docs/superpowers/specs/2026-05-02-dark-factory-design.md`.

**Architecture:** Documentation-only change. No SQLAlchemy models, FastAPI routers, React components, or Celery tasks are modified. The four diagrams live as fenced Mermaid code blocks inside existing Markdown files. The orphaned `docs/Diagram.md` (live-scanner flow duplicate) is deleted.

**Tech Stack:** Markdown + Mermaid (renders natively in GitHub, VS Code, and any Mermaid-aware viewer).

## File Structure

| File | Change |
|------|--------|
| `docs/Diagram.md` | Deleted (`git rm`) |
| `ARCHITECTURE.md` | Two Mermaid blocks added: service topology (replaces ASCII art) + scan-execution sequence |
| `CONTEXT.md` | One Mermaid ERD block inserted after the `## Language` heading |
| `docs/superpowers/specs/2026-05-02-dark-factory-design.md` | One Mermaid flowchart inserted after the numbered lifecycle list |

---

## Task 1 — Delete orphaned `docs/Diagram.md`

**Files:** `docs/Diagram.md`

The file contains a single live-scanner sequence diagram that duplicates the "Live Scanner — Data flow" section already in `ARCHITECTURE.md`. It is generically named and orphaned — no other doc links to it.

**Steps:**

1. Confirm the file exists and contains only the live-scanner duplicate:
   ```bash
   ls docs/Diagram.md
   wc -l docs/Diagram.md
   # expected: file present, ~42 lines (single mermaid sequenceDiagram block)
   ```

2. Stage the deletion:
   ```bash
   git rm docs/Diagram.md
   ```

3. Verify it is staged:
   ```bash
   git status
   # expected: deleted:    docs/Diagram.md
   ```

4. Commit:
   ```bash
   git commit -m "docs(#174): remove orphaned docs/Diagram.md (duplicates ARCHITECTURE.md live-scanner flow)"
   ```

**Expected outcome:** `docs/Diagram.md` no longer exists. The live-scanner diagram in `ARCHITECTURE.md` remains the canonical source.

---

## Task 2 — Service topology: replace ASCII art with Mermaid `graph TD`

**Files:** `ARCHITECTURE.md`

The service topology section (lines 3–40) uses a large fenced ASCII art block. Replace it with an equivalent Mermaid `graph TD` block so the topology renders as a diagram on GitHub and VS Code.

**Steps:**

1. Locate the ASCII block in `ARCHITECTURE.md`:
   ```bash
   grep -n "stockscanner-network" ARCHITECTURE.md
   # expected: line ~9 (inside the ASCII block)
   grep -n "┌─────" ARCHITECTURE.md
   # expected: line ~8 (ASCII border)
   ```

2. Replace the triple-backtick plain text block (the entire block starting with the opening `` ``` `` through the closing `` ``` `` on its own line, ~lines 7–40) with the following Mermaid block:

   ````markdown
   ```mermaid
   graph TD
       Browser["Browser :3333"]

       subgraph net["stockscanner-network"]
           frontend["frontend :3333"]
           backend["backend :8000"]
           livescanner["live-scanner"]
           celery["celery-worker"]
           beat["celery-beat"]
           flower["flower :5555"]
           pgadmin["pgadmin :5050"]
           seq["seq :5380/5341"]
           tweetmonitor["tweet-monitor :8001"]
           postgres["postgres :5432"]
           redis["redis :6379"]
           ibgw["ib-gateway :4004"]
           prometheus["prometheus :9090"]
           grafana["grafana :3001"]
           jaeger["jaeger :16686/:4317"]
       end

       polygon(["api.polygon.io"])

       Browser -->|"HTTP :3333"| frontend
       frontend -->|HTTP| backend
       frontend -.->|"WS /api/v1/live/ws/*"| backend

       backend --> postgres
       backend --> redis
       backend --> ibgw
       backend -->|HTTPS| polygon
       backend -->|HTTP| seq

       livescanner --> postgres
       livescanner --> redis
       livescanner --> ibgw

       celery --> postgres
       celery --> redis
       celery --> ibgw
       celery -->|HTTPS| polygon

       beat -->|broker| redis
       beat -->|"HTTP POST / 45 s"| tweetmonitor
       flower --> redis
       pgadmin --> postgres
       tweetmonitor --> postgres
       tweetmonitor --> redis

       prometheus -->|"scrape :8000/metrics"| backend
       grafana --> prometheus
       jaeger -->|OTLP| backend
       jaeger -->|OTLP| celery
       jaeger -->|OTLP| beat
   ```
   ````

3. Verify the ASCII art is gone and the Mermaid block is in place:
   ```bash
   grep "┌─────" ARCHITECTURE.md
   # expected: no output

   grep -c "mermaid" ARCHITECTURE.md
   # expected: at least 1 (the new topology block)

   grep -A 2 '```mermaid' ARCHITECTURE.md | head -6
   # expected: "graph TD" on the next line
   ```

4. Commit:
   ```bash
   git add ARCHITECTURE.md
   git commit -m "docs(#174): replace ASCII service-topology with Mermaid graph TD"
   ```

---

## Task 3 — Scan-execution: add Mermaid sequence diagram to `ARCHITECTURE.md`

**Files:** `ARCHITECTURE.md`

The **Scan Execution Flow** section describes nine steps as prose. Add a Mermaid `sequenceDiagram` block immediately after the numbered list so the participant interactions and ordering are visual.

**Steps:**

1. Locate the end of the numbered list in the **Scan Execution Flow** section:
   ```bash
   grep -n "Delivery" ARCHITECTURE.md
   # expected: line ~54 (step 9 — last bullet)
   grep -n "## Backend Module Map" ARCHITECTURE.md
   # expected: line ~56 — insert diagram between line 54 and this heading
   ```

2. Insert the following Mermaid block between the numbered list and the `## Backend Module Map` heading (add one blank line before and after):

   ````markdown
   ```mermaid
   sequenceDiagram
       participant Beat as Celery Beat / User POST
       participant Task as scanning.run_universe_scan
       participant Svc as ScannerService
       participant Poly as Polygon.io
       participant DB as PostgreSQL
       participant BE as Backend API (FastAPI)
       participant FE as Frontend (React Query / WS)

       Beat->>Task: fire run_scanner (scheduled or manual)
       Task->>Svc: calculate_day_metrics(tickers, session)
       Svc->>Svc: classify session (pre-market / regular / post)
       Svc->>DB: SELECT StockUniverseTicker for universe
       DB-->>Svc: [ticker list]

       loop per batch (asyncio.Semaphore 10)
           Svc->>Poly: GET /v2/aggs/{ticker} (OHLCV bars)
           Poly-->>Svc: bars[]
       end

       Svc->>DB: SELECT TickerReference for full batch (1 round-trip)
       DB-->>Svc: [enrichment metadata]
       Svc->>DB: SELECT NewsArticle WHERE timestamp > now-72h
       DB-->>Svc: [articles]
       Svc->>Svc: CatalystParser.analyze_batch()

       loop per ticker
           Svc->>Svc: evaluate 5 criteria (vol ratio, gap %, liquidity, …)
           alt passes all criteria
               Svc->>DB: INSERT ScannerEvent (signal_quality_score computed)
           end
       end

       Svc->>DB: INSERT ScannerRun (timing, hit count, config snapshot)
       FE->>BE: GET /api/v1/scanner/results (React Query poll)
       BE->>DB: SELECT ScannerEvent (eager-load reviews, sort by score)
       DB-->>BE: [ScannerEvent list]
       BE-->>FE: JSON response
       BE->>FE: broadcast via websocket_manager (live push)
   ```
   ````

3. Confirm insertion:
   ```bash
   grep -n "sequenceDiagram" ARCHITECTURE.md
   # expected: one match (the new block)

   grep -A 3 "sequenceDiagram" ARCHITECTURE.md | head -6
   # expected: participant lines follow
   ```

4. Commit:
   ```bash
   git add ARCHITECTURE.md
   git commit -m "docs(#174): add scan-execution sequence diagram to ARCHITECTURE.md"
   ```

---

## Task 4 — Domain model: add Mermaid ERD to `CONTEXT.md`

**Files:** `CONTEXT.md`

`CONTEXT.md` defines 19 domain concepts in prose but never draws their relationships. Add a Mermaid `erDiagram` block immediately after the `## Language` heading to give the full picture before the glossary entries.

**Steps:**

1. Locate the `## Language` heading:
   ```bash
   grep -n "^## Language" CONTEXT.md
   # expected: line ~5
   grep -n "^\*\*Signal\*\*:" CONTEXT.md
   # expected: line ~7 — insert diagram between ## Language and this line
   ```

2. Insert the following Mermaid ERD block between the `## Language` heading and the `**Signal**:` entry (add one blank line before and after):

   ````markdown
   ```mermaid
   erDiagram
       UNIVERSE ||--|{ TICKER : contains
       UNIVERSE ||--o{ SCAN : "is scanned by"
       SCANNER ||--o{ SCAN : executes
       SCAN ||--o{ SIGNAL : produces
       SIGNAL ||--o| REVIEW : "reviewed as"
       SIGNAL ||--o{ OUTCOME : "measured at"
       SIGNAL ||--o| ENRICHMENT : "enriched with"
       SIGNAL }o--o{ SIGNAL_CLUSTER : "grouped into"
       SCANNER ||--o| SCORECARD : "scored by"
       SCORECARD }|--|| EDGE : reveals
       SIGNAL }o--o{ ALERT : triggers
       ALERT_RULE ||--o{ ALERT : generates
       ALERT_RULE }o--o| TRADING_STRATEGY : "linked to"
       WATCHLIST }o--o{ TICKER : monitors
   ```
   ````

   The ERD maps the full Signal → Review / Outcome → Scorecard → Edge chain plus Watchlist, Alert, and Trading Strategy concepts from the glossary.

3. Confirm insertion:
   ```bash
   grep -n "erDiagram" CONTEXT.md
   # expected: one match

   grep -A 3 "erDiagram" CONTEXT.md | head -6
   # expected: UNIVERSE lines follow
   ```

4. Commit:
   ```bash
   git add CONTEXT.md
   git commit -m "docs(#174): add domain-model ERD to CONTEXT.md"
   ```

---

## Task 5 — Dark-factory pipeline: add Mermaid flowchart to the spec

**Files:** `docs/superpowers/specs/2026-05-02-dark-factory-design.md`

The **What the Factory Does Inside** section lists the 12-step lifecycle in a numbered list. Add a Mermaid `flowchart TD` block immediately after the list to show the intent branches, the TDD loop, and the preview phase.

**Steps:**

1. Locate the numbered lifecycle list and the text immediately after it:
   ```bash
   grep -n "What the Factory Does Inside" docs/superpowers/specs/2026-05-02-dark-factory-design.md
   # expected: one match

   grep -n "^12\." docs/superpowers/specs/2026-05-02-dark-factory-design.md
   # expected: line number of the last lifecycle step — insert diagram after this line
   ```

2. Insert the following Mermaid block immediately after step 12 of the numbered list (add one blank line before and after):

   ````markdown
   ```mermaid
   flowchart TD
       A(["docker compose run --rm dark-factory 'verb issue #N'"])
       A --> B{Intent?}

       B -->|"Fix issue #N"| C["Clone repo · create feat/issue-N-slug branch"]
       B -->|"Continue issue #N"| D["Pull branch · read PR comments via gh"]
       B -->|"Close issue #N"| Z["Merge PR · delete branch · docker compose down -v · comment · exit"]

       C --> E["Fetch issue body via gh"]
       D --> E

       E --> F["Write implementation plan"]
       F --> G["Write failing tests"]
       G --> H["Implement feature"]
       H --> I{"pytest + tsc pass?"}
       I -->|No| G
       I -->|Yes| J["Spin up preview stack\ndocker compose -p mh-preview-N up -d"]

       J --> K["Poll backend :1N80/api/health"]
       K --> L["curl-validate new endpoints\nagainst preview"]
       L --> M["git push · gh pr create or update\n(preview URL in PR body)"]
       M --> O(["Exit · preview keeps running for human review"])
   ```
   ````

3. Confirm insertion:
   ```bash
   grep -n "flowchart TD" docs/superpowers/specs/2026-05-02-dark-factory-design.md
   # expected: one match

   grep -A 4 "flowchart TD" docs/superpowers/specs/2026-05-02-dark-factory-design.md | head -6
   # expected: A([ line follows
   ```

4. Commit:
   ```bash
   git add docs/superpowers/specs/2026-05-02-dark-factory-design.md
   git commit -m "docs(#174): add dark-factory pipeline flowchart to spec"
   ```

---

## Summary

| Task | File | Change | Commits |
|------|------|--------|---------|
| 1 | `docs/Diagram.md` | Delete | 1 |
| 2 | `ARCHITECTURE.md` | Replace ASCII topology with Mermaid graph TD | 1 |
| 3 | `ARCHITECTURE.md` | Add scan-execution sequence diagram | 1 |
| 4 | `CONTEXT.md` | Add domain-model ERD | 1 |
| 5 | `docs/superpowers/specs/2026-05-02-dark-factory-design.md` | Add pipeline flowchart | 1 |

**Total: 5 tasks, 17 steps, 5 commits.**

No tests, migrations, or dependency changes. All validation is structural (grep/ls confirm blocks are present/absent). Mermaid renders on GitHub PR view — reviewer can confirm diagram quality there.
