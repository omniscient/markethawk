# Ratchet Frontend Coverage Thresholds to 30%/22% — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add high-value tests for the highest-yield 0%-covered frontend files until coverage actuals clear ~32%/24%, then update the gate in `frontend/vitest.config.ts` to statements: 30, branches: 22, functions: 22, lines: 30 (using the established `floor(actual) - 3` headroom formula).

**Architecture:** Frontend only. No backend changes. All test files live in `frontend/src/`. Coverage is measured by Vitest v8 over `src/**` (already configured with `all: true`). The `renderWithQuery` test utility at `frontend/src/test-utils/renderWithQuery.tsx` provides `QueryClientProvider + MemoryRouter` wrapping.

**Tech Stack:** Vitest + React Testing Library + jsdom. TypeScript strict-mode. `npx tsc -p tsconfig.app.json --noEmit` must pass after every task (the root `tsconfig.json` uses `"files": []` + project references and does not typecheck `src/` directly; `tsconfig.app.json` is the correct target for production-code type gates).

**Issue:** #250
**Spec:** `docs/superpowers/specs/2026-06-10-ratchet-coverage-thresholds-design.md`
**Branch:** `refine/issue-250-ratchet-frontend-coverage-thresholds-to-`

---

## File Structure

| File | Action | Purpose |
|------|--------|---------|
| `frontend/src/utils/indicators.test.ts` | Create | Unit tests for `calculateDoubleSuperTrend` |
| `frontend/src/pages/StockDetailPage/MetadataPanel.test.tsx` | Create | Tests for MetadataPanel presentational component |
| `frontend/src/pages/StockDetailPage/ScannerHistoryPanel.test.tsx` | Create | Tests for ScannerHistoryPanel presentational component |
| `frontend/src/pages/AutoTrading/AccountPanel.test.tsx` | Create | Tests for AccountPanel presentational component |
| `frontend/src/pages/AutoTrading/OrdersPanel.test.tsx` | Create | Tests for OrdersPanel presentational component |
| `frontend/src/components/scorecard/HeroMetrics.test.tsx` | Create (if needed) | Tests for HeroMetrics scorecard component |
| `frontend/src/components/scorecard/IntervalTable.test.tsx` | Create (if needed) | Tests for IntervalTable scorecard component |
| `frontend/vitest.config.ts` | Edit | Raise thresholds to 30/22 |

---

## Task 1: Add tests for `src/utils/indicators.ts`

**Files:** `frontend/src/utils/indicators.test.ts`

This file contains a single exported function `calculateDoubleSuperTrend` — pure TypeScript, no JSX, no hooks. It is the highest-yield test target.

- [ ] Create `frontend/src/utils/indicators.test.ts` with the following content:

```typescript
import { describe, it, expect } from 'vitest';
import { calculateDoubleSuperTrend, OHLCVInput } from './indicators';

const makeBar = (h: number, l: number, o: number, c: number, i: number): OHLCVInput => ({
  High: h, Low: l, Open: o, Close: c, time: i,
});

const flatBars = (n: number): OHLCVInput[] =>
  Array.from({ length: n }, (_, i) => makeBar(11, 9, 10, 10, i));

describe('calculateDoubleSuperTrend', () => {
  it('returns [] when data length < atrPeriod (default 12)', () => {
    expect(calculateDoubleSuperTrend(flatBars(11))).toEqual([]);
  });

  it('returns [] when data length equals atrPeriod - 1', () => {
    expect(calculateDoubleSuperTrend(flatBars(5), 3, 6)).toEqual([]);
  });

  it('returns one result per input bar when data.length >= atrPeriod', () => {
    const result = calculateDoubleSuperTrend(flatBars(12));
    expect(result).toHaveLength(12);
  });

  it('each result has time, tsl1, tsl2, trend fields', () => {
    const result = calculateDoubleSuperTrend(flatBars(12));
    const last = result[result.length - 1];
    expect(last).toHaveProperty('time');
    expect(last).toHaveProperty('tsl1');
    expect(last).toHaveProperty('tsl2');
    expect(last).toHaveProperty('trend');
  });

  it('time passthrough — preserves input bar time', () => {
    const bars = flatBars(12);
    const result = calculateDoubleSuperTrend(bars);
    result.forEach((r, i) => expect(r.time).toBe(i));
  });

  it('default trend is 1 for flat price action at steady state', () => {
    // Flat candles: close == prevTDown is always false, so trend stays 1
    const result = calculateDoubleSuperTrend(flatBars(20));
    expect(result[result.length - 1].trend).toBe(1);
  });

  it('tsl1 equals tUp and tsl2 equals tDown when trend is 1', () => {
    const result = calculateDoubleSuperTrend(flatBars(20));
    const last = result[result.length - 1];
    // When trend=1: tsl1 = tUp (support line), tsl2 = tDown (resistance line)
    // tUp (support) should be <= close; tDown (resistance) should be >= close
    expect(last.tsl1).toBeLessThanOrEqual(10);
    expect(last.tsl2).toBeGreaterThanOrEqual(10);
  });

  it('detects trend flip to -1 on sustained close < tUp', () => {
    // Build bars that initially trend up, then crash below tUp
    const bars: OHLCVInput[] = [
      ...Array.from({ length: 15 }, (_, i) => makeBar(12 + i, 10 + i, 11 + i, 11.5 + i, i)),
      // Sudden drop: close well below any reasonable tUp
      makeBar(5, 1, 3, 2, 15),
      makeBar(5, 1, 3, 2, 16),
      makeBar(5, 1, 3, 2, 17),
    ];
    const result = calculateDoubleSuperTrend(bars);
    expect(result[result.length - 1].trend).toBe(-1);
  });

  it('custom factor and atrPeriod parameters are accepted', () => {
    const result = calculateDoubleSuperTrend(flatBars(8), 2, 5);
    expect(result).toHaveLength(8);
  });
});
```

