# MarketHawk README, Docs Site, and Demo Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a clear public-facing README/docs experience and a reproducible `make demo` sandbox that starts MarketHawk with deterministic sample data and no live credentials.

**Architecture:** Keep documentation static and repository-native: the README is the fast entry point, and `docs/site/` is a zero-build static docs site. Demo mode is isolated through `docker-compose.demo.yml`, demo-specific named volumes, and a seed script that runs inside the backend container after migrations.

**Tech Stack:** Markdown, static HTML/CSS, Docker Compose, GNU Make, FastAPI backend image, Vite frontend image, PostgreSQL, Redis, Python seed script using SQLAlchemy models.

---

## File Structure

- Modify `README.md`: replace the current short project overview with positioning, five-minute demo, architecture, data flow, install, roadmap, safety, and comparison content.
- Create `docs/site/index.html`: static docs landing page with the same story as the README in a more visual, browsable format.
- Create `docs/site/styles.css`: responsive, dependency-free styles for the docs site.
- Create `docs/site/assets/README.md`: explains screenshot/GIF placeholders and where future captures belong.
- Create `docs/site/assets/dashboard-placeholder.svg`: committed visual placeholder for screenshots/GIFs when real captures are not available.
- Create `Makefile`: adds `demo`, `demo-down`, `demo-logs`, and `demo-seed` targets.
- Create `docker-compose.demo.yml`: isolated demo stack with Postgres, Redis, backend, and frontend only.
- Create `demo/README.md`: short operational notes for the demo sandbox.
- Create `demo/seed/seed_demo.py`: deterministic seed script run inside the backend container.
- Create `tests/scripts/test_demo_seed.py`: pure tests for seed data invariants and demo credentials.

## Task 1: README Positioning and Walkthrough

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Replace the README with a world-class entry point**

Write `README.md` with these top-level sections in this order:

```markdown
# MarketHawk

MarketHawk is an AI-First human-in-the-loop market scanning cockpit for turning market data, news, scanner hits, alerts, reviews, execution notes, journal entries, and outcomes into a repeatable trader workflow.

> MarketHawk helps you understand scanner behavior. It does not provide financial advice, guarantee trading results, or replace broker-side risk controls.

## What MarketHawk Is

- An AI-First full-stack scanner workflow for active traders who want a repeatable review loop.
- A local-first research and monitoring cockpit that connects data, scanners, alerts, reviews, journal notes, and outcomes.
- A way to make scanner ideas observable: which signals fired, what reviewers decided, what happened after the signal, and what should be improved.
- A practical bridge between discretionary review and systematic evidence.

## What MarketHawk Is Not

- It is not a broker or broker replacement.
- It is not a promise of profitable trading.
- It is not a pure vectorized research engine like vectorbt.
- It is not a full institutional backtesting engine like Lean or NautilusTrader.
- It is not a substitute for risk controls, compliance, or human judgment.

## Five-Minute Demo

Run a complete demo without IBKR, Polygon, X, or live credentials:

```bash
make demo
```

Then open:

| Surface | URL |
|---|---|
| App | http://localhost:3333 |
| API | http://localhost:8000 |
| API docs | http://localhost:8000/docs |

Demo login:

| Username | Password |
|---|---|
| `demo` | `markethawk-demo` |

The demo resets only demo-owned Docker volumes. It does not touch normal development or live MarketHawk volumes.

## Demo Walkthrough

1. Open the app and log in with the demo account.
2. Review seeded scanner events for NVDA, AMD, MSFT, TSLA, and AMZN.
3. Open the active watchlist to see symbols promoted from scanner context.
4. Inspect review cards with confirmed, rejected, and enhanced verdicts.
5. Open outcome/scorecard views to see fake follow-through, MFE/MAE, and end-of-day results.
6. Open the journal to see example execution notes and trade outcomes.

## Architecture

```mermaid
flowchart LR
    UI["React + Vite frontend"] --> API["FastAPI backend"]
    API --> DB["PostgreSQL"]
    API --> Redis["Redis"]
    API --> Workers["Celery workers"]
    Workers --> DB
    Providers["Polygon / IBKR / demo seed data"] --> API
```

## Data Flow

```mermaid
flowchart LR
    Data["OHLCV + news + references"] --> Scanner["Scanner"]
    Scanner --> Alert["Alert"]
    Alert --> Review["Human review"]
    Review --> Execution["Execution note / paper order"]
    Execution --> Journal["Journal"]
    Journal --> Outcome["Outcome + scorecard"]
    Outcome --> Scanner
