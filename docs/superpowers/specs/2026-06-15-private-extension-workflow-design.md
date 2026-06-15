# Private Extension Workflow Documentation Design

**Date:** 2026-06-15
**Issue:** #446
**Status:** Draft

## Overview

MarketHawk users who build proprietary scanners, risk rules, or trading logic need a clear path to load those modules into the running platform without committing them to the public repository. Issue #438 (Epic: Formal module extension points) delivers the implementation across #439–#445; issue #446 is the documentation deliverable that makes the workflow accessible to end users.

This spec defines the documentation structure, content, and example file for the private extension workflow.

## Requirements

Distilled from the acceptance criteria and Q&A:

1. **`docs/extensions.md`** — primary reference document covering the end-to-end workflow: create, install/mount, configure, and verify extension modules.
2. **`docs/extensions/example_scanner.py`** — a fully worked, lint-able scanner extension example outside `backend/app/` and not loaded by default.
3. **`ENV_VARIABLES.md`** — new section documenting `MARKETHAWK_EXTENSION_MODULES`.
4. Primary installation path: **Docker volume bind mount** via `docker-compose.override.yml` (local dev).
5. Secondary installation path: **Custom Docker image** built `FROM` the MarketHawk backend image (production/deployment).
6. Worked code example: **one full scanner extension** (the flagship extension type from #440) — create, register descriptor, mount, configure, verify.
7. Reference table: the other six extension types (data provider, alert channel, broker adapter, position sizing model, risk rule, outcome analyzer) with registration signatures only.
8. Explicit statement: **extension-owned Alembic migrations are not supported in v1**; extensions must use existing JSON/config surfaces (`SystemConfig`, `ScannerConfig.parameters` JSONB, `indicators`/`enrichment` JSONB fields on `ScannerEvent`).
9. Explicit statement: **Python entry-point discovery is deferred** — not current behavior.
10. `CLAUDE.md` and `DEVELOPMENT.md` get one-line cross-references to `docs/extensions.md`.

## Architecture / Approach

### File Layout

```
docs/extensions.md                       ← primary user-facing doc (new)
docs/extensions/
  example_scanner.py                     ← worked example (new, never auto-loaded)
ENV_VARIABLES.md                         ← one new "Extensions" section
CLAUDE.md                                ← one-line cross-ref added to "Further Reading"
```

No changes to any file under `backend/` or `frontend/` — this ticket is documentation-only.

### `docs/extensions.md` Structure

```
# MarketHawk Private Extension Workflow

## What are extensions?
## Quick start (5-step recipe)
## Step 1 — Create an extension module
## Step 2 — Mount or install the module
   ### Local development (bind mount)
   ### Production (custom Docker image)
## Step 3 — Configure MARKETHAWK_EXTENSION_MODULES
## Step 4 — Verify the module loaded
## Extension point reference
   ### Scanners (#440)
   ### Data providers (#441)
   ### Alert channels (#442)
   ### Broker adapters (#443)
   ### Position sizing models (#444)
   ### Risk rules (#444)
   ### Outcome analyzers (#445)
## Constraints — v1
   ### No extension-owned migrations
   ### Using existing JSON configuration surfaces
## Future — Python entry-point discovery
```

### Quick Start Recipe (content)

The five-step recipe in the doc:

1. **Write** your extension module (`myedge/scanners.py`) with a top-level `register()` function or module-level import-time calls.
2. **Mount** it: add a volume entry to `docker-compose.override.yml` on `backend` and `celery-worker` services — e.g. `- /opt/markethawk-ext/myedge:/app/myedge:ro`.
3. **Configure**: add `MARKETHAWK_EXTENSION_MODULES=myedge.scanners` to `.env`.
4. **Restart**: `docker-compose restart backend celery-worker celery-beat`.
5. **Verify**: `docker-compose logs backend | grep -i extension` — a successful load logs the module name; an import error fails fast with a descriptive message.

### Bind-Mount Detail

The `docker-compose.override.yml` already bind-mounts `./backend:/app` for hot-reload. The extension workflow follows the same pattern. Crucially, the mount must be applied to **all services that import the application at startup**: `backend`, `celery-worker`, `celery-beat`, and optionally `live-scanner`. The doc shows a complete override snippet:

```yaml
services:
  backend:
    volumes:
      - /opt/markethawk-ext/myedge:/app/myedge:ro
    environment:
      MARKETHAWK_EXTENSION_MODULES: "myedge.scanners"

  celery-worker:
    volumes:
      - /opt/markethawk-ext/myedge:/app/myedge:ro

  celery-beat:
    volumes:
      - /opt/markethawk-ext/myedge:/app/myedge:ro
```

The env var is set once in `.env`; the volume entries must be repeated per service because `docker-compose.override.yml` configures services independently.

### Custom Image Path (production)

```dockerfile
FROM ghcr.io/omniscient/markethawk-backend:latest
COPY ./myedge /app/myedge
```

Then set `MARKETHAWK_EXTENSION_MODULES=myedge.scanners` in `.env` and override the image reference in `docker-compose.yml` (or use `IMAGE_TAG`). No bind mounts required.

### `docs/extensions/example_scanner.py` Content

A complete, runnable scanner module that:
- Imports the extension registry from `app.extensions` (the loader introduced in #439).
- Defines a `ScannerDescriptor` with `key`, `display_name`, `description`, `run` callable, `asset_classes`, `date_range_support`, and `default_parameters`.
- Calls `register_scanner(descriptor)` at module level so import = registration.
- Implements a minimal `async run(tickers, db, event_date, config)` callable that returns a list of `ScannerEvent` rows.
- Includes a module-level docstring noting it is an **illustrative example** and not loaded unless explicitly added to `MARKETHAWK_EXTENSION_MODULES`.

The example follows the pattern established by `backend/app/providers/base.py` (base interface) and `backend/app/services/pre_market_scan.py` (self-registration at import time).

### Extension Point Reference Table

A table in `docs/extensions.md` covering all seven extension types:

| Extension type | Issue | Registration call | Key interface |
|---|---|---|---|
| Scanner | #440 | `register_scanner(ScannerDescriptor(...))` | `async run(tickers, db, event_date, config) → list[ScannerEvent]` |
| Data provider | #441 | `register_provider(ProviderDescriptor(...))` | `BaseDataProvider` subclass |
| Alert channel | #442 | `register_alert_channel(ChannelDescriptor(...))` | `async send(event, rule, config) → None` |
| Broker adapter | #443 | `register_broker_adapter(AdapterDescriptor(...))` | `async submit_order(...)`, `async cancel_order(...)`, `async poll_fills(...)` |
| Position sizing model | #444 | `register_sizing_model(SizingDescriptor(...))` | `compute_size(strategy, account) → Decimal` |
| Risk rule | #444 | `register_risk_rule(RuleDescriptor(...))` | `evaluate(order, strategy, db) → RuleDecision` |
| Outcome analyzer | #445 | `register_outcome_analyzer(AnalyzerDescriptor(...))` | `analyze(events, db) → AnalysisResult` |

*Note: exact class names and signatures are defined by #439–#445 and should be verified against the implementation before this doc is merged.*

### v1 Constraints Section

This section states clearly:

- **No extension-owned migrations.** Extensions cannot add database tables or columns. Alembic (`alembic/versions/`) is exclusively for the core platform.
- **Use existing JSON surfaces instead.** Extensions can store per-scanner configuration in `ScannerConfig.parameters` (JSONB), append metadata to `ScannerEvent.indicators`/`enrichment` (JSONB), and read runtime settings from `SystemConfig` key-value pairs. All these surfaces are already committed and migration-stable.

### Future: Entry-Point Discovery

One paragraph explaining that a future version of the loader will support Python packaging entry points (`[project.entry-points."markethawk.extensions"]`) so installed packages self-register without explicit `MARKETHAWK_EXTENSION_MODULES` configuration. This is intentionally deferred from v1 to keep the initial loader simple.

### `ENV_VARIABLES.md` Addition

New section added before the Verification section:

```markdown
## Extensions

Set on `backend`, `celery-worker`, `celery-beat`, and `live-scanner`.

| Variable | Default | Purpose |
|----------|---------|---------|
| `MARKETHAWK_EXTENSION_MODULES` | `""` (disabled) | Comma-separated list of Python module paths to import at backend startup, e.g. `myedge.scanners,myedge.risk`. Each module is imported exactly once; a missing or unimportable module causes a fatal startup error. See [docs/extensions.md](docs/extensions.md). |
```

## Alternatives Considered

**A: Inline code example only (no example file)**
All example code lives as fenced blocks in `docs/extensions.md` prose. Simpler structure, but prose code blocks are not lint-checked and silently rot as APIs evolve. Rejected because the example needs to be copy-pasteable and verifiable.

**B: Example file at `docs/extensions/example_scanner.py` + inline excerpt (chosen)**
The full example lives as a real Python file outside `backend/app/`, referenced by the doc and inlined as a short excerpt. Satisfies "not as production code loaded by default" (the file path is never scanned by the loader) while remaining lint-able and git-historical.

**C: One example file per extension type**
Seven example files, one per extension point. Over-scoped given that the registration pattern is uniform — one worked scanner example plus a reference table teaches the model without seven files to maintain.

## Open Questions (non-blocking)

1. **Exact API surface** — The registration function names and descriptor field names will be defined by #439–#445. The doc should be authored against this spec and finalized with a light pass after those tickets land to match the concrete API. The example file should have a `# NOTE: verify against final API surface` comment at the top.
2. **`live-scanner` extension support** — Whether `live-scanner` loads extension modules at startup (it's a separate asyncio process). This is an implementation question for #439; the doc should note that live-scanner support is implementation-defined and may be added in a follow-on ticket.
3. **Log verbosity** — The exact log format for successful extension loading (used in the "Verify" step) will be determined by #439. The spec says "logs the module name" — confirm the actual log level and message format.

## Assumptions

- **[Assumed]** `MARKETHAWK_EXTENSION_MODULES` is read by `app/core/config.py` `Settings` class as a string field (defaulting to `""`) and parsed at startup. This follows the existing env-var pattern.
- **[Assumed]** Extension modules live on the Python path (`/app` is already on `PYTHONPATH` inside the container). The bind-mount-to-`/app` approach (e.g. `/opt/ext/myedge:/app/myedge:ro`) does not require an additional `PYTHONPATH` override.
- **[Assumed]** The seven extension types listed in the reference table are the complete v1 scope; no additional extension points are planned before #438 is closed.
- **[Assumed]** `docs/extensions.md` is the canonical location; no top-level `EXTENSIONS.md` is needed (the pattern in this repo places reference docs under `docs/`).