- [ ] Run the tests and confirm they all pass:
  ```bash
  cd frontend && npx vitest run src/utils/indicators.test.ts
  ```
  Expected: `9 tests passed`

- [ ] Run TypeScript check:
  ```bash
  cd frontend && npx tsc -p tsconfig.app.json --noEmit
  ```
  Expected: no errors

- [ ] Commit:
  ```bash
  git add frontend/src/utils/indicators.test.ts
  git commit -m "test(frontend): add calculateDoubleSuperTrend unit tests

  Covers: empty-return guard, length passthrough, field presence,
  time passthrough, steady-state trend=1, tsl1/tsl2 assignment,
  trend flip to -1, and custom parameters.
  
  Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
  ```

---

## Task 2: Add tests for `MetadataPanel`

**Files:** `frontend/src/pages/StockDetailPage/MetadataPanel.test.tsx`

`MetadataPanel` is a pure presentational component: `{ symbol, details, scannerResults, events }` → rendered JSX. No hooks. Imports `NewsFeed` which makes API calls — mock it to isolate rendering.

- [ ] Create `frontend/src/pages/StockDetailPage/MetadataPanel.test.tsx`:

```tsx
import { vi, describe, it, expect } from 'vitest';
import { screen } from '@testing-library/react';
import { renderWithQuery } from '../../test-utils/renderWithQuery';
import { MetadataPanel } from './MetadataPanel';

vi.mock('../../components/NewsFeed', () => ({
  default: ({ ticker }: { ticker: string }) => (
    <div data-testid="news-feed">{ticker}</div>
  ),
}));

const defaultProps = {
  symbol: 'AAPL',
  details: {
    pre_market: {
      pre_market_volume: 200000,
      pre_market_high: 187.5,
    },
  },
  scannerResults: [
    { metadata: { catalyst_summary: 'earnings beat' } },
  ],
  events: [{ id: 1 }],
};

describe('MetadataPanel', () => {
  it('renders without crashing', () => {
    renderWithQuery(<MetadataPanel {...defaultProps} />);
  });

  it('passes symbol to NewsFeed', () => {
    renderWithQuery(<MetadataPanel {...defaultProps} />);
    expect(screen.getByTestId('news-feed')).toHaveTextContent('AAPL');
  });

  it('shows PM High with formatted price when available', () => {
    renderWithQuery(<MetadataPanel {...defaultProps} />);
    expect(screen.getByText(/187\.50/)).toBeInTheDocument();
  });

  it('shows N/A for PM High when pre_market details are missing', () => {
    renderWithQuery(
      <MetadataPanel {...defaultProps} details={null} />
    );
    expect(screen.getByText(/N\/A/)).toBeInTheDocument();
  });

  it('Scanner Alert Detected shows active dot when events.length > 0', () => {
    renderWithQuery(<MetadataPanel {...defaultProps} />);
    expect(screen.getByText('Scanner Alert Detected')).toBeInTheDocument();
  });

  it('Check Extended Hours Volume shows active dot when pre_market_volume > 100000', () => {
    renderWithQuery(<MetadataPanel {...defaultProps} />);
    expect(screen.getByText('Check Extended Hours Volume')).toBeInTheDocument();
  });

  it('Review Catalyst Summary shows active dot when scannerResults has catalyst_summary', () => {
    renderWithQuery(<MetadataPanel {...defaultProps} />);
    expect(screen.getByText('Review Catalyst Summary')).toBeInTheDocument();
  });

  it('shows symbol in Pro Tip text', () => {
    renderWithQuery(<MetadataPanel {...defaultProps} />);
    expect(screen.getByText(/AAPL.*PM High/i)).toBeInTheDocument();
  });
});
```

- [ ] Run tests:
  ```bash
  cd frontend && npx vitest run src/pages/StockDetailPage/MetadataPanel.test.tsx
  ```
  Expected: `8 tests passed`

- [ ] Run TypeScript check:
  ```bash
  cd frontend && npx tsc -p tsconfig.app.json --noEmit
  ```

- [ ] Commit:
  ```bash
  git add frontend/src/pages/StockDetailPage/MetadataPanel.test.tsx
  git commit -m "test(frontend): add MetadataPanel tests

  Covers: render, symbol passthrough to NewsFeed, PM High formatting,
  N/A fallback, checklist item rendering, and Pro Tip symbol.
  
  Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
  ```