```

## Local Install With Sample Data

Use demo mode for the fastest sample-data setup:

```bash
make demo
```

Use the full development stack when connecting real providers:

```bash
cp .env.example .env
docker compose up -d
```

## Screenshots and GIFs

The static docs site includes placeholder assets in `docs/site/assets/`. Replace them with captured dashboard, scanner, review, and scorecard screenshots as the public demo stabilizes.

## Comparison

| Tool | Primary Positioning | Best At | MarketHawk Difference |
|---|---|---|---|
| MarketHawk | Human-in-the-loop scanner cockpit | Reviewing live-ish signals, watchlists, alerts, outcomes, and journal context together | Optimized for the scanner-review-outcome loop rather than pure backtesting |
| Lean | Institutional-grade algorithmic trading platform | Multi-asset backtesting, live deployment, brokerage integrations | MarketHawk is lighter and focused on scanner operations and human review |
| NautilusTrader | Production-grade Rust-native trading engine | Low-latency, event-driven strategy execution | MarketHawk prioritizes explainable scanner workflow over engine-level execution |
| vectorbt | Test thousands of ideas quickly | Vectorized research and parameter sweeps | MarketHawk captures review decisions, alerts, and outcomes around operational scanner use |
| backtrader | Ease-of-use Python backtesting | Scriptable local strategy backtests | MarketHawk is a full-stack scanner cockpit with UI, alerting, review, and journal surfaces |
| pysystemtrade | Systematic futures trading research | Portfolio/system research and futures workflows | MarketHawk focuses on equity scanner signals and operator review workflows |

## Roadmap

- Reproducible demo screenshots and GIFs.
- Stronger scanner scorecards and interval outcome analysis.
- Safer broker integration boundaries for paper execution.
- More import/export paths for journals and signal reviews.
- Public docs expansion for scanner design and operational playbooks.

## Safety and Risk

MarketHawk is research and workflow software. Trading involves substantial risk of loss. Sample data, fake outcomes, scanner scores, and demo records are illustrative only. Do not use demo settings for live trading.

## Documentation

| Document | Contents |
|---|---|
| `docs/site/index.html` | Static public docs site |
| `DEVELOPMENT.md` | Local setup and troubleshooting |
| `ARCHITECTURE.md` | System architecture details |
| `ENV_VARIABLES.md` | Environment variable reference |
| `deployment-guide.md` | Deployment and hardening notes |
```

- [ ] **Step 2: Verify the README has required sections**

Run:

```powershell
$required = @(
  'What MarketHawk Is',
  'What MarketHawk Is Not',
  'Five-Minute Demo',
  'Architecture',
  'Data Flow',
  'Local Install With Sample Data',
  'Screenshots and GIFs',
  'Comparison',
  'Roadmap',
  'Safety and Risk'
)
$content = Get-Content README.md -Raw
$missing = $required | Where-Object { $content -notmatch [regex]::Escape($_) }
if ($missing) { $missing; exit 1 }
```

Expected: exit code `0` with no output.

- [ ] **Step 3: Commit README change**

Run:

```bash
git add README.md
git commit -m "docs: clarify MarketHawk positioning"
```

## Task 2: Static Docs Site

**Files:**
- Create: `docs/site/index.html`
- Create: `docs/site/styles.css`
- Create: `docs/site/assets/README.md`
- Create: `docs/site/assets/dashboard-placeholder.svg`

- [ ] **Step 1: Create docs site HTML**

Create `docs/site/index.html` as a standalone HTML document. Include:

- `<title>MarketHawk Docs</title>`
- A first-viewport hero with the literal product name `MarketHawk`.
- Sections with IDs: `what`, `demo`, `architecture`, `flow`, `screenshots`, `comparison`, `roadmap`, `safety`.
- Two inline Mermaid-style diagrams represented as semantic HTML/CSS blocks, not a Mermaid runtime dependency.
- A comparison table with the same six tools as the README.

Use this exact skeleton and fill the paragraphs from the README content:

