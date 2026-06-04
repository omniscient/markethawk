# Plan: ADR Hygiene — Renumber Duplicate 0010 and Add Decision-Log Index

**Goal**: Resolve the duplicate ADR-0010 number collision, renumber the GELF logging ADR to 0011, add a decision-log index at `docs/adr/README.md`, and link the index from `CONTEXT.md`.

**Issue**: [#172 — docs: ADR hygiene — renumber duplicate 0010 and add a decision-log index](https://github.com/omniscient/markethawk/issues/172)

**Architecture**: No code changes. Pure documentation: one file rename, internal title fix, cross-reference updates, one new file, one file edit.

**Tech Stack**: Markdown, git (mv + edit)

**Component**: `docs/adr/`, `CONTEXT.md`

---

## File Structure

| File | Change |
|------|--------|
| `docs/adr/0010-dark-factory-gelf-logging.md` | Renamed → `0011-dark-factory-gelf-logging.md`; internal title updated |
| `docs/adr/README.md` | New — decision-log table |
| `CONTEXT.md` | Add "Architecture Decisions" section linking to `docs/adr/README.md` |
| `docs/superpowers/specs/2026-05-29-dark-factory-gelf-logging-design.md` | Update `0010` → `0011` filename reference (line 66) |
| `docs/superpowers/plans/2026-05-29-dark-factory-gelf-logging.md` | Update `0010` → `0011` filename reference (lines 12, 209, 216–217) |

---

## Task 1 — Rename GELF ADR from 0010 → 0011 and fix cross-references

**Files**: `docs/adr/0010-dark-factory-gelf-logging.md`, `docs/superpowers/specs/2026-05-29-dark-factory-gelf-logging-design.md`, `docs/superpowers/plans/2026-05-29-dark-factory-gelf-logging.md`

### Verify current (broken) state

```bash
ls docs/adr/0010-*.md
# Expected output (broken — two files share the 0010 prefix):
# docs/adr/0010-api-versioning-policy.md
# docs/adr/0010-dark-factory-gelf-logging.md
```

### Implement

**Step 1.1** — Rename the file:

```bash
git mv docs/adr/0010-dark-factory-gelf-logging.md docs/adr/0011-dark-factory-gelf-logging.md
```

**Step 1.2** — Update the internal title in `docs/adr/0011-dark-factory-gelf-logging.md`.

Change line 1 from:
```markdown
# ADR-0010: GELF Log Shipping for Dark Factory Containers
```
To:
```markdown
# ADR-0011: GELF Log Shipping for Dark Factory Containers
```

**Step 1.3** — Update the cross-reference in `docs/superpowers/specs/2026-05-29-dark-factory-gelf-logging-design.md` (line 66):

Change:
```markdown
| `Docs/adr/0010-dark-factory-gelf-logging.md` | ADR documenting the decision and trade-offs |
```
To:
```markdown
| `docs/adr/0011-dark-factory-gelf-logging.md` | ADR documenting the decision and trade-offs |
```

**Step 1.4** — Update the three cross-references in `docs/superpowers/plans/2026-05-29-dark-factory-gelf-logging.md`:

Line 12, change:
```markdown
**ADR:** [`Docs/adr/0010-dark-factory-gelf-logging.md`](../../adr/0010-dark-factory-gelf-logging.md)
```
To:
```markdown
**ADR:** [`docs/adr/0011-dark-factory-gelf-logging.md`](../../adr/0011-dark-factory-gelf-logging.md)
```

Line 209, change:
```markdown
- Already on disk: `Docs/adr/0010-dark-factory-gelf-logging.md`
```
To:
```markdown
- Already on disk: `docs/adr/0011-dark-factory-gelf-logging.md`
```

Lines 216–217, change:
```bash
git add Docs/superpowers/specs/2026-05-29-dark-factory-gelf-logging-design.md Docs/adr/0010-dark-factory-gelf-logging.md
git commit -m "docs: add spec and ADR-0010 for dark factory GELF logging (#122)"
```
To:
```bash
git add docs/superpowers/specs/2026-05-29-dark-factory-gelf-logging-design.md docs/adr/0011-dark-factory-gelf-logging.md
git commit -m "docs: add spec and ADR-0011 for dark factory GELF logging (#122)"
```

### Verify correct state

```bash
ls docs/adr/0010-*.md docs/adr/0011-*.md
# Expected output — exactly one file per number, no 0010 collision:
# docs/adr/0010-api-versioning-policy.md
# docs/adr/0011-dark-factory-gelf-logging.md

head -1 docs/adr/0011-dark-factory-gelf-logging.md
# Expected:
# # ADR-0011: GELF Log Shipping for Dark Factory Containers

grep "0010-dark-factory-gelf" docs/superpowers/specs/2026-05-29-dark-factory-gelf-logging-design.md docs/superpowers/plans/2026-05-29-dark-factory-gelf-logging.md
# Expected: (no output — all references updated)

grep "0011-dark-factory-gelf" docs/superpowers/specs/2026-05-29-dark-factory-gelf-logging-design.md docs/superpowers/plans/2026-05-29-dark-factory-gelf-logging.md
# Expected: references present in both files
```

### Commit

```bash
git add docs/adr/0011-dark-factory-gelf-logging.md \
        docs/superpowers/specs/2026-05-29-dark-factory-gelf-logging-design.md \
        docs/superpowers/plans/2026-05-29-dark-factory-gelf-logging.md
git commit -m "docs(#172): renumber GELF logging ADR from 0010 to 0011"
```

---

## Task 2 — Create `docs/adr/README.md` decision-log index

**Files**: `docs/adr/README.md` (new)

### Verify current (absent) state

```bash
ls docs/adr/README.md 2>/dev/null || echo "No README — correct, about to create it"
```

### Implement

Create `docs/adr/README.md` with the following content:

```markdown
# Architecture Decision Records

This directory contains the architecture decision log for MarketHawk. Each record documents a significant design choice: the context, the alternatives considered, the decision taken, and its consequences.

## Decision Log

| # | Title | Status | Date |
|---|-------|--------|------|
| [0001](0001-polygon-for-historical-market-data.md) | Polygon.io for Historical Market Data | Accepted | — |
| [0002](0002-jwt-authentication-httponly-cookies.md) | JWT Authentication via HttpOnly Cookies | Accepted | 2026-05-27 |
| [0003](0003-slowapi-middleware-for-rate-limiting.md) | SlowAPI Middleware for Rate Limiting | Accepted | 2026-05-28 |
| [0004](0004-synchronous-sqlalchemy.md) | Synchronous SQLAlchemy ORM | Accepted (short-term; async tracked in #103) | 2026-05-28 |
| [0005](0005-jsonb-for-scanner-event-metadata.md) | JSONB Columns for Scanner Event Metadata | Accepted | 2026-05-28 |
| [0006](0006-celery-redis-for-background-tasks.md) | Celery + Redis for Background Tasks | Accepted | 2026-05-28 |
| [0007](0007-live-scanner-service-extraction.md) | Live Scanner as a Separate Container | Accepted | 2026-05-28 |
| [0008](0008-dark-factory-autonomous-development.md) | Dark Factory Autonomous Development Model | Accepted | 2026-05-28 |
| [0009](0009-naive-utc-timestamps.md) | Naive UTC Timestamps in the Database | Accepted | 2026-05-28 |
| [0010](0010-api-versioning-policy.md) | API Versioning Policy | Accepted | 2026-05-29 |
| [0011](0011-dark-factory-gelf-logging.md) | GELF Log Shipping for Dark Factory Containers | Accepted | 2026-05-29 |

## Adding a New ADR

Copy `template.md` to `NNNN-short-title.md` where `NNNN` is the next sequential number. Fill in all fields. Add a row to the table above.
```

### Verify correct state

```bash
cat docs/adr/README.md | grep "| \[00" | wc -l
# Expected: 11 (one row per ADR)

grep "0011" docs/adr/README.md
# Expected: row with 0011-dark-factory-gelf-logging.md link present

grep "0010" docs/adr/README.md | grep -v "api-versioning"
# Expected: (no output — only 0010-api-versioning-policy.md in table, no stale GELF reference)
```

### Commit

```bash
git add docs/adr/README.md
git commit -m "docs(#172): add decision-log index at docs/adr/README.md"
```

---

## Task 3 — Link the index from `CONTEXT.md`

**Files**: `CONTEXT.md`

### Verify current (absent) state

```bash
grep -n "adr\|ADR\|Architecture Decision\|decision log" CONTEXT.md -i
# Expected: (no output — no ADR pointer exists yet)
```

### Implement

Append the following section to `CONTEXT.md` (after the last line):

```markdown

## Architecture Decisions

Significant design choices are recorded as ADRs in [`docs/adr/`](docs/adr/).

The **[decision-log index](docs/adr/README.md)** lists every ADR by number, title, status, and date — scan it to find what has already been decided before proposing a new approach.
```

### Verify correct state

```bash
grep -n "Architecture Decisions\|docs/adr/README" CONTEXT.md
# Expected:
# 93:## Architecture Decisions
# 97:The **[decision-log index](docs/adr/README.md)** lists every ADR...

tail -6 CONTEXT.md
# Expected: the new section is present at the end of the file
```

### Commit

```bash
git add CONTEXT.md
git commit -m "docs(#172): link ADR decision-log index from CONTEXT.md"
```