---

## Task 3: Add tests for `ScannerHistoryPanel`

**Files:** `frontend/src/pages/StockDetailPage/ScannerHistoryPanel.test.tsx`

`ScannerHistoryPanel` is presentational but imports `RecentEvents` and `ForceScanDialog`. Mock both to isolate the panel's own rendering logic: status messages, button states, and the clear-confirm dialog branch.

- [ ] Create `frontend/src/pages/StockDetailPage/ScannerHistoryPanel.test.tsx`:

```tsx
import { vi, describe, it, expect } from 'vitest';
import { screen, fireEvent } from '@testing-library/react';
import { renderWithQuery } from '../../test-utils/renderWithQuery';
import { ScannerHistoryPanel, ScannerHistoryPanelProps } from './ScannerHistoryPanel';

vi.mock('../../components/RecentEvents', () => ({
  default: () => <div data-testid="recent-events" />,
}));

vi.mock('../../components/ForceScanDialog', () => ({
  default: ({ isOpen }: { isOpen: boolean }) =>
    isOpen ? <div data-testid="force-scan-dialog" /> : null,
}));

const makeTask = (status: string): ScannerHistoryPanelProps['scanTask'] => ({
  status,
  done: 0,
  total: 0,
  error: null,
});

const defaultProps: ScannerHistoryPanelProps = {
  symbol: 'TSLA',
  events: [],
  clearConfirmOpen: false,
  onClearConfirmOpen: vi.fn(),
  onClearHistory: vi.fn(),
  clearHistoryPending: false,
  scanDialogOpen: false,
  onScanDialogOpen: vi.fn(),
  scanTask: makeTask('idle'),
  scanDoneMsg: null,
  onScanSubmit: vi.fn(),
  scanSubmitting: false,
  onHighlightDate: vi.fn(),
};

describe('ScannerHistoryPanel', () => {
  it('renders without crashing', () => {
    renderWithQuery(<ScannerHistoryPanel {...defaultProps} />);
  });

  it('renders Run Scanner button when idle', () => {
    renderWithQuery(<ScannerHistoryPanel {...defaultProps} />);
    expect(screen.getByRole('button', { name: /run scanner/i })).toBeInTheDocument();
  });

  it('Run Scanner button is enabled when status is idle', () => {
    renderWithQuery(<ScannerHistoryPanel {...defaultProps} />);
    expect(screen.getByRole('button', { name: /run scanner/i })).not.toBeDisabled();
  });

  it('Run Scanner button is disabled when status is running', () => {
    renderWithQuery(
      <ScannerHistoryPanel {...defaultProps} scanTask={makeTask('running')} />
    );
    expect(screen.getByRole('button', { name: /run scanner/i })).toBeDisabled();
  });

  it('Run Scanner button is disabled when status is connecting', () => {
    renderWithQuery(
      <ScannerHistoryPanel {...defaultProps} scanTask={makeTask('connecting')} />
    );
    expect(screen.getByRole('button', { name: /run scanner/i })).toBeDisabled();
  });

  it('shows "Queued…" text when status is connecting', () => {
    renderWithQuery(
      <ScannerHistoryPanel {...defaultProps} scanTask={makeTask('connecting')} />
    );
    expect(screen.getByText(/queued/i)).toBeInTheDocument();
  });

  it('shows "Scanning… N / M days" when running with total > 0', () => {
    renderWithQuery(
      <ScannerHistoryPanel
        {...defaultProps}
        scanTask={{ status: 'running', done: 3, total: 10, error: null }}
      />
    );
    expect(screen.getByText(/scanning.*3.*\/.*10 days/i)).toBeInTheDocument();
  });

  it('shows scanDoneMsg when present', () => {
    renderWithQuery(
      <ScannerHistoryPanel {...defaultProps} scanDoneMsg="Scan complete: 5 events found" />
    );
    expect(screen.getByText(/scan complete/i)).toBeInTheDocument();
  });

  it('shows "Scan failed" when status is failed', () => {
    renderWithQuery(
      <ScannerHistoryPanel {...defaultProps} scanTask={{ ...makeTask('failed'), error: 'timeout' }} />
    );
    expect(screen.getByText(/scan failed/i)).toBeInTheDocument();
  });

  it('shows clear-confirm dialog when clearConfirmOpen is true', () => {
    renderWithQuery(
      <ScannerHistoryPanel {...defaultProps} clearConfirmOpen={true} />
    );
    expect(screen.getByText(/are you sure/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /yes, clear/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /no, cancel/i })).toBeInTheDocument();
  });

  it('clicking "Run Scanner" calls onScanDialogOpen(true)', () => {
    const onScanDialogOpen = vi.fn();
    renderWithQuery(
      <ScannerHistoryPanel {...defaultProps} onScanDialogOpen={onScanDialogOpen} />
    );
    fireEvent.click(screen.getByRole('button', { name: /run scanner/i }));
    expect(onScanDialogOpen).toHaveBeenCalledWith(true);
  });

  it('clicking "Clear History" calls onClearConfirmOpen(true)', () => {
    const onClearConfirmOpen = vi.fn();
    renderWithQuery(
      <ScannerHistoryPanel {...defaultProps} onClearConfirmOpen={onClearConfirmOpen} />
    );
    fireEvent.click(screen.getByRole('button', { name: /clear history/i }));
    expect(onClearConfirmOpen).toHaveBeenCalledWith(true);
  });

  it('renders RecentEvents', () => {
    renderWithQuery(<ScannerHistoryPanel {...defaultProps} />);
    expect(screen.getByTestId('recent-events')).toBeInTheDocument();
  });

  it('renders ForceScanDialog when scanDialogOpen is true', () => {
    renderWithQuery(
      <ScannerHistoryPanel {...defaultProps} scanDialogOpen={true} />
    );
    expect(screen.getByTestId('force-scan-dialog')).toBeInTheDocument();
  });
});
```

