# Frontend Page Decomposition — Implementation Plan

**Goal**: Decompose five monolithic frontend pages (4,022 LOC total) into co-located panel directories and standalone hooks, bringing every file under 300 LOC with no behavior changes.

**Issue**: [#74 — refactor: decompose monolithic frontend page components](https://github.com/omniscient/markethawk/issues/74)
**Date**: 2026-05-26
**Branch**: refine/issue-74-refactor--decompose-monolithic-frontend-

## Architecture

Panel files are page-private (under `pages/PageName/`). Hooks go in `frontend/src/hooks/`. Existing shared components in `components/` are untouched. The page shell (`index.tsx`) owns React Query calls, layout, and props passed to panels. Panels receive data and callbacks via props — no direct API calls.

TypeScript resolves `import Scanner from './pages/Scanner'` to `pages/Scanner/index.tsx` automatically — no router or tsconfig changes needed.

## File Structure

| File | ~LOC | Responsibility |
|------|------|----------------|
| `pages/Scanner/index.tsx` | ~120 | Shell: layout, queries, WS orchestration |
| `pages/Scanner/ScanConfigPanel.tsx` | ~150 | Config selector, date range, scan trigger |
| `pages/Scanner/LiveProgressPanel.tsx` | ~100 | WS progress + status display |
| `pages/Scanner/ResultsPanel.tsx` | ~200 | Results table, sorting, review controls |
| `hooks/useScannerState.ts` | ~80 | Scanner state + localStorage + WS ref |
| `pages/AutoTrading/index.tsx` | ~120 | Shell |
| `pages/AutoTrading/StrategyPanel.tsx` | ~200 | Strategy list + toggle/edit/delete |
| `pages/AutoTrading/OrdersPanel.tsx` | ~150 | Orders table + filter |
| `pages/AutoTrading/AccountPanel.tsx` | ~100 | Account metrics display |
| `pages/AutoTrading/ConfigPanel.tsx` | ~150 | Strategy create/edit modal form |
| `pages/AutoTrading/components.tsx` | ~150 | Page-private: StatusBadge, StrategyRow, StratStat, OrderRow, AccountMetric, StatRow, NumberField, ToggleField |
| `pages/Alerts/index.tsx` | ~100 | Shell |
| `pages/Alerts/AlertRulesPanel.tsx` | ~200 | Rule list + CRUD form |
| `pages/Alerts/AlertLogsPanel.tsx` | ~150 | Alert history |
| `pages/Alerts/ChannelConfigPanel.tsx` | ~200 | Push subscription lifecycle |
| `pages/StockDetailPage/index.tsx` | ~100 | Shell |
| `pages/StockDetailPage/ChartPanel.tsx` | ~200 | Lightweight Charts OHLCV + controls |
| `pages/StockDetailPage/MetadataPanel.tsx` | ~150 | Ticker info + news |
| `pages/StockDetailPage/ScannerHistoryPanel.tsx` | ~150 | Event list + clear history |
| `pages/ActiveWatchlist/index.tsx` | ~100 | Shell |
| `pages/ActiveWatchlist/WatchlistTable.tsx` | ~200 | Table rows + add form |
| `pages/ActiveWatchlist/AlertBadges.tsx` | ~80 | AlertBadge component |
| `hooks/useWatchlistLive.ts` | ~200 | Extracted WS live-prices hook |

## Tech Stack

- **Framework**: React 18 + TypeScript + Vite
- **State**: React Query (server), `useState` (local UI)
- **Styling**: Tailwind CSS
- **Type checking**: `npx tsc --noEmit` — must pass after every per-page extraction
- **Behavior verification**: Browser smoke test after each page — load the page, confirm primary interactions

---

## Tasks

### Phase 1: Scanner (830 LOC → ~5 files)

#### Task 1: Extract `useScannerState` hook

**Files:**
- Create: `frontend/src/hooks/useScannerState.ts`

**Steps:**

1. Establish green baseline before touching anything:
   ```bash
   cd /workspace/markethawk/frontend && npx tsc --noEmit
   # Expected: zero errors
   ```

2. Create `frontend/src/hooks/useScannerState.ts`. The types, constants, and helpers below are taken verbatim from Scanner.tsx lines 35–96. Copy from source rather than re-typing to avoid transcription errors:

   ```typescript
   // frontend/src/hooks/useScannerState.ts
   import { useState, useRef, useEffect } from 'react';

   // ── Constants (the shell needs these for finishScan / re-attach logic) ────────
   export const ACTIVE_SCAN_LS_KEY = 'markethawk.activeScan';
   export const SELECTION_LS_KEY   = 'markethawk.scanner.selection';

   // ── Types (verbatim from Scanner.tsx) ────────────────────────────────────────
   export interface PersistedSelection {
     scanner_type?: string;
     universe_id?: number | null;
   }

   export interface ActiveScanRef {
     scan_id: string;
     task_id: string;
     scanner_type: string;
     universe_id: number;
     start_date: string;
     end_date: string;
     started_at: string;
   }

   export interface LiveProgress {
     day_index: number;
     total_days: number;
     total_tickers: number;
     estimated_pairs: number;
     evaluated: number;
     no_data: number;
     no_prior_close: number;
     no_baseline: number;
     fired_pre: number;
     fired_post: number;
     errors: number;
     events_detected: number;
     last_day?: string;
   }

   export const EMPTY_PROGRESS: LiveProgress = {
     day_index: 0, total_days: 0, total_tickers: 0, estimated_pairs: 0,
     evaluated: 0, no_data: 0, no_prior_close: 0, no_baseline: 0,
     fired_pre: 0, fired_post: 0, errors: 0, events_detected: 0,
   };

   // ── Helpers (verbatim from Scanner.tsx) ──────────────────────────────────────
   export const lastCompletedWeekday = (): string => {
     const d = new Date();
     d.setDate(d.getDate() - 1);
     while (d.getDay() === 0 || d.getDay() === 6) d.setDate(d.getDate() - 1);
     return d.toISOString().slice(0, 10);
   };

   export const todayIso = (): string => new Date().toISOString().slice(0, 10);

   export const loadPersistedSelection = (): PersistedSelection => {
     try {
       const raw = localStorage.getItem(SELECTION_LS_KEY);
       if (!raw) return {};
       const parsed = JSON.parse(raw);
       return parsed && typeof parsed === 'object' ? parsed : {};
     } catch {
       return {};
     }
   };

   // ── Hook ─────────────────────────────────────────────────────────────────────
   export function useScannerState() {
     // useRef so the persisted value is read once on mount, not re-read on every render.
     const persisted = useRef<PersistedSelection>(loadPersistedSelection()).current;

     const [isScanning, setIsScanning] = useState(false);
     const [selectedConfig, setSelectedConfig] = useState<string>(
       persisted.scanner_type || 'pre_market_volume_spike',
     );
     const [selectedUniverse, setSelectedUniverse] = useState<number | null>(
       typeof persisted.universe_id === 'number' ? persisted.universe_id : null,
     );
     // Dates are NOT persisted — always initialise to the last completed weekday.
     const [scanStartDate, setScanStartDate] = useState<string>(lastCompletedWeekday());
     const [scanEndDate, setScanEndDate] = useState<string>(lastCompletedWeekday());
     const [scanResults, setScanResults] = useState<any>(null);
     const [scanError, setScanError] = useState<string | null>(null);
     const [sortBy, setSortBy] = useState<string>('signal_quality_score');
     const [sortOrder, setSortOrder] = useState<'asc' | 'desc'>('desc');
     const [activeScan, setActiveScan] = useState<ActiveScanRef | null>(null);
     const [liveProgress, setLiveProgress] = useState<LiveProgress>(EMPTY_PROGRESS);
     const wsRef = useRef<WebSocket | null>(null);

     // Persist scanner_type + universe_id only (not dates) on every selection change.
     useEffect(() => {
       try {
         localStorage.setItem(
           SELECTION_LS_KEY,
           JSON.stringify({ scanner_type: selectedConfig, universe_id: selectedUniverse }),
         );
       } catch { /* ignore quota errors */ }
     }, [selectedConfig, selectedUniverse]);

     return {
       isScanning, setIsScanning,
       selectedConfig, setSelectedConfig,
       selectedUniverse, setSelectedUniverse,
       scanStartDate, setScanStartDate,
       scanEndDate, setScanEndDate,
       scanResults, setScanResults,
       scanError, setScanError,
       sortBy, setSortBy,
       sortOrder, setSortOrder,
       activeScan, setActiveScan,
       liveProgress, setLiveProgress,
       wsRef,
     };
   }
   ```
   The shell (`Scanner/index.tsx`) must `import { ACTIVE_SCAN_LS_KEY, EMPTY_PROGRESS, ActiveScanRef, LiveProgress } from '../../hooks/useScannerState'` for use inside `finishScan`, `handleWsMessage`, and the re-attach effect — copy those functions verbatim from Scanner.tsx.

3. Verify tsc (new file compiles, nothing broken):
   ```bash
   npx tsc --noEmit
   # Expected: no errors
   ```

4. Commit:
   ```bash
   git add frontend/src/hooks/useScannerState.ts
   git commit -m "refactor(frontend): extract useScannerState hook from Scanner.tsx"
   ```

---

#### Task 2: Extract `ScanConfigPanel`

**Files:**
- Create: `frontend/src/pages/Scanner/ScanConfigPanel.tsx`

**Steps:**

1. Create directory:
   ```bash
   mkdir -p /workspace/markethawk/frontend/src/pages/Scanner
   ```

2. Identify the config/date-range/scan-trigger section in Scanner.tsx (the control sidebar). Create `frontend/src/pages/Scanner/ScanConfigPanel.tsx`. The `DateRangePresets` inline component (lines 792–829 of Scanner.tsx) moves here since it is only used in this panel:

   ```typescript
   // frontend/src/pages/Scanner/ScanConfigPanel.tsx
   import React from 'react';
   // Copy every import from Scanner.tsx that is referenced only in this section.
   // Typically: Card, Button, ScannerConfig (shared component), plus type imports.

   interface DateRangePresetsProps {
     onSelect: (start: string, end: string) => void;
     disabled?: boolean;  // the real component has this prop (Scanner.tsx line 793)
   }

   function DateRangePresets({ onSelect, disabled }: DateRangePresetsProps) {
     // Copy lines 792-829 from Scanner.tsx verbatim.
   }

   export interface ScanConfigPanelProps {
     // Replace `any` with the actual types imported in Scanner.tsx.
     configs: any[];
     loadingConfigs: boolean;
     universes: any[];
     loadingUniverses: boolean;
     selectedConfig: string;
     onSelectConfig: (v: string) => void;
     selectedUniverse: number | null;
     onSelectUniverse: (v: number | null) => void;
     scanStartDate: string;
     onScanStartDate: (v: string) => void;
     scanEndDate: string;
     onScanEndDate: (v: string) => void;
     isScanning: boolean;
     onRunScan: () => void;
     onCancelScan: () => void;  // the cancel button is in the header alongside run
     statusBlock: any;          // Scan Status sidebar card (right column of the grid)
     scanHistory: any[];
     loadingHistory: boolean;
     scanError: string | null;
     onDismissError: () => void;
   }

   export function ScanConfigPanel({
     configs, loadingConfigs, universes, loadingUniverses,
     selectedConfig, onSelectConfig, selectedUniverse, onSelectUniverse,
     scanStartDate, onScanStartDate, scanEndDate, onScanEndDate,
     isScanning, onRunScan, onCancelScan, statusBlock,
     scanHistory, loadingHistory, scanError, onDismissError,
   }: ScanConfigPanelProps) {
     // Copy the following from Scanner.tsx verbatim:
     // 1. Header div (lines 402-468): title, date inputs, DateRangePresets,
     //    conditional Cancel/Run button — passes onCancelScan / onRunScan
     // 2. Error card (lines 475-491): rendered when scanError is set
     // 3. Config grid (lines 494-647): left col = ScannerConfig card,
     //    right col = Scan Status card (uses statusBlock prop)
     // 4. Scan history card (lines 668-708)
   }
   ```

3. Verify tsc:
   ```bash
   npx tsc --noEmit
   ```

4. Commit:
   ```bash
   git add frontend/src/pages/Scanner/ScanConfigPanel.tsx
   git commit -m "refactor(frontend): extract ScanConfigPanel from Scanner.tsx"
   ```

---

#### Task 3: Extract `LiveProgressPanel`

**Files:**
- Create: `frontend/src/pages/Scanner/LiveProgressPanel.tsx`

**Steps:**

1. Create `frontend/src/pages/Scanner/LiveProgressPanel.tsx`. The `ProgressChip` (lines 774–788) and `LiveProgressCard` (lines 718–772) inline components of Scanner.tsx move here since they are only used in this panel:

   ```typescript
   // frontend/src/pages/Scanner/LiveProgressPanel.tsx
   import React from 'react';
   import type { ActiveScanRef, LiveProgress } from '../../hooks/useScannerState';
   // Copy any other imports from Scanner.tsx used in this section.

   interface ProgressChipProps {
     // Copy the exact props from ProgressChip in Scanner.tsx.
   }

   function ProgressChip(props: ProgressChipProps) {
     // Copy lines 774-788 from Scanner.tsx verbatim.
   }

   interface LiveProgressCardProps {
     // Copy the exact props from LiveProgressCard in Scanner.tsx.
   }

   function LiveProgressCard(props: LiveProgressCardProps) {
     // Copy lines 718-772 from Scanner.tsx verbatim.
     // Uses ProgressChip internally.
   }

   export interface LiveProgressPanelProps {
     isScanning: boolean;
     activeScan: ActiveScanRef | null;
     progress: LiveProgress;
   }

   export function LiveProgressPanel({ isScanning, activeScan, progress }: LiveProgressPanelProps) {
     // Copy lines 471-473 from Scanner.tsx:
     //   {isScanning && activeScan && (
     //     <LiveProgressCard scan={activeScan} progress={progress} />
     //   )}
     // The cancel button lives in ScanConfigPanel (it is in the page header, not here).
     // statusBlock is also in ScanConfigPanel (the Scan Status sidebar card).
   }
   ```

2. Verify tsc:
   ```bash
   npx tsc --noEmit
   ```

3. Commit:
   ```bash
   git add frontend/src/pages/Scanner/LiveProgressPanel.tsx
   git commit -m "refactor(frontend): extract LiveProgressPanel from Scanner.tsx"
   ```

---

#### Task 4: Extract `ResultsPanel`

**Files:**
- Create: `frontend/src/pages/Scanner/ResultsPanel.tsx`

**Steps:**

1. Create `frontend/src/pages/Scanner/ResultsPanel.tsx`. This wraps the existing shared `ScannerResults` and `SignalReviewStats` components plus any sorting controls:

   ```typescript
   // frontend/src/pages/Scanner/ResultsPanel.tsx
   import React from 'react';
   import ScannerResults from '../../components/ScannerResults';
   import SignalReviewStats from '../../components/SignalReviewStats';
   // Copy remaining imports from Scanner.tsx used in this section.

   export interface ResultsPanelProps {
     scanResults: any; // the object shaped { scan_id, events: [], ... } from Scanner.tsx
     sortBy: string;
     sortOrder: 'asc' | 'desc';
     // Single-argument to match ScannerResults' onSort?: (column: string) => void signature.
     // The shell builds the toggle logic: if column === sortBy, flip order; else set new column.
     onSort: (column: string) => void;
   }

   export function ResultsPanel({ scanResults, sortBy, sortOrder, onSort }: ResultsPanelProps) {
     // Copy the following from Scanner.tsx:
     // 1. Lines 650-666: ScannerResults conditional block
     // 2. Line 710: <SignalReviewStats />
     // Note: scan history card (lines 668-708) lives in ScanConfigPanel alongside the
     // Scanner Configuration grid, not here.
   }
   ```

2. Verify tsc:
   ```bash
   npx tsc --noEmit
   ```

3. Commit:
   ```bash
   git add frontend/src/pages/Scanner/ResultsPanel.tsx
   git commit -m "refactor(frontend): extract ResultsPanel from Scanner.tsx"
   ```

---

#### Task 5: Create `Scanner/index.tsx` shell — delete `Scanner.tsx` — verify

**Files:**
- Create: `frontend/src/pages/Scanner/index.tsx`
- Delete: `frontend/src/pages/Scanner.tsx`

**Steps:**

1. Create `frontend/src/pages/Scanner/index.tsx`. The shell retains:
   - All React Query calls (`fetchScannerConfigs`, `fetchStockUniverses`, `fetchScannerHistory`, `fetchScanStatusBlock`, `fetchScannerResults`, `runScanner` mutation)
   - `useScannerState()` call
   - WebSocket lifecycle functions: `createScanRunWebSocket`, `handleWsMessage`, `attachWebSocket`
   - Re-attach useEffect (line ~351–377 of Scanner.tsx)
   - Auto-load useEffect (line ~156–169)
   - Cleanup useEffect (line ~390–397)

   ```typescript
   // frontend/src/pages/Scanner/index.tsx
   import React, { useEffect, useCallback, useRef } from 'react';
   import { useScannerState } from '../../hooks/useScannerState';
   import { ScanConfigPanel } from './ScanConfigPanel';
   import { LiveProgressPanel } from './LiveProgressPanel';
   import { ResultsPanel } from './ResultsPanel';
   // Copy all remaining imports from Scanner.tsx (API functions, query hooks, etc.)

   export default function Scanner() {
     const state = useScannerState();
     const queryClient = useQueryClient();

     // Copy all useQuery / useMutation declarations from Scanner.tsx, replacing
     // direct state references with state.xxx (e.g. selectedConfig → state.selectedConfig).

     // Copy finishScan, handleWsMessage, attachWebSocket, handleRunScanner,
     // handleCancelScanner from Scanner.tsx verbatim. Update references:
     //   wsRef → state.wsRef
     //   setActiveScan → state.setActiveScan  etc.
     // Import ACTIVE_SCAN_LS_KEY and EMPTY_PROGRESS from '../../hooks/useScannerState'.

     // Copy the three useEffects (re-attach, auto-load existingResults, cleanup).

     const handleSort = (column: string) => {
       if (column === state.sortBy) {
         state.setSortOrder(state.sortOrder === 'asc' ? 'desc' : 'asc');
       } else {
         state.setSortBy(column);
         state.setSortOrder('desc');
       }
     };

     return (
       <div className="space-y-6 animate-fade-in">
         <ScanConfigPanel
           configs={configs ?? []}
           loadingConfigs={loadingConfigs}
           universes={universes ?? []}
           loadingUniverses={loadingUniverses}
           selectedConfig={state.selectedConfig}
           onSelectConfig={state.setSelectedConfig}
           selectedUniverse={state.selectedUniverse}
           onSelectUniverse={state.setSelectedUniverse}
           scanStartDate={state.scanStartDate}
           onScanStartDate={state.setScanStartDate}
           scanEndDate={state.scanEndDate}
           onScanEndDate={state.setScanEndDate}
           isScanning={state.isScanning}
           onRunScan={handleRunScanner}
           onCancelScan={handleCancelScanner}
           statusBlock={statusBlock}
           scanHistory={scanHistory ?? []}
           loadingHistory={loadingHistory}
           scanError={state.scanError}
           onDismissError={() => state.setScanError(null)}
         />
         <LiveProgressPanel
           isScanning={state.isScanning}
           activeScan={state.activeScan}
           progress={state.liveProgress}
         />
         <ResultsPanel
           scanResults={state.scanResults}
           sortBy={state.sortBy}
           sortOrder={state.sortOrder}
           onSort={handleSort}
         />
       </div>
     );
   }
   ```

2. Delete the original flat file:
   ```bash
   rm /workspace/markethawk/frontend/src/pages/Scanner.tsx
   ```

3. Verify TypeScript resolves the directory index:
   ```bash
   npx tsc --noEmit
   # Expected: zero errors — import './pages/Scanner' resolves to Scanner/index.tsx
   ```

4. Browser smoke test — open http://localhost:3333/scanner:
   - Config dropdown populates from API
   - Date pickers work; preset buttons update the range
   - Scan button is enabled; clicking it triggers a scan and the progress panel appears
   - Previous scan results load on page open
   - No console errors

5. Commit:
   ```bash
   git add -A frontend/src/pages/Scanner/
   git rm frontend/src/pages/Scanner.tsx
   git commit -m "refactor(frontend): decompose Scanner.tsx into Scanner/ directory"
   ```

---

### Phase 2: AutoTrading (1,003 LOC → ~6 files)

#### Task 6: Create `AutoTrading/components.tsx`

**Files:**
- Create: `frontend/src/pages/AutoTrading/components.tsx`

**Steps:**

1. Create directory:
   ```bash
   mkdir -p /workspace/markethawk/frontend/src/pages/AutoTrading
   ```

2. Create `frontend/src/pages/AutoTrading/components.tsx`. Extract all inline sub-components from AutoTrading.tsx (lines ~800–1001). The list from the codebase:
   - `StrategyRow` (lines 800–855, ~55 LOC)
   - `StratStat` (lines 857–862, ~5 LOC)
   - `OrderRow` (lines 864–933, ~69 LOC)
   - `AccountMetric` (lines 935–940, ~5 LOC)
   - `StatRow` (lines 942–949, ~7 LOC)
   - `NumberField` (lines 953–981, ~28 LOC)
   - `ToggleField` (lines 983–1001, ~18 LOC)
   - `StatusBadge` — check AutoTrading.tsx for this name; include if present

   ```typescript
   // frontend/src/pages/AutoTrading/components.tsx
   import React from 'react';
   // Copy every import from AutoTrading.tsx required by the items below.
   // Specifically: lucide-react icons, Card, Button, Modal, and the
   // TradingStrategy / AutoTradeOrder types from '../../../api/trading'.

   // ── Constants (verbatim from AutoTrading.tsx lines 52-99) ────────────────────
   // These are used by OrderRow (STATUS_CONFIG) and ConfigPanel (DEFAULT_STRATEGY,
   // SESSION_OPTIONS, DIRECTION_OPTIONS, ENTRY_TYPES). Export them so panels
   // can import without reaching back into the parent file.
   export const SESSION_OPTIONS = [ /* copy verbatim */ ];
   export const DIRECTION_OPTIONS = [ /* copy verbatim */ ];
   export const ENTRY_TYPES = [ /* copy verbatim */ ];
   export const STATUS_CONFIG = { /* copy verbatim */ };
   export const DEFAULT_STRATEGY: Partial<TradingStrategy> = { /* copy verbatim */ };

   // ── Helpers (verbatim from AutoTrading.tsx lines 103-112) ────────────────────
   export const fmt = (n: number | null | undefined, decimals = 2, prefix = '') =>
     n == null ? '—' : `${prefix}${n.toFixed(decimals)}`;
   export const fmtUSD = (n: number | null | undefined) =>
     n == null ? '—' : `$${n.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
   export function pnlColor(n: number | null | undefined) {
     if (n == null) return 'text-gray-400';
     return n >= 0 ? 'text-green-400' : 'text-red-400';
   }

   // ── Sub-components (verbatim from AutoTrading.tsx lines 116-1001) ────────────
   // Copy each component block verbatim in declaration order:
   export const StatusBadge: React.FC<{ status: string }> = /* lines 116-125 */;
   // StrategyRow (lines 800-855), StratStat (857-862), OrderRow (864-933),
   // AccountMetric (935-940), StatRow (942-949), NumberField (953-981), ToggleField (983-1001).
   export { StrategyRow, StratStat, OrderRow, AccountMetric, StatRow, NumberField, ToggleField };
   ```

   If the file exceeds 200 LOC after adding all constants + helpers + components, split into:
   - `AutoTrading/components.tsx` — sub-components only (StatusBadge through ToggleField)
   - `AutoTrading/constants.ts` — STATUS_CONFIG, DEFAULT_STRATEGY, SESSION_OPTIONS, DIRECTION_OPTIONS, ENTRY_TYPES, fmt, fmtUSD, pnlColor
   and update panel imports accordingly.

3. Verify tsc:
   ```bash
   npx tsc --noEmit
   ```

4. Commit:
   ```bash
   git add frontend/src/pages/AutoTrading/components.tsx
   git commit -m "refactor(frontend): extract AutoTrading page-private components"
   ```

---

#### Task 7: Extract `StrategyPanel` and `OrdersPanel`

**Files:**
- Create: `frontend/src/pages/AutoTrading/StrategyPanel.tsx`
- Create: `frontend/src/pages/AutoTrading/OrdersPanel.tsx`

**Steps:**

1. Create `frontend/src/pages/AutoTrading/StrategyPanel.tsx`. This renders the strategies tab content — the strategy list, stat badges, and edit/delete/toggle controls:

   ```typescript
   // frontend/src/pages/AutoTrading/StrategyPanel.tsx
   import React from 'react';
   import { StrategyRow, StratStat } from './components';
   // Copy other imports from AutoTrading.tsx used in this section (Card, Button, etc.)

   export interface StrategyPanelProps {
     // Replace `any` with the actual types from AutoTrading.tsx.
     strategies: any[];
     loadingStrategies: boolean;
     stats: any;
     onCreateStrategy: () => void;
     onEditStrategy: (strategy: any) => void;
     onDeleteStrategy: (id: number) => void;
     onToggleStrategy: (id: number, active: boolean) => void;
   }

   export function StrategyPanel({
     strategies, loadingStrategies, stats,
     onCreateStrategy, onEditStrategy, onDeleteStrategy, onToggleStrategy,
   }: StrategyPanelProps) {
     // Copy the strategies tab JSX from AutoTrading.tsx.
   }
   ```

2. Create `frontend/src/pages/AutoTrading/OrdersPanel.tsx`:

   ```typescript
   // frontend/src/pages/AutoTrading/OrdersPanel.tsx
   import React from 'react';
   import { OrderRow } from './components';
   // Copy other imports from AutoTrading.tsx used in this section.

   export interface OrdersPanelProps {
     orders: any[];
     loadingOrders: boolean;
     orderFilter: string;
     onOrderFilter: (v: string) => void;
     onApprove: (id: number) => void;
     onReject: (id: number) => void;
     onCancel: (id: number) => void;
   }

   export function OrdersPanel({
     orders, loadingOrders, orderFilter, onOrderFilter,
     onApprove, onReject, onCancel,
   }: OrdersPanelProps) {
     // Copy the orders tab JSX from AutoTrading.tsx.
   }
   ```

3. Verify tsc:
   ```bash
   npx tsc --noEmit
   ```

4. Commit:
   ```bash
   git add frontend/src/pages/AutoTrading/StrategyPanel.tsx frontend/src/pages/AutoTrading/OrdersPanel.tsx
   git commit -m "refactor(frontend): extract StrategyPanel and OrdersPanel from AutoTrading.tsx"
   ```

---

#### Task 8: Extract `AccountPanel` and `ConfigPanel`

**Files:**
- Create: `frontend/src/pages/AutoTrading/AccountPanel.tsx`
- Create: `frontend/src/pages/AutoTrading/ConfigPanel.tsx`

**Steps:**

1. Create `frontend/src/pages/AutoTrading/AccountPanel.tsx`:

   ```typescript
   // frontend/src/pages/AutoTrading/AccountPanel.tsx
   import React from 'react';
   import { AccountMetric, StatRow } from './components';

   export interface AccountPanelProps {
     account: any;
     fetchingAccount: boolean;
     config: any;
     stats: any;
     onRefresh: () => void;
     onUpdateConfig: (config: any) => void;
   }

   export function AccountPanel({
     account, fetchingAccount, config, stats, onRefresh, onUpdateConfig,
   }: AccountPanelProps) {
     // Copy the account tab JSX from AutoTrading.tsx.
   }
   ```

2. Create `frontend/src/pages/AutoTrading/ConfigPanel.tsx`. This is the strategy create/edit modal form:

   ```typescript
   // frontend/src/pages/AutoTrading/ConfigPanel.tsx
   import React from 'react';
   import { NumberField, ToggleField } from './components';
   // Copy Modal and other imports from AutoTrading.tsx used in this section.

   export interface ConfigPanelProps {
     isOpen: boolean;
     editingStrategy: any | null;
     stratForm: any;
     onStratForm: (form: any) => void;
     onSave: () => void;
     onClose: () => void;
   }

   export function ConfigPanel({
     isOpen, editingStrategy, stratForm, onStratForm, onSave, onClose,
   }: ConfigPanelProps) {
     // Copy the modal + strategy form JSX from AutoTrading.tsx.
   }
   ```

3. Verify tsc:
   ```bash
   npx tsc --noEmit
   ```

4. Commit:
   ```bash
   git add frontend/src/pages/AutoTrading/AccountPanel.tsx frontend/src/pages/AutoTrading/ConfigPanel.tsx
   git commit -m "refactor(frontend): extract AccountPanel and ConfigPanel from AutoTrading.tsx"
   ```

---

#### Task 9: Create `AutoTrading/index.tsx` shell — delete `AutoTrading.tsx` — verify

**Files:**
- Create: `frontend/src/pages/AutoTrading/index.tsx`
- Delete: `frontend/src/pages/AutoTrading.tsx`

**Steps:**

1. Create `frontend/src/pages/AutoTrading/index.tsx`. Shell owns all queries, all mutations, tab state, and modal state:

   ```typescript
   // frontend/src/pages/AutoTrading/index.tsx
   import React, { useState } from 'react';
   import { StrategyPanel } from './StrategyPanel';
   import { OrdersPanel } from './OrdersPanel';
   import { AccountPanel } from './AccountPanel';
   import { ConfigPanel } from './ConfigPanel';
   // Copy all API / hook imports from AutoTrading.tsx.

   export default function AutoTrading() {
     const [tab, setTab] = useState<'strategies' | 'orders' | 'account'>('strategies');
     const [stratModalOpen, setStratModalOpen] = useState(false);
     const [editingStrategy, setEditingStrategy] = useState<any | null>(null);
     const [stratForm, setStratForm] = useState<any>({});
     const [orderFilter, setOrderFilter] = useState('');

     // Copy all useQuery / useMutation declarations from AutoTrading.tsx.
     // Copy handler functions (handleSaveStrategy, handleDeleteStrategy, etc.)

     return (
       <div className="..."> {/* copy top-level layout + tab switcher JSX */}
         {tab === 'strategies' && (
           <StrategyPanel
             strategies={strategies}
             loadingStrategies={loadingStrategies}
             stats={stats}
             onCreateStrategy={() => { setEditingStrategy(null); setStratForm({}); setStratModalOpen(true); }}
             onEditStrategy={(s) => { setEditingStrategy(s); setStratForm(s); setStratModalOpen(true); }}
             onDeleteStrategy={handleDeleteStrategy}
             onToggleStrategy={handleToggleStrategy}
           />
         )}
         {tab === 'orders' && (
           <OrdersPanel
             orders={orders}
             loadingOrders={loadingOrders}
             orderFilter={orderFilter}
             onOrderFilter={setOrderFilter}
             onApprove={handleApproveOrder}
             onReject={handleRejectOrder}
             onCancel={handleCancelOrder}
           />
         )}
         {tab === 'account' && (
           <AccountPanel
             account={account}
             fetchingAccount={fetchingAccount}
             config={config}
             stats={stats}
             onRefresh={refetch}
             onUpdateConfig={handleUpdateConfig}
           />
         )}
         <ConfigPanel
           isOpen={stratModalOpen}
           editingStrategy={editingStrategy}
           stratForm={stratForm}
           onStratForm={setStratForm}
           onSave={handleSaveStrategy}
           onClose={() => setStratModalOpen(false)}
         />
       </div>
     );
   }
   ```

2. Delete original file:
   ```bash
   rm /workspace/markethawk/frontend/src/pages/AutoTrading.tsx
   ```

3. Verify tsc:
   ```bash
   npx tsc --noEmit
   ```

4. Browser smoke test — open http://localhost:3333/trading:
   - Strategies tab renders the strategy list
   - Orders tab and Account tab switch correctly
   - Create Strategy button opens the modal and the form renders (NumberField, ToggleField visible)
   - No console errors

5. Commit:
   ```bash
   git add -A frontend/src/pages/AutoTrading/
   git rm frontend/src/pages/AutoTrading.tsx
   git commit -m "refactor(frontend): decompose AutoTrading.tsx into AutoTrading/ directory"
   ```

---

### Phase 3: Alerts (812 LOC → ~4 files)

#### Task 10: Extract `AlertRulesPanel` and `AlertLogsPanel`

**Files:**
- Create: `frontend/src/pages/Alerts/AlertRulesPanel.tsx`
- Create: `frontend/src/pages/Alerts/AlertLogsPanel.tsx`

**Steps:**

1. Create directory:
   ```bash
   mkdir -p /workspace/markethawk/frontend/src/pages/Alerts
   ```

2. Create `frontend/src/pages/Alerts/AlertRulesPanel.tsx`. Contains the rule list and the create/edit modal form, plus the three rule-form option arrays that are only used here:

   ```typescript
   // frontend/src/pages/Alerts/AlertRulesPanel.tsx
   import React from 'react';
   // Copy imports from Alerts.tsx used in this section (Card, Button, Modal, etc.)

   // ── Constants (verbatim from Alerts.tsx lines 47-69) — used only in this panel
   const SCANNER_TYPES = [ /* copy verbatim */ ];
   const SEVERITIES    = [ /* copy verbatim */ ];
   const COOLDOWN_OPTIONS = [ /* copy verbatim */ ];

   export interface AlertRulesPanelProps {
     rules: any[];
     isLoadingRules: boolean;
     strategies: any[];
     isModalOpen: boolean;
     editingRule: any | null;
     formState: any;
     onFormState: (state: any) => void;
     onOpenCreate: () => void;
     onOpenEdit: (rule: any) => void;
     onCloseModal: () => void;
     onSave: () => void;
     onDelete: (id: number) => void;
     onTest: (id: number) => void;
   }

   export function AlertRulesPanel({
     rules, isLoadingRules, strategies,
     isModalOpen, editingRule, formState, onFormState,
     onOpenCreate, onOpenEdit, onCloseModal, onSave, onDelete, onTest,
   }: AlertRulesPanelProps) {
     // Copy the rules list + modal form JSX from Alerts.tsx.
   }
   ```

3. Create `frontend/src/pages/Alerts/AlertLogsPanel.tsx`:

   ```typescript
   // frontend/src/pages/Alerts/AlertLogsPanel.tsx
   import React from 'react';
   // Copy imports from Alerts.tsx used in this section.

   export interface AlertLogsPanelProps {
     logs: any[];
     stats: any;
   }

   export function AlertLogsPanel({ logs, stats }: AlertLogsPanelProps) {
     // Copy the alert history + stats JSX from Alerts.tsx.
   }
   ```

4. Verify tsc:
   ```bash
   npx tsc --noEmit
   ```

5. Commit:
   ```bash
   git add frontend/src/pages/Alerts/AlertRulesPanel.tsx frontend/src/pages/Alerts/AlertLogsPanel.tsx
   git commit -m "refactor(frontend): extract AlertRulesPanel and AlertLogsPanel from Alerts.tsx"
   ```

---

#### Task 11: Extract `ChannelConfigPanel`

**Files:**
- Create: `frontend/src/pages/Alerts/ChannelConfigPanel.tsx`

**Steps:**

1. Create `frontend/src/pages/Alerts/ChannelConfigPanel.tsx`. This owns the push-subscription channel UI. The `useEffect` that checks for an active subscription (line ~90–98) remains in the shell because it writes to `hasPushSubscription` state that the shell owns:

   ```typescript
   // frontend/src/pages/Alerts/ChannelConfigPanel.tsx
   import React from 'react';
   // Copy imports from Alerts.tsx used in this section.

   export interface ChannelConfigPanelProps {
     hasPushSubscription: boolean | null;
     onSubscribe: () => void;
     onUnsubscribe: () => void;
   }

   export function ChannelConfigPanel({
     hasPushSubscription, onSubscribe, onUnsubscribe,
   }: ChannelConfigPanelProps) {
     // Copy the push subscription channel configuration JSX from Alerts.tsx.
   }
   ```

2. Verify tsc:
   ```bash
   npx tsc --noEmit
   ```

3. Commit:
   ```bash
   git add frontend/src/pages/Alerts/ChannelConfigPanel.tsx
   git commit -m "refactor(frontend): extract ChannelConfigPanel from Alerts.tsx"
   ```

---

#### Task 12: Create `Alerts/index.tsx` shell — delete `Alerts.tsx` — verify

**Files:**
- Create: `frontend/src/pages/Alerts/index.tsx`
- Delete: `frontend/src/pages/Alerts.tsx`

**Steps:**

1. Create `frontend/src/pages/Alerts/index.tsx`. Shell owns all queries, mutations, local state, and the subscription-check `useEffect`:

   ```typescript
   // frontend/src/pages/Alerts/index.tsx
   import React, { useState, useEffect } from 'react';
   import { AlertRulesPanel } from './AlertRulesPanel';
   import { AlertLogsPanel } from './AlertLogsPanel';
   import { ChannelConfigPanel } from './ChannelConfigPanel';
   // Copy all API/hook imports from Alerts.tsx.

   export default function Alerts() {
     const [isModalOpen, setIsModalOpen] = useState(false);
     const [editingRule, setEditingRule] = useState<any | null>(null);
     const [hasPushSubscription, setHasPushSubscription] = useState<boolean | null>(null);
     const [formState, setFormState] = useState<any>({});

     // Copy useQuery / useMutation declarations from Alerts.tsx.
     // Copy the subscription check useEffect (line ~90-98).
     // Copy handleSave, handleDelete, handleTest, handleSubscribe, handleUnsubscribe.

     return (
       <div className="...">
         <AlertRulesPanel
           rules={rules}
           isLoadingRules={isLoadingRules}
           strategies={strategies}
           isModalOpen={isModalOpen}
           editingRule={editingRule}
           formState={formState}
           onFormState={setFormState}
           onOpenCreate={() => { setEditingRule(null); setFormState({}); setIsModalOpen(true); }}
           onOpenEdit={(rule) => { setEditingRule(rule); setFormState(rule); setIsModalOpen(true); }}
           onCloseModal={() => setIsModalOpen(false)}
           onSave={handleSave}
           onDelete={handleDelete}
           onTest={handleTest}
         />
         <AlertLogsPanel logs={logs} stats={stats} />
         <ChannelConfigPanel
           hasPushSubscription={hasPushSubscription}
           onSubscribe={handleSubscribe}
           onUnsubscribe={handleUnsubscribe}
         />
       </div>
     );
   }
   ```

2. Delete original file:
   ```bash
   rm /workspace/markethawk/frontend/src/pages/Alerts.tsx
   ```

3. Verify tsc:
   ```bash
   npx tsc --noEmit
   ```

4. Browser smoke test — open http://localhost:3333/alerts:
   - Rule list loads; Create Rule modal opens and form renders
   - Alert logs section visible
   - Push subscription section renders with subscribe/unsubscribe button
   - No console errors

5. Commit:
   ```bash
   git add -A frontend/src/pages/Alerts/
   git rm frontend/src/pages/Alerts.tsx
   git commit -m "refactor(frontend): decompose Alerts.tsx into Alerts/ directory"
   ```

---

### Phase 4: StockDetailPage (694 LOC → ~4 files)

#### Task 13: Extract `ChartPanel` and `MetadataPanel`

**Files:**
- Create: `frontend/src/pages/StockDetailPage/ChartPanel.tsx`
- Create: `frontend/src/pages/StockDetailPage/MetadataPanel.tsx`

**Steps:**

1. Create directory:
   ```bash
   mkdir -p /workspace/markethawk/frontend/src/pages/StockDetailPage
   ```

2. Create `frontend/src/pages/StockDetailPage/ChartPanel.tsx`. Contains the Lightweight Charts section with period/timespan/resolution/showST controls:

   ```typescript
   // frontend/src/pages/StockDetailPage/ChartPanel.tsx
   import React from 'react';
   // Copy Chart import and other imports from StockDetailPage.tsx used here.

   export interface ChartPanelProps {
     symbol: string;
     historicalData: any;
     loadingHistorical: boolean;
     fetchingHistorical: boolean;
     liveData: any;
     isConnected: boolean;
     period: string;
     onPeriod: (v: string) => void;
     timespan: string;
     onTimespan: (v: string) => void;
     wsResolution: 'minute' | 'second';
     onWsResolution: (v: 'minute' | 'second') => void;
     showST: boolean;
     onShowST: (v: boolean) => void;
     catchingUp: boolean;
     highlightDate: string | undefined;
   }

   export function ChartPanel(props: ChartPanelProps) {
     // Copy the chart + controls JSX from StockDetailPage.tsx.
   }
   ```

3. Create `frontend/src/pages/StockDetailPage/MetadataPanel.tsx`. Contains ticker details, universe memberships, news:

   ```typescript
   // frontend/src/pages/StockDetailPage/MetadataPanel.tsx
   import React from 'react';
   // Copy NewsFeed and other imports from StockDetailPage.tsx used in this section.

   export interface MetadataPanelProps {
     symbol: string;
     details: any;
     loadingDetails: boolean;
     tickerUniverses: any[];
     systemInfo: any;
     onRefresh: () => void;
     onSyncMissing: () => void;
     onOpenForceScan: () => void;
   }

   export function MetadataPanel(props: MetadataPanelProps) {
     // Copy ticker info + news + universes JSX from StockDetailPage.tsx.
     // NewsFeed remains as a shared-component import.
   }
   ```

4. Verify tsc:
   ```bash
   npx tsc --noEmit
   ```

5. Commit:
   ```bash
   git add frontend/src/pages/StockDetailPage/ChartPanel.tsx frontend/src/pages/StockDetailPage/MetadataPanel.tsx
   git commit -m "refactor(frontend): extract ChartPanel and MetadataPanel from StockDetailPage.tsx"
   ```

---

#### Task 14: Extract `ScannerHistoryPanel`

**Files:**
- Create: `frontend/src/pages/StockDetailPage/ScannerHistoryPanel.tsx`

**Steps:**

1. Create `frontend/src/pages/StockDetailPage/ScannerHistoryPanel.tsx`. Contains the scanner event list, the force-scan dialog, and clear-history confirmation:

   ```typescript
   // frontend/src/pages/StockDetailPage/ScannerHistoryPanel.tsx
   import React from 'react';
   // Copy RecentEvents, ForceScanDialog imports from StockDetailPage.tsx.

   export interface ScannerHistoryPanelProps {
     symbol: string;
     scannerResults: any;
     clearConfirmOpen: boolean;
     onClearConfirmOpen: (v: boolean) => void;
     onClearHistory: () => void;
     scanDialogOpen: boolean;
     onScanDialogOpen: (v: boolean) => void;
     scanTaskId: string | null;
     scanSubmitting: boolean;
     scanDoneMsg: string | null;
     onScanSubmit: (taskId: string) => void;
     highlightDate: string | undefined;
     onHighlightDate: (date: string | undefined) => void;
   }

   export function ScannerHistoryPanel(props: ScannerHistoryPanelProps) {
     // Copy scanner history + clear history + ForceScanDialog JSX from StockDetailPage.tsx.
     // RecentEvents and ForceScanDialog remain as shared-component imports.
   }
   ```

2. Verify tsc:
   ```bash
   npx tsc --noEmit
   ```

3. Commit:
   ```bash
   git add frontend/src/pages/StockDetailPage/ScannerHistoryPanel.tsx
   git commit -m "refactor(frontend): extract ScannerHistoryPanel from StockDetailPage.tsx"
   ```

---

#### Task 15: Create `StockDetailPage/index.tsx` shell — delete old file — verify

**Files:**
- Create: `frontend/src/pages/StockDetailPage/index.tsx`
- Delete: `frontend/src/pages/StockDetailPage.tsx`

**Steps:**

1. Create `frontend/src/pages/StockDetailPage/index.tsx`. Shell owns all queries, mutations, all useState, and all useEffects from StockDetailPage.tsx:

   ```typescript
   // frontend/src/pages/StockDetailPage/index.tsx
   import React, { useState, useEffect, useRef } from 'react';
   import { useParams } from 'react-router-dom';
   import { ChartPanel } from './ChartPanel';
   import { MetadataPanel } from './MetadataPanel';
   import { ScannerHistoryPanel } from './ScannerHistoryPanel';
   // Copy all API/hook imports from StockDetailPage.tsx.

   export default function StockDetailPage() {
     const { ticker } = useParams<{ ticker: string }>();
     const symbol = ticker?.toUpperCase() || '';
     const [searchParams] = useSearchParams();  // used to initialise highlightDate from ?date= param

     // Copy all useState declarations from StockDetailPage.tsx:
     // period, timespan, wsResolution (initialised from localStorage keys
     //   'stock_detail_period', 'stock_detail_timespan', 'stock_detail_ws_res'),
     // highlightDate (initialised from searchParams.get('date')),
     // catchingUp, showST ('show_double_st'),
     // scanDialogOpen, scanTaskId, scanSubmitting, scanDoneMsg, clearConfirmOpen.

     // Copy const didRefreshRef = React.useRef<string | null>(null); (dedup guard).

     // Copy all useQuery / useMutation calls:
     //   refreshMutation, catchUpMutation, clearEventsMutation (mutations)
     //   details, historicalResponse, scannerResults (queries)
     //   useLiveStockData, getSystemInfo, fetchUniversesForTicker, useScanTask
     // Copy all useEffect hooks (localStorage save, background refresh, catch-up clear).

     return (
       <div className="...">
         <ChartPanel
           symbol={symbol!}
           historicalData={historicalResponse}
           loadingHistorical={loadingHistorical}
           fetchingHistorical={fetchingHistorical}
           liveData={liveData}
           isConnected={isConnected}
           period={period}
           onPeriod={setPeriod}
           timespan={timespan}
           onTimespan={setTimespan}
           wsResolution={wsResolution}
           onWsResolution={setWsResolution}
           showST={showST}
           onShowST={setShowST}
           catchingUp={catchingUp}
           highlightDate={highlightDate}
         />
         <MetadataPanel
           symbol={symbol!}
           details={details}
           loadingDetails={loadingDetails}
           tickerUniverses={tickerUniverses}
           systemInfo={systemInfo}
           onRefresh={() => refreshStockData({ ticker: symbol! })}
           onSyncMissing={() => syncMissingStockAggregates({ ticker: symbol! })}
           onOpenForceScan={() => setScanDialogOpen(true)}
         />
         <ScannerHistoryPanel
           symbol={symbol!}
           scannerResults={scannerResults}
           clearConfirmOpen={clearConfirmOpen}
           onClearConfirmOpen={setClearConfirmOpen}
           onClearHistory={handleClearHistory}
           scanDialogOpen={scanDialogOpen}
           onScanDialogOpen={setScanDialogOpen}
           scanTaskId={scanTaskId}
           scanSubmitting={scanSubmitting}
           scanDoneMsg={scanDoneMsg}
           onScanSubmit={handleScanSubmit}
           highlightDate={highlightDate}
           onHighlightDate={setHighlightDate}
         />
       </div>
     );
   }
   ```

2. Delete original file:
   ```bash
   rm /workspace/markethawk/frontend/src/pages/StockDetailPage.tsx
   ```

3. Verify tsc:
   ```bash
   npx tsc --noEmit
   ```

4. Browser smoke test — open http://localhost:3333/stock/AAPL (or any available ticker):
   - Chart loads with OHLCV data; period/timespan controls work
   - Metadata panel shows ticker info and news
   - Scanner history list visible; Clear History button triggers confirmation
   - Force-scan dialog opens when triggered
   - No console errors

5. Commit:
   ```bash
   git add -A frontend/src/pages/StockDetailPage/
   git rm frontend/src/pages/StockDetailPage.tsx
   git commit -m "refactor(frontend): decompose StockDetailPage.tsx into StockDetailPage/ directory"
   ```

---

### Phase 5: ActiveWatchlist (683 LOC → ~3 files + 1 hook)

#### Task 16: Extract `useWatchlistLive` hook

**Files:**
- Create: `frontend/src/hooks/useWatchlistLive.ts`

**Steps:**

1. Create `frontend/src/hooks/useWatchlistLive.ts`. This is lines 91–206 of ActiveWatchlist.tsx extracted verbatim. The hook manages the WebSocket connection to `/api/live/ws/watchlist`, handles four message types (`quote`, `tick`, `minute_bar`, `alert`), and auto-reconnects after 3 s:

   ```typescript
   // frontend/src/hooks/useWatchlistLive.ts
   import { useState, useEffect, useRef } from 'react';
   // Copy all imports used by the inline hook from ActiveWatchlist.tsx.

   export interface WatchlistLiveEntry {
     // Copy the exact per-symbol data shape from the hook's state in ActiveWatchlist.tsx.
     price?: number;
     change?: number;
     changePercent?: number;
     volume?: number;
     vwap?: number;
     session?: string;
     alerts?: any[];
   }

   export interface UseWatchlistLiveReturn {
     liveData: Record<string, WatchlistLiveEntry>;
     connected: boolean;
   }

   export function useWatchlistLive(symbols: string[]): UseWatchlistLiveReturn {
     // Copy lines 91-206 from ActiveWatchlist.tsx verbatim.
     // Adjust any reference to the outer component's `items` array to use
     // the `symbols` parameter instead — check whether the inline version
     // already accepted symbols or derived them from component scope.
   }
   ```

2. Verify tsc:
   ```bash
   npx tsc --noEmit
   ```

3. Commit:
   ```bash
   git add frontend/src/hooks/useWatchlistLive.ts
   git commit -m "refactor(frontend): extract useWatchlistLive hook from ActiveWatchlist.tsx"
   ```

---

#### Task 17: Extract `AlertBadges` and `WatchlistTable`

**Files:**
- Create: `frontend/src/pages/ActiveWatchlist/AlertBadges.tsx`
- Create: `frontend/src/pages/ActiveWatchlist/WatchlistTable.tsx`

**Steps:**

1. Create directory:
   ```bash
   mkdir -p /workspace/markethawk/frontend/src/pages/ActiveWatchlist
   ```

2. Create `frontend/src/pages/ActiveWatchlist/AlertBadges.tsx`. This file is named with the plural form to match the spec's architecture table, but exports a singularly-named component `AlertBadge` to match the existing definition in ActiveWatchlist.tsx (line 376):

   ```typescript
   // frontend/src/pages/ActiveWatchlist/AlertBadges.tsx
   import React from 'react';
   // Copy imports used by AlertBadge from ActiveWatchlist.tsx.

   export interface AlertBadgeProps {
     // Copy the exact props from AlertBadge in ActiveWatchlist.tsx (line 376).
   }

   export function AlertBadge(props: AlertBadgeProps) {
     // Copy lines 376-392 from ActiveWatchlist.tsx verbatim.
   }
   ```

3. Create `frontend/src/pages/ActiveWatchlist/WatchlistTable.tsx`. Contains `PriceCell`, `SessionCell`, `WatchlistRow`, and `AddSymbolForm` from ActiveWatchlist.tsx, plus the table rendering:

   ```typescript
   // frontend/src/pages/ActiveWatchlist/WatchlistTable.tsx
   import React, { useState } from 'react';
   import { AlertBadge } from './AlertBadges';
   import type { UseWatchlistLiveReturn } from '../../hooks/useWatchlistLive';
   // Copy Button and other shared imports from ActiveWatchlist.tsx.

   // Copy verbatim from ActiveWatchlist.tsx:
   // - PriceCell (lines 308-333)
   // - SessionCell (lines 337-372)
   // - WatchlistRow (lines 396-551) — uses AlertBadge
   // - AddSymbolForm (lines 213-304)

   export interface WatchlistTableProps {
     items: any[];
     isLoading: boolean;
     isError: boolean;
     liveData: UseWatchlistLiveReturn['liveData'];
     onAdd: (symbol: string, securityType: string, exchange: string, notes: string) => void;
     onRemove: (symbol: string) => void;
     onUpdateNotes: (symbol: string, notes: string) => void;
   }

   export function WatchlistTable({
     items, isLoading, isError, liveData, onAdd, onRemove, onUpdateNotes,
   }: WatchlistTableProps) {
     // Copy the table + add-form JSX from ActiveWatchlist.tsx.
   }
   ```

4. Verify tsc:
   ```bash
   npx tsc --noEmit
   ```

5. Commit:
   ```bash
   git add frontend/src/pages/ActiveWatchlist/AlertBadges.tsx frontend/src/pages/ActiveWatchlist/WatchlistTable.tsx
   git commit -m "refactor(frontend): extract WatchlistTable and AlertBadges from ActiveWatchlist.tsx"
   ```

---

#### Task 18: Create `ActiveWatchlist/index.tsx` shell — delete old file — verify

**Files:**
- Create: `frontend/src/pages/ActiveWatchlist/index.tsx`
- Delete: `frontend/src/pages/ActiveWatchlist.tsx`

**Steps:**

1. Create `frontend/src/pages/ActiveWatchlist/index.tsx`. Shell owns the watchlist query, the live hook, and all mutations:

   ```typescript
   // frontend/src/pages/ActiveWatchlist/index.tsx
   import React from 'react';
   import { WatchlistTable } from './WatchlistTable';
   import { useWatchlistLive } from '../../hooks/useWatchlistLive';
   // Copy query / mutation imports from ActiveWatchlist.tsx.

   export default function ActiveWatchlist() {
     const { data: items = [], isLoading, isError } = useWatchlist();
     const symbols = items.map((item: any) => item.symbol);
     const { liveData, connected } = useWatchlistLive(symbols);
     // Copy useAddToWatchlist, useRemoveFromWatchlist, useUpdateWatchlistNotes mutations.

     return (
       <div className="..."> {/* copy top-level layout from ActiveWatchlist.tsx */}
         <WatchlistTable
           items={items}
           isLoading={isLoading}
           isError={isError}
           liveData={liveData}
           onAdd={(symbol, securityType, exchange, notes) =>
             addToWatchlist({ symbol, securityType, exchange, notes })}
           onRemove={(symbol) => removeFromWatchlist(symbol)}
           onUpdateNotes={(symbol, notes) => updateNotes({ symbol, notes })}
         />
       </div>
     );
   }
   ```

2. Delete original file:
   ```bash
   rm /workspace/markethawk/frontend/src/pages/ActiveWatchlist.tsx
   ```

3. Verify tsc:
   ```bash
   npx tsc --noEmit
   ```

4. Browser smoke test — open http://localhost:3333/watchlist:
   - Watchlist table loads with symbol rows
   - Real-time price data updates (PriceCell changes)
   - Add symbol form works; added symbol appears in table
   - Remove symbol works
   - No console errors

5. Commit:
   ```bash
   git add -A frontend/src/pages/ActiveWatchlist/
   git rm frontend/src/pages/ActiveWatchlist.tsx
   git commit -m "refactor(frontend): decompose ActiveWatchlist.tsx into ActiveWatchlist/ directory"
   ```

---

### Phase 6: Final Validation

#### Task 19: LOC audit + tsc + import verification

**Steps:**

1. LOC audit — every output file must be ≤ 300 lines:
   ```bash
   wc -l \
     frontend/src/pages/Scanner/*.tsx \
     frontend/src/pages/AutoTrading/*.tsx \
     frontend/src/pages/Alerts/*.tsx \
     frontend/src/pages/StockDetailPage/*.tsx \
     frontend/src/pages/ActiveWatchlist/*.tsx \
     frontend/src/hooks/useScannerState.ts \
     frontend/src/hooks/useWatchlistLive.ts
   # Expected: every individual file ≤ 300 lines
   ```
   If any file exceeds 300, split it — follow the spec guidance for AutoTrading/components.tsx (FormFields + DisplayComponents) or equivalent for other files.

2. Final tsc across entire frontend:
   ```bash
   cd /workspace/markethawk/frontend && npx tsc --noEmit
   # Expected: zero errors
   ```

3. Confirm App.tsx router imports are unchanged (directory-index resolution is transparent):
   ```bash
   grep -n "Scanner\|AutoTrading\|Alerts\|StockDetail\|ActiveWatchlist" frontend/src/App.tsx
   # Expected: same import strings as on main — no path changes needed
   ```

4. Confirm shared components are untouched:
   ```bash
   git diff main -- frontend/src/components/ScannerResults.tsx \
                    frontend/src/components/ScannerConfig.tsx \
                    frontend/src/components/SignalReviewStats.tsx
   # Expected: no diff
   ```