```html
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>MarketHawk Docs</title>
  <link rel="stylesheet" href="styles.css">
</head>
<body>
  <header class="site-header">
    <a class="brand" href="#top">MarketHawk</a>
    <nav aria-label="Primary">
      <a href="#demo">Demo</a>
      <a href="#architecture">Architecture</a>
      <a href="#comparison">Compare</a>
      <a href="#safety">Safety</a>
    </nav>
  </header>
  <main id="top">
    <section class="hero">
<p class="eyebrow">AI-First human-in-the-loop market scanning</p>
      <h1>MarketHawk</h1>
      <p class="lede">A scanner cockpit for connecting market data, news, alerts, reviews, execution notes, journal entries, and outcomes.</p>
      <div class="hero-actions">
        <a class="button primary" href="#demo">Run the 5-minute demo</a>
        <a class="button" href="../../README.md">Read the README</a>
      </div>
    </section>
    <section id="what" class="section two-column"></section>
    <section id="demo" class="section"></section>
    <section id="architecture" class="section"></section>
    <section id="flow" class="section"></section>
    <section id="screenshots" class="section"></section>
    <section id="comparison" class="section"></section>
    <section id="roadmap" class="section"></section>
    <section id="safety" class="section safety"></section>
  </main>
  <footer class="footer">MarketHawk is research and workflow software, not financial advice.</footer>
</body>
</html>
```

- [ ] **Step 2: Create docs site CSS**

Create `docs/site/styles.css` with:

- A restrained, professional palette that is not dominated by a single hue.
- Responsive layout using `max-width`, `grid`, and `@media`.
- Accessible focus styles.
- Tables that scroll horizontally on narrow screens.
- Diagram node styles for data flow and architecture cards.

Use only CSS; do not add JavaScript or external fonts.

- [ ] **Step 3: Create placeholder asset documentation**

Create `docs/site/assets/README.md`:

```markdown
# Docs Site Assets

This directory holds public documentation screenshots and GIFs.

Current committed assets are placeholders so the docs site can render without external dependencies. Replace them with real captures when the demo UI is stable:

- `dashboard-placeholder.svg` -> dashboard overview
- future `scanner-results.png` -> seeded scanner results
- future `review-cards.gif` -> signal review workflow
- future `scorecard.png` -> outcome scorecard
```

- [ ] **Step 4: Create placeholder SVG**

Create `docs/site/assets/dashboard-placeholder.svg` as a simple SVG dashboard mock with labeled regions: `Scanner Results`, `Watchlist`, `Review Queue`, and `Outcomes`.

- [ ] **Step 5: Verify static docs required anchors**

Run:

```powershell
$html = Get-Content docs/site/index.html -Raw
$ids = @('what','demo','architecture','flow','screenshots','comparison','roadmap','safety')
$missing = $ids | Where-Object { $html -notmatch "id=`"$_`"" }
if ($missing) { $missing; exit 1 }
```

Expected: exit code `0` with no output.

- [ ] **Step 6: Commit docs site**

Run:

```bash
git add docs/site
git commit -m "docs: add static MarketHawk docs site"
```

## Task 3: Demo Seed Data Helpers

**Files:**
- Create: `demo/seed/seed_demo.py`
- Create: `tests/scripts/test_demo_seed.py`

- [ ] **Step 1: Write failing seed invariant tests**

Create `tests/scripts/test_demo_seed.py`:

```python
from pathlib import Path

import importlib.util


ROOT = Path(__file__).resolve().parents[2]
SEED_PATH = ROOT / "demo" / "seed" / "seed_demo.py"