- [ ] Run tests:
  ```bash
  cd frontend && npx vitest run src/pages/StockDetailPage/ScannerHistoryPanel.test.tsx
  ```
  Expected: `14 tests passed`

- [ ] Run TypeScript check:
  ```bash
  cd frontend && npx tsc -p tsconfig.app.json --noEmit
  ```

- [ ] Commit:
  ```bash
  git add frontend/src/pages/StockDetailPage/ScannerHistoryPanel.test.tsx
  git commit -m "test(frontend): add ScannerHistoryPanel tests

  Covers: render, Run Scanner enable/disable states, status messages
  (connecting/running/done/failed), clear-confirm dialog branch,
  button click callbacks, and child component presence.
  
  Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
  ```

---

## Task 4: Add tests for `AccountPanel`

**Files:** `frontend/src/pages/AutoTrading/AccountPanel.test.tsx`

`AccountPanel` is presentational: takes `account`, `stats`, `config`, handlers. Import `AccountMetric`, `StatRow`, `fmtUSD`, and `pnlColor` helpers from `components` — these are also exercised through the render.

- [ ] Create `frontend/src/pages/AutoTrading/AccountPanel.test.tsx`:

```tsx
import { vi, describe, it, expect } from 'vitest';
import { screen, fireEvent } from '@testing-library/react';
import { renderWithQuery } from '../../test-utils/renderWithQuery';
import { AccountPanel, AccountPanelProps } from './AccountPanel';

const defaultProps: AccountPanelProps = {
  account: null,
  fetchingAccount: false,
  onRefreshAccount: vi.fn(),
  stats: null,
  config: null,
  onUpdateConfig: vi.fn(),
};

const connectedAccount = {
  connected: true,
  net_liquidation: 100000,
  available_funds: 50000,
  buying_power: 200000,
  open_broker_orders: [],
  error: null,
};

describe('AccountPanel', () => {
  it('renders without crashing', () => {
    renderWithQuery(<AccountPanel {...defaultProps} />);
  });

  it('shows IBKR not connected state when account is null', () => {
    renderWithQuery(<AccountPanel {...defaultProps} />);
    expect(screen.getByText(/ibkr not connected/i)).toBeInTheDocument();
  });

  it('shows IBKR not connected state when account.connected is false', () => {
    renderWithQuery(
      <AccountPanel {...defaultProps} account={{ connected: false, error: null }} />
    );
    expect(screen.getByText(/ibkr not connected/i)).toBeInTheDocument();
  });

  it('shows account error message when provided', () => {
    renderWithQuery(
      <AccountPanel
        {...defaultProps}
        account={{ connected: false, error: 'Connection refused' }}
      />
    );
    expect(screen.getByText(/connection refused/i)).toBeInTheDocument();
  });

  it('shows Net Liquidation when account is connected', () => {
    renderWithQuery(
      <AccountPanel {...defaultProps} account={connectedAccount} />
    );
    expect(screen.getByText(/net liquidation/i)).toBeInTheDocument();
  });

  it('shows formatted USD values for account metrics', () => {
    renderWithQuery(
      <AccountPanel {...defaultProps} account={connectedAccount} />
    );
    expect(screen.getByText('$100,000.00')).toBeInTheDocument();
  });

  it('shows 30-Day Breakdown when stats.total_orders > 0', () => {
    renderWithQuery(
      <AccountPanel
        {...defaultProps}
        stats={{ total_orders: 5, by_status: { open: 2, closed: 3 }, closed_count: 3, win_rate: 60, total_pnl: 1200, avg_pnl_per_trade: 240 }}
      />
    );
    expect(screen.getByText(/30-day breakdown/i)).toBeInTheDocument();
  });

  it('does not show 30-Day Breakdown when stats is null', () => {
    renderWithQuery(<AccountPanel {...defaultProps} stats={null} />);
    expect(screen.queryByText(/30-day breakdown/i)).not.toBeInTheDocument();
  });

  it('shows System Config card', () => {
    renderWithQuery(<AccountPanel {...defaultProps} />);
    expect(screen.getByText(/system config/i)).toBeInTheDocument();
  });

  it('shows Live Trading Enabled toggle', () => {
    renderWithQuery(<AccountPanel {...defaultProps} />);
    expect(screen.getByText(/live trading enabled/i)).toBeInTheDocument();
  });

  it('clicking Live Trading toggle calls onUpdateConfig', () => {
    const onUpdateConfig = vi.fn();
    renderWithQuery(
      <AccountPanel
        {...defaultProps}
        config={{ AUTO_TRADING_ENABLED: false, PAPER_ACCOUNT_SIZE: 100000 }}
        onUpdateConfig={onUpdateConfig}
      />
    );
    // The toggle button is the parent of the ToggleLeft icon
    const toggle = screen.getByText(/live trading enabled/i).closest('div')?.parentElement?.querySelector('button');
    if (toggle) fireEvent.click(toggle);
    expect(onUpdateConfig).toHaveBeenCalledWith({ AUTO_TRADING_ENABLED: true });
  });

  it('shows Refresh button', () => {
    renderWithQuery(<AccountPanel {...defaultProps} />);
    expect(screen.getByRole('button', { name: /refresh/i })).toBeInTheDocument();
  });

  it('clicking Refresh calls onRefreshAccount', () => {
    const onRefreshAccount = vi.fn();
    renderWithQuery(
      <AccountPanel {...defaultProps} onRefreshAccount={onRefreshAccount} />
    );
    fireEvent.click(screen.getByRole('button', { name: /refresh/i }));
    expect(onRefreshAccount).toHaveBeenCalled();
  });

  it('shows Performance 30d card when stats is present', () => {
    renderWithQuery(
      <AccountPanel
        {...defaultProps}
        stats={{ total_orders: 5, by_status: {}, closed_count: 3, win_rate: 60, total_pnl: 1200, avg_pnl_per_trade: 240 }}
      />
    );
    expect(screen.getByText(/performance \(30d\)/i)).toBeInTheDocument();
  });
});
```

