# Frontend Page Decomposition — Design Spec

**Issue**: [#74 — refactor: decompose monolithic frontend page components](https://github.com/omniscient/markethawk/issues/74)
**Date**: 2026-05-25
**Status**: Pending Review

## Overview

Five frontend pages exceed 680 LOC and mix state management, data fetching, business logic, and presentation in a single file. This refactor extracts each page into a directory of co-located panels and hooks so that a focused modification (e.g. "change how scan results display") requires reading ~200 LOC rather than 800+. No visible behaviour changes; this is a pure structural refactor.

## Problem

| File | Current LOC | Problem |
|------|-------------|---------|
| `pages/AutoTrading.tsx` | 1,003 | 8 inline sub-components + 5 config objects + formatters |
| `pages/Scanner.tsx` | 830 | 15+ useState + inline WS logic + 3 inline sub-components |
| `pages/Alerts.tsx` | 812 | Push subscription lifecycle mixed with alert rule CRUD |
| `pages/StockDetailPage.tsx` | 694 | Chart, metadata, and event history all entangled |
| `pages/ActiveWatchlist.tsx` | 683 | 206 LOC WebSocket hook defined inline |

An agent modifying one concern must load the entire file. The goal is no file exceeds ~250 LOC.

## Requirements

From the issue and Q&A:

1. Each of the five pages is extracted into a directory (`pages/PageName/`) with an `index.tsx` shell and co-located panel files.
2. Panel files are page-private. Only promote to `components/` if a second page imports them.
3. Hooks extracted from pages land in `frontend/src/hooks/` following the existing `useLiveStockData` / `useScanTask` / `useScorecard` naming convention.
4. No file in the output exceeds ~250 LOC (target; hard limit 300 LOC).
5. `npx tsc --noEmit` passes after every per-page extraction before moving to the next.
6. Browser smoke-test each page before committing: confirm it renders and its primary interactions work.
7. Delivered in two PRs: PR 1 = Scanner only (establishes the pattern); PR 2 = the remaining four pages.
8. Inline sub-components in `AutoTrading.tsx` (`StatusBadge`, `StrategyRow`, `NumberField`, `ToggleField`, etc.) are treated as page-private helpers and co-located in `AutoTrading/` — not promoted to `components/`.
9. Scope is the five named page files only. `UniverseFormModal.tsx` (492 LOC) and `QualityReportModal.tsx` (753 LOC) are out of scope.

## Architecture

### Pattern

```
pages/
  Scanner/
    index.tsx           # Shell: layout + query orchestration only; delegates to panels
    ScanConfigPanel.tsx # Universe selector, date range, scan trigger
    LiveProgressPanel.tsx # WebSocket progress + status display
    ResultsPanel.tsx    # Table, sorting, review controls
  AutoTrading/
    index.tsx
    StrategyPanel.tsx
    OrdersPanel.tsx
    AccountPanel.tsx
    ConfigPanel.tsx
    components.tsx      # Page-private: StatusBadge, StrategyRow, NumberField, ToggleField, etc.
  Alerts/
    index.tsx
    AlertRulesPanel.tsx
    AlertLogsPanel.tsx
    ChannelConfigPanel.tsx
  StockDetailPage/
    index.tsx
    ChartPanel.tsx
    MetadataPanel.tsx
    ScannerHistoryPanel.tsx
  ActiveWatchlist/
    index.tsx
    WatchlistTable.tsx
    AlertBadges.tsx
hooks/
  useScannerState.ts    # Extracted: 15 useState + localStorage + WS (was inline in Scanner.tsx)
  useWatchlistLive.ts   # Extracted: 206 LOC WS hook (was inline in ActiveWatchlist.tsx)
```

### Panel design rule

The page shell (`index.tsx`) owns:
- Route-level React Query calls
- Top-level layout (grid/flex)
- Props passed down to panels

Panels own:
- Their slice of local UI state
- Presentation and user interactions for their domain
- No direct API calls — receive data and callbacks via props

### PR 1 — Scanner (template PR)

Purpose: establish the directory/panel/hook pattern that PR 2 will follow.

**Files deleted:** `pages/Scanner.tsx`  
**Files created:**

| File | ~LOC | Responsibility |
|------|------|----------------|
| `pages/Scanner/index.tsx` | ~120 | Shell: layout, query orchestration, delegates to panels |
| `pages/Scanner/ScanConfigPanel.tsx` | ~150 | Universe selector, date range, scan trigger |
| `pages/Scanner/LiveProgressPanel.tsx` | ~100 | WebSocket progress + status display |
| `pages/Scanner/ResultsPanel.tsx` | ~200 | Table, sorting, review controls |
| `hooks/useScannerState.ts` | ~80 | 15 useState + localStorage persistence + WS ref |

`App.tsx` import updates: `import Scanner from './pages/Scanner'` resolves to `pages/Scanner/index.tsx` automatically — no router change needed.

### PR 2 — Remaining four pages

Follow the pattern from PR 1. Order of extraction within the PR: AutoTrading first (largest, most benefit), then Alerts, StockDetailPage, ActiveWatchlist.

**AutoTrading (1,003 → ~5 files):**

| File | ~LOC | Responsibility |
|------|------|----------------|
| `AutoTrading/index.tsx` | ~120 | Shell |
| `AutoTrading/StrategyPanel.tsx` | ~200 | Strategy list, activating/deactivating strategies |
| `AutoTrading/OrdersPanel.tsx` | ~150 | Active orders table, order controls |
| `AutoTrading/AccountPanel.tsx` | ~100 | Account metrics display |
| `AutoTrading/ConfigPanel.tsx` | ~150 | Strategy form (uses page-private helpers) |
| `AutoTrading/components.tsx` | ~150 | Page-private: StatusBadge, StrategyRow, StratStat, OrderRow, AccountMetric, StatRow, NumberField, ToggleField |

**Alerts (812 → ~4 files):**

| File | ~LOC | Responsibility |
|------|------|----------------|
| `Alerts/index.tsx` | ~100 | Shell |
| `Alerts/AlertRulesPanel.tsx` | ~200 | Alert rule list, create/edit form |
| `Alerts/AlertLogsPanel.tsx` | ~150 | Alert history/log |
| `Alerts/ChannelConfigPanel.tsx` | ~200 | Push subscription lifecycle + channel settings |

**StockDetailPage (694 → ~4 files):**

| File | ~LOC | Responsibility |
|------|------|----------------|
| `StockDetailPage/index.tsx` | ~100 | Shell |
| `StockDetailPage/ChartPanel.tsx` | ~200 | Lightweight Charts OHLCV + controls |
| `StockDetailPage/MetadataPanel.tsx` | ~150 | Ticker info, fundamentals, news |
| `StockDetailPage/ScannerHistoryPanel.tsx` | ~150 | RecentEvents list, Clear History button |

**ActiveWatchlist (683 → ~3 files + 1 hook):**

| File | ~LOC | Responsibility |
|------|------|----------------|
| `ActiveWatchlist/index.tsx` | ~100 | Shell |
| `ActiveWatchlist/WatchlistTable.tsx` | ~200 | Symbol rows, real-time price display |
| `ActiveWatchlist/AlertBadges.tsx` | ~80 | Alert badge rendering |
| `hooks/useWatchlistLive.ts` | ~200 | Extracted WS hook (was 206 LOC inline) |

## Alternatives Considered

### Option B: Extract to `components/PageName/` rather than `pages/PageName/`

The existing `components/` directory contains shared components (`ScannerResults`, `ScannerConfig`, `SignalReviewStats`) used by multiple pages. Moving page-private panels there would blur the shared/private distinction. **Rejected** in favour of co-location under `pages/`.

### Option C: One large PR for all five pages

Simpler delivery but a 4,000+ LOC PR is hard to review and introduces more risk of cross-page merge conflicts. **Rejected** in favour of the two-PR split.

### Option D: Shared utility extraction (NumberField, ToggleField, StatusBadge)

`NumberField` is hardcoded to `focus:ring-financial-blue` and wired to the `stratForm` pattern; `ToggleField` requires a mandatory `description` prop not used elsewhere. Neither is generic enough to promote. Alerts uses `ToggleRight`/`ToggleLeft` icons inline without this abstraction. **Rejected** — keep page-private per the Q1 rule.

## Open Questions

- `AutoTrading/components.tsx` may still approach 150 LOC. If it does, consider splitting into `AutoTrading/FormFields.tsx` (NumberField, ToggleField) and `AutoTrading/DisplayComponents.tsx` (StatusBadge, StrategyRow, etc.) — decide during implementation.

## Assumptions

- **Import resolution**: TypeScript resolves `./pages/Scanner` to `./pages/Scanner/index.tsx` with no `tsconfig.json` changes required. Verify this holds for the Vite build as well.
- **LOC estimates** are approximate ±30 LOC. If a panel comes out at 260–280 LOC, that is acceptable.
- **Existing shared components stay put**: `components/ScannerResults.tsx`, `components/ScannerConfig.tsx`, `components/SignalReviewStats.tsx` are not moved — they remain shared components imported by the page shells.

## Out of Scope

- `components/UniverseFormModal.tsx` (492 LOC)
- `components/QualityReportModal.tsx` (753 LOC)
- Deduplicating shared sub-components across pages
- Adding tests (no frontend tests currently exist)
- Any change to routing, API calls, or business logic

## Acceptance Criteria

- [ ] All five pages render correctly in the browser after extraction (golden path: load the page, confirm primary interactions work)
- [ ] `npx tsc --noEmit` passes after each per-page extraction
- [ ] No file in the output exceeds 300 LOC
- [ ] `App.tsx` router imports require no changes (directory index resolution)
- [ ] Existing `components/ScannerResults.tsx`, `ScannerConfig.tsx`, `SignalReviewStats.tsx` are unchanged
- [ ] `hooks/useScannerState.ts` and `hooks/useWatchlistLive.ts` are new standalone files
- [ ] PR 1 covers Scanner only; PR 2 covers the remaining four pages