def load_seed_module():
    spec = importlib.util.spec_from_file_location("seed_demo", SEED_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_demo_credentials_are_documented_and_nonempty():
    seed = load_seed_module()

    assert seed.DEMO_USERNAME == "demo"
    assert seed.DEMO_PASSWORD == "markethawk-demo"
    assert len(seed.DEMO_PASSWORD) >= 12


def test_demo_dataset_covers_workflow_surfaces():
    seed = load_seed_module()
    dataset = seed.build_dataset()

    assert {ticker["ticker"] for ticker in dataset["tickers"]} >= {
        "NVDA",
        "AMD",
        "MSFT",
        "TSLA",
        "AMZN",
    }
    assert len(dataset["scanner_events"]) >= 5
    assert len(dataset["watchlist"]) >= 3
    assert len(dataset["reviews"]) >= 3
    assert len(dataset["outcomes"]) >= 3
    assert len(dataset["news"]) >= 3
    assert len(dataset["journal_entries"]) >= 1
    assert len(dataset["trades"]) >= 1


def test_every_review_and_outcome_references_seeded_event():
    seed = load_seed_module()
    dataset = seed.build_dataset()
    event_keys = {event["key"] for event in dataset["scanner_events"]}

    assert all(review["event_key"] in event_keys for review in dataset["reviews"])
    assert all(outcome["event_key"] in event_keys for outcome in dataset["outcomes"])
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
python -m pytest tests/scripts/test_demo_seed.py -q
```

Expected: FAIL because `demo/seed/seed_demo.py` does not exist.

- [ ] **Step 3: Implement deterministic seed script**

Create `demo/seed/seed_demo.py` with:

- Constants `DEMO_USERNAME = "demo"` and `DEMO_PASSWORD = "markethawk-demo"`.
- Function `build_dataset() -> dict` returning dictionaries for tickers, universes, configs, scanner events, watchlist, reviews, outcomes, news, journal entries, and trades.
- Function `seed_database()` that imports SQLAlchemy models from `app.models`, hashes the demo password with `app.core.auth.hash_password`, deletes demo-owned rows marked with `markethawk_demo` in metadata, notes, URLs, usernames, or article providers, upserts rows, commits, and prints a short summary.
- A `if __name__ == "__main__": seed_database()` entry point.

Use `metadata.source = "markethawk_demo"` or notes text containing `markethawk_demo` for rows that support metadata/notes, so reseeding can identify demo-owned records.

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
python -m pytest tests/scripts/test_demo_seed.py -q
```

Expected: all tests pass.

- [ ] **Step 5: Commit seed helpers**

Run:

```bash
git add demo/seed/seed_demo.py tests/scripts/test_demo_seed.py
git commit -m "feat: add deterministic demo seed data"
```

## Task 4: Isolated Demo Compose and Make Targets

**Files:**
- Create: `docker-compose.demo.yml`
- Create: `Makefile`
- Create: `demo/README.md`

- [ ] **Step 1: Create demo compose file**

Create `docker-compose.demo.yml` with services:

- `postgres`: `postgres:15-alpine`, named volume `markethawk_demo_postgres_data`.
- `redis`: `redis:7-alpine`, named volume `markethawk_demo_redis_data`.
- `backend`: build `./backend`, mount `./backend:/app:ro` and `./demo:/demo:ro`, command `uvicorn app.main:app --host 0.0.0.0 --port 8000`, environment values:
  - `DATABASE_URL=postgresql://postgres:demo_password@postgres:5432/stockscanner`
  - `POSTGRES_DB=stockscanner`
  - `POSTGRES_USER=postgres`
  - `POSTGRES_PASSWORD=demo_password`
  - `POLYGON_API_KEY=demo_no_live_key`
  - `REDIS_URL=redis://redis:6379/0`
  - `ENVIRONMENT=development`
  - `COOKIE_SECURE=false`
  - `RATE_LIMITING_ENABLED=false`
  - `SEQ_URL=disabled`
  - `JWT_SECRET_KEY=markethawk_demo_jwt_secret_key_32_chars_minimum`
  - `CORS_ORIGINS=["http://localhost:3333"]`
- `frontend`: build `./frontend`, mount `./frontend:/app` and `/app/node_modules`, command `npm run dev -- --host 0.0.0.0 --port 3333`, environment values:
  - `REACT_APP_API_URL=http://localhost:8000`
  - `VITE_API_TARGET=http://backend:8000`

Use host ports `127.0.0.1:8000:8000` and `127.0.0.1:3333:3333`.

- [ ] **Step 2: Create Makefile targets**

Create `Makefile`:

```makefile
.PHONY: demo demo-down demo-logs demo-seed

DEMO_PROJECT := markethawk_demo
DEMO_COMPOSE := docker compose -p $(DEMO_PROJECT) -f docker-compose.demo.yml

demo:
	$(DEMO_COMPOSE) down -v --remove-orphans
	$(DEMO_COMPOSE) up -d --build postgres redis
	$(DEMO_COMPOSE) run --rm backend python -m alembic upgrade head
	$(DEMO_COMPOSE) run --rm backend python /demo/seed/seed_demo.py
	$(DEMO_COMPOSE) up -d --build backend frontend
	@echo "MarketHawk demo is starting."
	@echo "Frontend: http://localhost:3333"
	@echo "API:      http://localhost:8000"
	@echo "Docs:     http://localhost:8000/docs"
	@echo "Login:    demo / markethawk-demo"

demo-seed:
	$(DEMO_COMPOSE) run --rm backend python -m alembic upgrade head
	$(DEMO_COMPOSE) run --rm backend python /demo/seed/seed_demo.py

demo-logs:
	$(DEMO_COMPOSE) logs -f backend frontend

demo-down:
	$(DEMO_COMPOSE) down -v --remove-orphans
```

- [ ] **Step 3: Create demo README**

Create `demo/README.md`:

```markdown
# MarketHawk Demo Sandbox

`make demo` starts a credential-free MarketHawk stack with deterministic sample data.

The demo uses Docker Compose project `markethawk_demo` and demo-only volumes:

- `markethawk_demo_postgres_data`
- `markethawk_demo_redis_data`

Every `make demo` run resets those demo volumes. It does not touch normal development or live MarketHawk volumes.

Demo login:

- Username: `demo`
- Password: `markethawk-demo`
```

- [ ] **Step 4: Verify compose syntax**

Run:

```bash
docker compose -p markethawk_demo -f docker-compose.demo.yml config
```

Expected: exit code `0`, with only `postgres`, `redis`, `backend`, and `frontend` services.

- [ ] **Step 5: Commit demo orchestration**

Run:

```bash
git add Makefile docker-compose.demo.yml demo/README.md
git commit -m "feat: add isolated demo compose stack"
```

## Task 5: End-to-End Demo Smoke

**Files:**
- Verify: `demo/seed/seed_demo.py`
- Verify: `docker-compose.demo.yml`
- Verify: `Makefile`
- Verify: `README.md`
- Verify: `docs/site/index.html`

- [ ] **Step 1: Run the demo**

Run:

```bash
make demo
```

Expected:

- Demo volumes are recreated.
- Migrations complete.
- Seed script prints seeded counts.
- Backend and frontend containers start.
- Output prints frontend, API, docs, and login information.

- [ ] **Step 2: Verify seeded API data**

Run:

```bash
curl http://localhost:8000/api/auth/status
```

Expected JSON includes:

```json
{"bootstrapped":true}
```

Then run a login request using cookies:

```bash
curl -i -c demo-cookies.txt -H "Content-Type: application/json" -d "{\"username\":\"demo\",\"password\":\"markethawk-demo\"}" http://localhost:8000/api/auth/login
```

Expected: HTTP `200` and `Set-Cookie` headers.

Then run:

```bash
curl -b demo-cookies.txt http://localhost:8000/api/v1/scanner/results
curl -b demo-cookies.txt http://localhost:8000/api/v1/watchlist/
curl -b demo-cookies.txt "http://localhost:8000/api/v1/outcomes/scorecard/pre_market_volume"
curl -b demo-cookies.txt http://localhost:8000/api/v1/journal/trades
```

Expected:

- Scanner results include NVDA and AMD.
- Watchlist includes NVDA, AMD, and MSFT.
- Scorecard returns non-empty summary data or a schema-valid empty response if existing scorecard logic requires more history.
- Journal trades includes at least one demo trade.

- [ ] **Step 3: Verify tests and build checks**

Run:

```bash
python -m pytest tests/scripts/test_demo_seed.py -q
```

Expected: pass.

Run:

```bash
cd frontend && npm run build
```

Expected: TypeScript and Vite build complete successfully.

- [ ] **Step 4: Remove local cookie artifact**

Run:

```powershell
Remove-Item -LiteralPath demo-cookies.txt -ErrorAction SilentlyContinue
```

- [ ] **Step 5: Commit smoke fixes**

If smoke verification required changes, run:

```bash
git add README.md docs/site docker-compose.demo.yml Makefile demo tests/scripts/test_demo_seed.py
git commit -m "fix: stabilize demo smoke path"
```

If no changes were required, do not create an empty commit.

## Self-Review Checklist

- The README requirements map to Task 1.
- The static docs site requirements map to Task 2.
- Demo seed data, login, scanner events, watchlist, reviews, fake outcomes, news, and journal/trade records map to Task 3.
- Isolated demo compose and resettable `make demo` behavior map to Task 4.
- Verification maps to Task 5.
- No task mutates normal `markethawk_postgres_data` or `markethawk_redis_data`.
- No live credentials are required for the demo stack.