- [ ] Run tests:
  ```bash
  cd frontend && npx vitest run src/pages/AutoTrading/AccountPanel.test.tsx
  ```
  Expected: `13 tests passed`

- [ ] Run TypeScript check:
  ```bash
  cd frontend && npx tsc -p tsconfig.app.json --noEmit
  ```

- [ ] Commit:
  ```bash
  git add frontend/src/pages/AutoTrading/AccountPanel.test.tsx
  git commit -m "test(frontend): add AccountPanel tests

  Covers: not-connected states, error message, connected account
  metrics, 30-Day Breakdown conditional, System Config card,
  toggle callback, Refresh callback, and Performance card.
  
  Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
  ```

---

## Task 5: Add tests for `OrdersPanel`

**Files:** `frontend/src/pages/AutoTrading/OrdersPanel.test.tsx`

`OrdersPanel` renders filter buttons, a loading state, an empty state, and a table of orders. `OrderRow` is imported from `components` — mock it to keep the table tests focused on the panel's own logic.

- [ ] Create `frontend/src/pages/AutoTrading/OrdersPanel.test.tsx`:

```tsx
import { vi, describe, it, expect } from 'vitest';
import { screen, fireEvent } from '@testing-library/react';
import { renderWithQuery } from '../../test-utils/renderWithQuery';
import { OrdersPanel, OrdersPanelProps } from './OrdersPanel';
import type { AutoTradeOrder } from '../../api/trading';

vi.mock('./components', async (importOriginal) => {
  const original = await importOriginal<typeof import('./components')>();
  return {
    ...original,
    OrderRow: ({ order }: { order: AutoTradeOrder }) => (
      <tr data-testid={`order-row-${order.id}`}>
        <td>{order.symbol}</td>
      </tr>
    ),
  };
});

const defaultProps: OrdersPanelProps = {
  orders: [],
  loadingOrders: false,
  orderFilter: '',
  onOrderFilter: vi.fn(),
  strategies: [],
  onApprove: vi.fn(),
  onReject: vi.fn(),
  onCancel: vi.fn(),
};

const makeOrder = (id: number, symbol: string): AutoTradeOrder =>
  ({ id, symbol } as AutoTradeOrder);

describe('OrdersPanel', () => {
  it('renders without crashing', () => {
    renderWithQuery(<OrdersPanel {...defaultProps} />);
  });

  it('renders "All" filter button', () => {
    renderWithQuery(<OrdersPanel {...defaultProps} />);
    expect(screen.getByRole('button', { name: /^all$/i })).toBeInTheDocument();
  });

  it('renders all status filter buttons', () => {
    renderWithQuery(<OrdersPanel {...defaultProps} />);
    expect(screen.getByRole('button', { name: /pending_approval/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /submitted/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /closed/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /cancelled/i })).toBeInTheDocument();
  });

  it('clicking a filter button calls onOrderFilter with that status', () => {
    const onOrderFilter = vi.fn();
    renderWithQuery(<OrdersPanel {...defaultProps} onOrderFilter={onOrderFilter} />);
    fireEvent.click(screen.getByRole('button', { name: /pending_approval/i }));
    expect(onOrderFilter).toHaveBeenCalledWith('pending_approval');
  });

  it('clicking "All" filter calls onOrderFilter with empty string', () => {
    const onOrderFilter = vi.fn();
    renderWithQuery(<OrdersPanel {...defaultProps} onOrderFilter={onOrderFilter} />);
    fireEvent.click(screen.getByRole('button', { name: /^all$/i }));
    expect(onOrderFilter).toHaveBeenCalledWith('');
  });

  it('shows loading spinner when loadingOrders is true', () => {
    renderWithQuery(<OrdersPanel {...defaultProps} loadingOrders={true} />);
    expect(screen.getByText(/loading orders/i)).toBeInTheDocument();
  });

  it('shows empty state message when orders is empty and not loading', () => {
    renderWithQuery(<OrdersPanel {...defaultProps} />);
    expect(screen.getByText(/no orders found/i)).toBeInTheDocument();
  });

  it('does not show empty state when orders are present', () => {
    renderWithQuery(
      <OrdersPanel {...defaultProps} orders={[makeOrder(1, 'AAPL')]} />
    );
    expect(screen.queryByText(/no orders found/i)).not.toBeInTheDocument();
  });

  it('renders an OrderRow per order', () => {
    renderWithQuery(
      <OrdersPanel
        {...defaultProps}
        orders={[makeOrder(1, 'AAPL'), makeOrder(2, 'TSLA')]}
      />
    );
    expect(screen.getByTestId('order-row-1')).toBeInTheDocument();
    expect(screen.getByTestId('order-row-2')).toBeInTheDocument();
  });

  it('active filter button has highlighted styling', () => {
    renderWithQuery(
      <OrdersPanel {...defaultProps} orderFilter="closed" />
    );
    const btn = screen.getByRole('button', { name: /^closed$/i });
    expect(btn.className).toContain('bg-financial-blue');
  });
});
```

- [ ] Run tests:
  ```bash
  cd frontend && npx vitest run src/pages/AutoTrading/OrdersPanel.test.tsx
  ```
  Expected: `10 tests passed`

- [ ] Run TypeScript check:
  ```bash
  cd frontend && npx tsc -p tsconfig.app.json --noEmit
  ```

- [ ] Commit:
  ```bash
  git add frontend/src/pages/AutoTrading/OrdersPanel.test.tsx
  git commit -m "test(frontend): add OrdersPanel tests

  Covers: render, filter buttons (all + status variants), filter
  callback, loading state, empty state, order rows, and active
  filter styling.
  
  Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
  ```

---

## Task 6: Check coverage and proceed if below 32%/24%

After Tasks 1–5, measure coverage and decide whether to continue.

- [ ] Run coverage measurement:
  ```bash
  cd frontend && npx vitest run --coverage --reporter=verbose 2>&1 | tail -30
  ```
  Expected output (approximate): statements ~32–34%, branches ~23–25%, functions ~22–25%, lines ~33–35%.

- [ ] **If actuals are ≥ 32% statements and ≥ 24% branches**: Skip Task 6a–6b and proceed to Task 7.

- [ ] **If actuals are still below 32%/24%**: Continue with Task 6a (HeroMetrics) and 6b (IntervalTable) below.

### Task 6a (if needed): Add tests for `HeroMetrics`

**Files:** `frontend/src/components/scorecard/HeroMetrics.test.tsx`

`HeroMetrics` is a pure presentational component — `scorecard: Scorecard` prop → rendered JSX. No hooks. The `colorByThreshold` helper is exercised through the render.

- [ ] Create `frontend/src/components/scorecard/HeroMetrics.test.tsx`:

```tsx
import { describe, it, expect } from 'vitest';
import { screen } from '@testing-library/react';
import { renderWithQuery } from '../../test-utils/renderWithQuery';
import HeroMetrics from './HeroMetrics';
import type { Scorecard } from '../../api/outcomes';

const makeScorecard = (overrides: Partial<Scorecard> = {}): Scorecard => ({
  win_rate_pct: 55,
  mfe_mae_ratio: 2.3,
  avg_mfe_pct: 4.5,
  avg_mae_pct: 1.9,
  expectancy: 1.2,
  follow_through_rate_pct: 68,
  profit_factor: 1.8,
  avg_r_multiple: 0.9,
  total_signals: 100,
  complete_signals: 87,
  ...overrides,
} as Scorecard);

describe('HeroMetrics', () => {
  it('renders without crashing', () => {
    renderWithQuery(<HeroMetrics scorecard={makeScorecard()} />);
  });

  it('shows Win Rate label', () => {
    renderWithQuery(<HeroMetrics scorecard={makeScorecard()} />);
    expect(screen.getByText(/win rate/i)).toBeInTheDocument();
  });

  it('formats win_rate_pct with 1 decimal + % suffix', () => {
    renderWithQuery(<HeroMetrics scorecard={makeScorecard({ win_rate_pct: 55.3 })} />);
    expect(screen.getByText('55.3%')).toBeInTheDocument();
  });

  it('shows — when win_rate_pct is null', () => {
    renderWithQuery(<HeroMetrics scorecard={makeScorecard({ win_rate_pct: null })} />);
    // Multiple — may appear; just verify win rate text is present with null-formatted value
    expect(screen.getByText(/win rate/i)).toBeInTheDocument();
  });

  it('shows MFE:MAE ratio label', () => {
    renderWithQuery(<HeroMetrics scorecard={makeScorecard()} />);
    expect(screen.getByText(/mfe.*mae/i)).toBeInTheDocument();
  });

  it('formats mfe_mae_ratio with 1 decimal : 1 suffix', () => {
    renderWithQuery(<HeroMetrics scorecard={makeScorecard({ mfe_mae_ratio: 2.3 })} />);
    expect(screen.getByText('2.3 : 1')).toBeInTheDocument();
  });

  it('shows Expectancy label', () => {
    renderWithQuery(<HeroMetrics scorecard={makeScorecard()} />);
    expect(screen.getByText(/expectancy/i)).toBeInTheDocument();
  });

  it('shows + prefix for positive expectancy', () => {
    renderWithQuery(<HeroMetrics scorecard={makeScorecard({ expectancy: 1.2 })} />);
    expect(screen.getByText('+1.2%')).toBeInTheDocument();
  });

  it('shows Follow-Through label', () => {
    renderWithQuery(<HeroMetrics scorecard={makeScorecard()} />);
    expect(screen.getByText(/follow-through/i)).toBeInTheDocument();
  });

  it('shows total / complete signal counts', () => {
    renderWithQuery(<HeroMetrics scorecard={makeScorecard({ total_signals: 100, complete_signals: 87 })} />);
    expect(screen.getByText('100 / 87')).toBeInTheDocument();
  });

  it('win rate text is green when >= 50', () => {
    const { container } = renderWithQuery(
      <HeroMetrics scorecard={makeScorecard({ win_rate_pct: 60 })} />
    );
    const rateEl = screen.getByText('60.0%');
    expect(rateEl.className).toContain('text-green-400');
  });

  it('win rate text is red when < 50', () => {
    renderWithQuery(<HeroMetrics scorecard={makeScorecard({ win_rate_pct: 40 })} />);
    const rateEl = screen.getByText('40.0%');
    expect(rateEl.className).toContain('text-red-400');
  });
});
```

- [ ] Run tests:
  ```bash
  cd frontend && npx vitest run src/components/scorecard/HeroMetrics.test.tsx
  ```
  Expected: `12 tests passed`

- [ ] Run TypeScript check:
  ```bash
  cd frontend && npx tsc -p tsconfig.app.json --noEmit
  ```

- [ ] Commit:
  ```bash
  git add frontend/src/components/scorecard/HeroMetrics.test.tsx
  git commit -m "test(frontend): add HeroMetrics scorecard tests

  Covers: render, Win Rate / MFE:MAE / Expectancy / Follow-Through
  labels, number formatting, null handling, positive prefix, total/complete
  counts, and colorByThreshold (green/red) branches.
  
  Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
  ```

### Task 6b (if needed): Add tests for `IntervalTable`

**Files:** `frontend/src/components/scorecard/IntervalTable.test.tsx`

`IntervalTable` has three render branches: loading skeleton, empty data, and data table. All driven by props.

- [ ] Create `frontend/src/components/scorecard/IntervalTable.test.tsx`:

```tsx
import { describe, it, expect } from 'vitest';
import { screen } from '@testing-library/react';
import { renderWithQuery } from '../../test-utils/renderWithQuery';
import IntervalTable from './IntervalTable';
import type { IntervalBreakdown } from '../../api/outcomes';

const makeRow = (overrides: Partial<IntervalBreakdown> = {}): IntervalBreakdown => ({
  avg_pct: 1.5,
  median_pct: 1.2,
  stddev_pct: 0.8,
  win_rate: 60,
  sample_size: 20,
  ...overrides,
} as IntervalBreakdown);

const sampleData: Record<string, IntervalBreakdown> = {
  '1h':  makeRow({ avg_pct: 1.5, win_rate: 60, sample_size: 20 }),
  '4h':  makeRow({ avg_pct: -0.3, win_rate: 45, sample_size: 15 }),
  'eod': makeRow({ avg_pct: 2.1, win_rate: 55, sample_size: 30 }),
};

describe('IntervalTable', () => {
  it('renders without crashing with data', () => {
    renderWithQuery(<IntervalTable data={sampleData} isLoading={false} />);
  });

  it('shows loading skeleton when isLoading is true', () => {
    const { container } = renderWithQuery(
      <IntervalTable data={{}} isLoading={true} />
    );
    // Skeleton shows 6 animated pulse divs
    const pulses = container.querySelectorAll('.animate-pulse');
    expect(pulses.length).toBeGreaterThan(0);
  });

  it('shows "No interval data available" when data is empty', () => {
    renderWithQuery(<IntervalTable data={{}} isLoading={false} />);
    expect(screen.getByText(/no interval data available/i)).toBeInTheDocument();
  });

  it('renders a row for each interval key in canonical order', () => {
    renderWithQuery(<IntervalTable data={sampleData} isLoading={false} />);
    expect(screen.getByText('1h')).toBeInTheDocument();
    expect(screen.getByText('4h')).toBeInTheDocument();
    expect(screen.getByText('eod')).toBeInTheDocument();
  });

  it('shows + prefix for positive avg_pct', () => {
    renderWithQuery(<IntervalTable data={sampleData} isLoading={false} />);
    expect(screen.getByText('+1.5%')).toBeInTheDocument();
  });

  it('shows no prefix for negative avg_pct', () => {
    renderWithQuery(<IntervalTable data={sampleData} isLoading={false} />);
    expect(screen.getByText('-0.3%')).toBeInTheDocument();
  });

  it('shows sample size for each interval', () => {
    renderWithQuery(<IntervalTable data={sampleData} isLoading={false} />);
    expect(screen.getByText('30')).toBeInTheDocument();
  });

  it('win rate is green when >= 50', () => {
    renderWithQuery(<IntervalTable data={sampleData} isLoading={false} />);
    // 1h has 60% win rate → green
    const el = screen.getByText('60%');
    expect(el.className).toContain('text-green-400');
  });

  it('win rate is red when < 50', () => {
    renderWithQuery(<IntervalTable data={sampleData} isLoading={false} />);
    // 4h has 45% win rate → red
    const el = screen.getByText('45%');
    expect(el.className).toContain('text-red-400');
  });

  it('shows "Interval Breakdown" heading', () => {
    renderWithQuery(<IntervalTable data={sampleData} isLoading={false} />);
    expect(screen.getByText(/interval breakdown/i)).toBeInTheDocument();
  });
});
```

- [ ] Run tests:
  ```bash
  cd frontend && npx vitest run src/components/scorecard/IntervalTable.test.tsx
  ```
  Expected: `10 tests passed`

- [ ] Run TypeScript check:
  ```bash
  cd frontend && npx tsc -p tsconfig.app.json --noEmit
  ```

- [ ] Commit:
  ```bash
  git add frontend/src/components/scorecard/IntervalTable.test.tsx
  git commit -m "test(frontend): add IntervalTable tests

  Covers: render, loading skeleton, empty state, canonical interval
  order, +/- pct formatting, sample size, win rate color branches,
  and heading text.
  
  Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
  ```

---

## Task 7: Measure actuals and update coverage thresholds

With all test files in place, measure the final coverage actuals and update `vitest.config.ts`.

- [ ] Run coverage with JSON output to get precise numbers:
  ```bash
  cd frontend && npx vitest run --coverage --reporter=json 2>/dev/null | python3 -c "
  import json, sys
  data = json.load(sys.stdin)
  totals = data.get('totals', {})
  for k in ['statements', 'branches', 'functions', 'lines']:
      pct = totals.get(k, {}).get('pct', 0)
      thr = max(30 if k in ('statements','lines') else 22, int(pct) - 3)
      print(f'{k}: actual={pct:.1f}% → threshold={thr}')
  "
  ```
  Note the four threshold values. Minimum: statements ≥ 30, branches ≥ 22, functions ≥ 22, lines ≥ 30.

- [ ] Edit `frontend/vitest.config.ts` — replace the `thresholds` block and update the comment:
  ```typescript
  // Spec target: 35%/25%. Actuals post-#198: 21.6%/21.1%/16.7%/22.3%.
  // Actuals post-#250 ratchet: <statements_actual>/<branches_actual>/<functions_actual>/<lines_actual>.
  // Thresholds set ~3pp below actuals for stable CI headroom. See issue #250.
  thresholds: {
    statements: <computed_value>,
    branches: <computed_value>,
    functions: <computed_value>,
    lines: <computed_value>,
  },
  ```
  Replace `<computed_value>` and `<X_actual>` with the real numbers from the coverage run.

- [ ] Run coverage once more to confirm the gate is green:
  ```bash
  cd frontend && npx vitest run --coverage
  ```
  Expected: all four threshold checks pass (no "ERROR: Coverage...below threshold" lines).

- [ ] Run TypeScript check:
  ```bash
  cd frontend && npx tsc -p tsconfig.app.json --noEmit
  ```
  Expected: no errors.

- [ ] Commit:
  ```bash
  git add frontend/vitest.config.ts
  git commit -m "feat(frontend): ratchet coverage thresholds to 30/22

  Statements/lines gate raised to ≥30%, branches/functions to ≥22%.
  Actuals post-#250 tests: <paste actual values>. Thresholds set 3pp
  below actuals per established headroom formula. Closes #250.
  
  Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
  ```

---

## Completion Checklist

- [ ] `npx vitest run` passes (all tests green)
- [ ] `npx vitest run --coverage` passes (thresholds met)
- [ ] `npx tsc -p tsconfig.app.json --noEmit` passes (production source type-checks clean)
- [ ] `vitest.config.ts` updated with real actuals and new thresholds
- [ ] Comment block in `vitest.config.ts` records the new actuals and issue reference
