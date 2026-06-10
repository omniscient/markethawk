# Eliminate `any` Usages & Re-enable `no-explicit-any: error` — Implementation Plan

**Date:** 2026-06-10
**Issue:** #239
**Spec:** `docs/superpowers/specs/2026-06-10-eliminate-any-usages-design.md`
**Status:** Plan — pending architect review

## Goal

Eliminate all 131 `@typescript-eslint/no-explicit-any` warnings in `frontend/src/`, promote the rule to `error` in `eslint.config.js`, and restore the strict `npm run lint` gate in CI and the pre-commit hook.

## Architecture

All changes are frontend-only. No backend changes. No new API routes. No schema changes. The implementation follows the codebase's established pattern: types come from `frontend/src/api/*.ts`; components import them rather than declaring local duplicates.

## Tech Stack

- TypeScript (tsc `--noEmit` is the final gate)
- ESLint + `@typescript-eslint` v8 (flat config)
- Vitest (test-utils files)

## File Structure

| File | Change |
|------|--------|
| `frontend/src/api/scanner.ts` | Add `EdgeDistributionEvent`, `EdgeStatEntry` types |
| `frontend/src/hooks/useScannerState.ts` | `useState<any>` → `useState<ScannerRunResponse \| null>` |
| `frontend/src/hooks/useScannerWs.ts` | `setActiveScan: any` → typed; `msg: any` → `unknown` |
| `frontend/src/pages/Dashboard.tsx` | Remove 3 callback `any`s; remove 8 icon casts |
| `frontend/src/pages/EdgeExplorer.tsx` | Remove 15 `any`s — icon casts + callback types |
| `frontend/src/pages/Journal.tsx` | Mutation fn `any`s → `CreateJournalEntryRequest` / `CreateTradeRequest` |
| `frontend/src/pages/Scanner/ScanConfigPanel.tsx` | Props interface + icon casts |
| `frontend/src/pages/Scanner/ScanStatusCard.tsx` | Props interface + icon cast |
| `frontend/src/pages/Scanner/index.tsx` | Callback + error handler `any`s |
| `frontend/src/pages/Scanner/ResultsPanel.tsx` | Props interface `any` |
| `frontend/src/pages/StockDetailPage/ChartPanel.tsx` | Props interface + icon casts |
| `frontend/src/pages/StockDetailPage/MetadataPanel.tsx` | Props interface + icon casts |
| `frontend/src/pages/StockDetailPage/ScannerHistoryPanel.tsx` | Props interface `any`s |
| `frontend/src/pages/StockDetailPage/index.tsx` | Map callbacks + cast `any`s |
| `frontend/src/pages/AutoTrading/AccountPanel.tsx` | Props interface `any`s |
| `frontend/src/pages/AutoTrading/ConfigPanel.tsx` | Event handler `any`s |
| `frontend/src/pages/Alerts/AlertLogsPanel.tsx` | Props interface `any`s |
| `frontend/src/pages/Alerts/AlertRuleModal.tsx` | Narrowed cast `any`s |
| `frontend/src/pages/ActiveWatchlist/index.tsx` | `onError` callback `any` |
| `frontend/src/pages/PreMarketMovers.tsx` | Callback `any`s |
| `frontend/src/pages/Settings.tsx` | Event handler `any` |
| `frontend/src/components/ScannerConfig.tsx` | Props interface `any`s |
| `frontend/src/components/ScannerResults.tsx` | `renderIndicator` param + map `any`s |
| `frontend/src/components/UniverseFormModal.tsx` | Event handler / map `any`s |
| `frontend/src/components/SyncUniverseModal.tsx` | Map `any` |
| `frontend/src/components/ExportUniverseModal.tsx` | Event handler `any` |
| `frontend/src/components/QualityReportModal.tsx` | `onError` callback `any` |
| `frontend/src/components/ui/Chart.tsx` | `data: any[]`, tooltip `any` |
| `frontend/src/components/ui/StockChart.tsx` | Two `any`s in internal logic |
| `frontend/src/test-utils/MockWebSocket.ts` | `globalThis as any` → typed cast |
| `frontend/src/hooks/useScorecard.test.ts` | `{} as any` → `{} as Scorecard` |
| `frontend/eslint.config.js` | `'warn'` → `'error'` |
| `.github/workflows/ci.yml` | Restore `npm run lint` |
| `.pre-commit-config.yaml` | Restore `npm run lint` |

---

## Task 1: Baseline — Verify 131 warnings

**Files:** none (read-only check)

### Steps

1. Run lint baseline in `frontend/`:
   ```bash
   cd frontend && npx eslint . --report-unused-disable-directives-severity error 2>&1 | tail -5
   # Expected: ✖ 131 problems (0 errors, 131 warnings)
   ```
2. Confirm `tsc --noEmit` is currently passing:
   ```bash
   cd frontend && npx tsc --noEmit
   # Expected: no output (exits 0)
   ```

**Commit:** (none — read-only baseline)

---

## Task 2: Add API types for EdgeExplorer data shapes

**Files:**
- `frontend/src/api/scanner.ts`

### Context

`EdgeExplorer.tsx` fetches two untyped endpoints (`/scanner/edge-stats` and `/scanner/edge-distribution`) via raw `apiClient.get()` which returns `any`. Adding typed response interfaces here lets the component remove all callback `any`s without local interface duplication.

### Steps

1. Run lint on EdgeExplorer to see the violations:
   ```bash
   cd frontend && npx eslint src/pages/EdgeExplorer.tsx
   # Expected: 15 warnings
   ```
2. Open `frontend/src/api/scanner.ts`. After the `ScannerSparklinePoint` block (around line 305), add:
   ```ts
   export interface EdgeDistributionEvent {
     ticker: string;
     event_date: string;
     gap_pct: number;
     fade_pct: number;
     day_range_pct: number;
   }

   export interface EdgeDistributionResponse {
     events: EdgeDistributionEvent[];
   }

   export interface EdgeStatEntry {
     label: string;
     event_count: number;
     avg_gap_pct: number;
     avg_fade_pct: number;
     avg_day_range_pct: number;
     avg_rel_vol: number;
   }
   ```
3. Run lint again — 0 change yet (we haven't updated EdgeExplorer):
   ```bash
   cd frontend && npx eslint src/pages/EdgeExplorer.tsx
   # Still 15 warnings — expected
   ```

**Commit:** (hold until Task 5 which uses these types)

---

## Task 3: Fix icon `as any` casts — all files (Pattern 1)

**Files:** Dashboard.tsx, Journal.tsx, ScanConfigPanel.tsx, ScanStatusCard.tsx, StockDetailPage/ChartPanel.tsx, StockDetailPage/MetadataPanel.tsx, EdgeExplorer.tsx, and any other file with `icon={X as any}` on a Card, MetricCard, or Button.

### Context

`Card`, `MetricCard`, and `Button` all declare `icon?: LucideIcon`. All passed Lucide icons are already `LucideIcon`. The casts are stale. Remove them mechanically — no interface changes needed.

### Steps

1. Count icon casts across the codebase:
   ```bash
   cd frontend && grep -rn 'as any' src/ | grep -E 'icon=|icon:' | wc -l
   # Note the count
   ```

2. In **`src/pages/Dashboard.tsx`** — remove `as any` from all 8 icon-prop casts:
   ```diff
   -  icon={Activity as any}
   +  icon={Activity}
   -  icon={TrendingUp as any}
   +  icon={TrendingUp}
   -  icon={Bell as any}
   +  icon={Bell}
   -  icon={TrendingDown as any}
   +  icon={TrendingDown}
   ```
   Apply the same removal at lines 130, 143, 151, 168.

3. In **`src/pages/Journal.tsx`** — remove icon casts (BookOpen, Plus, Download, TrendingUp, TrendingDown, Target, Activity, MessageSquare, PlusCircle, etc. wherever `as any` appears on icon props).

4. In **`src/pages/Scanner/ScanConfigPanel.tsx`** — remove icon casts:
   ```diff
   -  <Button variant="danger" onClick={onCancelScan} icon={X as any}>
   +  <Button variant="danger" onClick={onCancelScan} icon={X}>
   -  <Button variant="primary" onClick={onRunScan} icon={Play as any}
   +  <Button variant="primary" onClick={onRunScan} icon={Play}
   -  <Card title="Scanner Configuration" icon={Settings as any}>
   +  <Card title="Scanner Configuration" icon={Settings}>
   -  <Card title="Quick Actions" icon={Zap as any}>
   +  <Card title="Quick Actions" icon={Zap}>
   -  <Button variant="secondary" size="sm" fullWidth icon={Clock as any}>
   +  <Button variant="secondary" size="sm" fullWidth icon={Clock}>
   -  <Button variant="secondary" size="sm" fullWidth icon={Download as any}>
   +  <Button variant="secondary" size="sm" fullWidth icon={Download}>
   -  <Card title="Recent Scan History" icon={Clock as any}>
   +  <Card title="Recent Scan History" icon={Clock}>
   ```

5. In **`src/pages/Scanner/ScanStatusCard.tsx`** — remove icon cast:
   ```diff
   -  <Card title="Scan Status" icon={Eye as any}>
   +  <Card title="Scan Status" icon={Eye}>
   ```

6. In **`src/pages/StockDetailPage/ChartPanel.tsx`** — remove icon cast:
   ```diff
   -  icon={BarChart2 as any}
   +  icon={BarChart2}
   ```

7. In **`src/pages/StockDetailPage/MetadataPanel.tsx`** — remove icon casts:
   ```diff
   -  <Card title="Stock Specific News" icon={Newspaper as any}>
   +  <Card title="Stock Specific News" icon={Newspaper}>
   -  <Card title="Trader Plan Checklist" icon={Globe as any}>
   +  <Card title="Trader Plan Checklist" icon={Globe}>
   ```

8. In **`src/pages/EdgeExplorer.tsx`** — remove all icon casts:
   ```diff
   -  icon={Layers as any}
   +  icon={Layers}
   -  icon={TrendingUp as any}
   +  icon={TrendingUp}
   -  icon={Target as any}
   +  icon={Target}
   -  icon={BarChart2 as any}
   +  icon={BarChart2}
   -  icon={Calendar as any}
   +  icon={Calendar}
   ```
   (5 MetricCard/Card icon casts total in EdgeExplorer)

9. Note: **`src/pages/AutoTrading/AccountPanel.tsx`** has no icon casts — all its `any`s are in the props interface (handled in Task 12, not here).

10. Verify icon-cast fixes for any remaining files containing `as any}` with icon props:
    ```bash
    cd frontend && grep -rn 'as any}' src/ | grep -v 'test\|spec'
    ```

11. Run lint to check progress:
    ```bash
    cd frontend && npx eslint . --report-unused-disable-directives-severity error 2>&1 | tail -3
    # Warning count should be noticeably lower (icon casts were ~50 of 131)
    ```

12. Run `tsc --noEmit` to verify no type errors introduced:
    ```bash
    cd frontend && npx tsc --noEmit
    # Expected: exits 0
    ```

**Commit:**
```bash
git add frontend/src/pages/Dashboard.tsx frontend/src/pages/Journal.tsx \
  frontend/src/pages/Scanner/ScanConfigPanel.tsx frontend/src/pages/Scanner/ScanStatusCard.tsx \
  frontend/src/pages/StockDetailPage/ChartPanel.tsx frontend/src/pages/StockDetailPage/MetadataPanel.tsx \
  frontend/src/pages/EdgeExplorer.tsx
git commit -m "fix(#239): remove stale icon as-any casts — LucideIcon props already typed"
```

---

## Task 4: Fix API-layer typed props — Scanner components

**Files:**
- `frontend/src/components/ScannerConfig.tsx`
- `frontend/src/pages/Scanner/ScanConfigPanel.tsx`
- `frontend/src/pages/Scanner/ScanStatusCard.tsx`

### Context

`ScannerConfig`, `ScanConfigPanel`, and `ScanStatusCard` all receive `configs: any[]`, `universes: any[]`, `statusBlock: any`, and `scanHistory: any[]`. All these types exist in `api/scanner.ts`: `ScannerConfig`, `StockUniverse`, `ScannerStatusBlock`, and `ScannerRunResponse`.

### Steps

1. Run lint on these three files:
   ```bash
   cd frontend && npx eslint src/components/ScannerConfig.tsx \
     src/pages/Scanner/ScanConfigPanel.tsx src/pages/Scanner/ScanStatusCard.tsx
   # Note: 4 + 12 + 5 warnings
   ```

2. In **`src/components/ScannerConfig.tsx`** — add imports and fix the interface:
   ```diff
   +import { ScannerConfig as ScannerConfigType, StockUniverse } from '../api/scanner';
   
    interface ScannerConfigProps {
   -  configs: any[];
   -  universes: any[];
   +  configs: ScannerConfigType[];
   +  universes: StockUniverse[];
      selectedConfig: string;
   ```

3. In **`src/pages/Scanner/ScanConfigPanel.tsx`** — add imports and fix the interface:
   ```diff
   +import type { ScannerConfig, ScannerRunResponse, ScannerStatusBlock, StockUniverse } from '../../api/scanner';
   
    export interface ScanConfigPanelProps {
   -  configs: any[];
   +  configs: ScannerConfig[];
      loadingConfigs: boolean;
   -  universes: any[];
   +  universes: StockUniverse[];
      loadingUniverses: boolean;
      ...
   -  statusBlock: any;
   -  scanHistory: any[];
   +  statusBlock: ScannerStatusBlock | undefined;
   +  scanHistory: ScannerRunResponse[];
      ...
   }
   ```
   Also fix the `scanHistory.map((scan: any, index)` at line 150 — remove the `: any` annotation; TypeScript infers `ScannerRunResponse` from the array type:
   ```diff
   -  scanHistory.map((scan: any, index: number) => (
   +  scanHistory.map((scan, index) => (
   ```

4. In **`src/pages/Scanner/ScanStatusCard.tsx`** — add imports and fix the interface:
   ```diff
   +import type { ScannerStatusBlock, StockUniverse } from '../../api/scanner';
   
    export interface ScanStatusCardProps {
      isScanning: boolean;
   -  statusBlock: any;
   +  statusBlock: ScannerStatusBlock | undefined;
      selectedUniverse: number | null;
   -  universes: any[];
   +  universes: StockUniverse[];
    }
   ```

5. Run lint to verify these files are clean:
   ```bash
   cd frontend && npx eslint src/components/ScannerConfig.tsx \
     src/pages/Scanner/ScanConfigPanel.tsx src/pages/Scanner/ScanStatusCard.tsx
   # Expected: 0 warnings for these files
   ```
6. Run `tsc --noEmit`:
   ```bash
   cd frontend && npx tsc --noEmit
   # Expected: exits 0
   ```

**Commit:**
```bash
git add frontend/src/components/ScannerConfig.tsx \
  frontend/src/pages/Scanner/ScanConfigPanel.tsx \
  frontend/src/pages/Scanner/ScanStatusCard.tsx
git commit -m "fix(#239): type Scanner component props — ScannerConfig/StockUniverse/ScannerStatusBlock"
```

---

## Task 5: Fix Dashboard.tsx — callback `any` params

**Files:**
- `frontend/src/pages/Dashboard.tsx`

### Context

Three callbacks annotate `any` on array element params. `scannerResults` is `ScannerEvent[]` (inferred from `useQuery` with `fetchScannerResults`). Remove the annotations; TypeScript infers `ScannerEvent`. Fix `recentAlerts as any` by computing a properly typed array.

### Steps

1. Run lint on Dashboard.tsx after Task 3 (icon casts removed). Note remaining `any` count — should be ~5:
   ```bash
   cd frontend && npx eslint src/pages/Dashboard.tsx
   ```

2. Remove callback `any` annotations at lines 62, 67 (TypeScript infers from `ScannerEvent[]`):
   ```diff
   -  const todayEvents = scannerResults?.filter(
   -    (event: any) => event.event_date === format(new Date(), 'yyyy-MM-dd')
   +  const todayEvents = scannerResults?.filter(
   +    (event) => event.event_date === format(new Date(), 'yyyy-MM-dd')
   ```
   ```diff
   -  .map((e: any) => e.created_at ? new Date(e.created_at).getTime() : 0)
   +  .map((e) => e.created_at ? new Date(e.created_at).getTime() : 0)
   ```

3. Fix `recentAlerts` at line 52. `AlertList` is defined in `components/AlertList.tsx` with a local `Alert` interface requiring `type: 'volume_spike' | 'price_movement' | 'news'` and `severity: 'high' | 'medium' | 'low'`. TypeScript widens the literals in the `.map()` to `string`. Fix by annotating the mapper output with explicit union casts:
   ```diff
   -  const recentAlerts = (scannerResults?.slice(0, 5) || []).map((event: any) => ({
   +  const recentAlerts = (scannerResults?.slice(0, 5) || []).map((event) => ({
        id: event.uuid || String(event.id),
        ticker: event.ticker,
   -    type: event.severity === 'high' ? 'volume_spike' : 'news',
   +    type: (event.severity === 'high' ? 'volume_spike' : 'news') as 'volume_spike' | 'news',
        message: event.summary || `${event.ticker} triggered a ${event.scanner_type} alert`,
        timestamp: event.created_at || event.event_date || new Date().toISOString(),
   -    severity: event.severity || 'low',
   +    severity: (event.severity || 'low') as 'high' | 'medium' | 'low',
      }));
   -  <AlertList alerts={recentAlerts as any} />
   +  <AlertList alerts={recentAlerts} />
   ```

4. Fix `events={recentEvents as any}` at line 153. `RecentEvents` expects `ScannerEvent[]`; `recentEvents = scannerResults || []` is already `ScannerEvent[]` once `scannerResults` is typed:
   ```diff
   -  events={recentEvents as any}
   +  events={recentEvents}
   ```

5. Run lint:
   ```bash
   cd frontend && npx eslint src/pages/Dashboard.tsx
   # Expected: 0 warnings
   ```
6. Run `tsc --noEmit`:
   ```bash
   cd frontend && npx tsc --noEmit
   # Expected: exits 0
   ```

**Commit:**
```bash
git add frontend/src/pages/Dashboard.tsx
git commit -m "fix(#239): remove callback any params in Dashboard.tsx — infer from ScannerEvent[]"
```

---

## Task 6: Fix EdgeExplorer.tsx — callback `any` and remaining `any`s

**Files:**
- `frontend/src/pages/EdgeExplorer.tsx`

### Context

After removing icon casts (Task 3), remaining `any`s are: 3 reduce callbacks on `events` array, 3 `apiClient.get()` return callbacks inline, and several `map/reduce` on `stats` array. Use `EdgeDistributionEvent` and `EdgeStatEntry` from Task 2.

### Steps

1. Run lint on EdgeExplorer after Task 3:
   ```bash
   cd frontend && npx eslint src/pages/EdgeExplorer.tsx
   # Should be ~9 warnings remaining (icon casts already removed)
   ```

2. In `EdgeExplorer.tsx`, add imports at the top:
   ```diff
   +import type { EdgeDistributionEvent, EdgeDistributionResponse, EdgeStatEntry } from '../api/scanner';
   ```

3. Fix the `distribution` query return type using the new interface:
   ```diff
    queryFn: async () => {
      const params = new URLSearchParams();
      if (ticker) params.append('ticker', ticker);
      if (scannerType) params.append('scanner_type', scannerType);
      const response = await apiClient.get<EdgeDistributionResponse>(
        `/scanner/edge-distribution?${params.toString()}`
      );
      return response.data;
    }
   ```

4. Fix the `stats` query return type:
   ```diff
    queryFn: async () => {
      const params = new URLSearchParams({ period });
      if (ticker) params.append('ticker', ticker);
      if (scannerType) params.append('scanner_type', scannerType);
      const response = await apiClient.get<EdgeStatEntry[]>(
        `/scanner/edge-stats?${params.toString()}`
      );
      return response.data;
    }
   ```

5. Fix reduce callbacks at lines 107–109. After the type fix, `events` is now `EdgeDistributionEvent[]`, so TypeScript infers `e`:
   ```diff
   -  events.reduce((acc: number, e: any) => acc + (e.gap_pct || 0), 0)
   +  events.reduce((acc, e) => acc + (e.gap_pct || 0), 0)
   -  events.reduce((acc: number, e: any) => acc + (e.fade_pct || 0), 0)
   +  events.reduce((acc, e) => acc + (e.fade_pct || 0), 0)
   -  events.reduce((acc: number, e: any) => acc + (e.day_range_pct || 0), 0)
   +  events.reduce((acc, e) => acc + (e.day_range_pct || 0), 0)
   ```

6. Fix `stats?.reduce((acc: number, s: any) => ...)` at line 176 similarly:
   ```diff
   -  stats.reduce((acc: number, s: any) => acc + s.event_count, 0)
   +  stats.reduce((acc, s) => acc + s.event_count, 0)
   ```

7. Fix `events.map((entry: any, index)` at line 234 — after typing, `entry` is `EdgeDistributionEvent`:
   ```diff
   -  events.map((entry: any, index: number) => (
   +  events.map((entry, index) => (
   ```

8. Fix `stats?.map((row: any, i: number)` at line 308:
   ```diff
   -  stats?.map((row: any, i: number) => (
   +  stats?.map((row, i) => (
   ```

9. Commit `api/scanner.ts` (from Task 2) along with `EdgeExplorer.tsx`:
   ```bash
   cd frontend && npx eslint src/pages/EdgeExplorer.tsx
   # Expected: 0 warnings
   cd frontend && npx tsc --noEmit
   # Expected: exits 0
   ```

**Commit:**
```bash
git add frontend/src/api/scanner.ts frontend/src/pages/EdgeExplorer.tsx
git commit -m "fix(#239): add EdgeDistribution/EdgeStat API types; fix EdgeExplorer callback anys"
```

---

## Task 7: Fix Journal.tsx — mutation function `any`s

**Files:**
- `frontend/src/pages/Journal.tsx`

### Context

Two `useMutation` calls have `mutationFn: (data: any)`. `journalApi.createEntry` expects `CreateJournalEntryRequest`; `journalApi.createTrade` expects `CreateTradeRequest`. Import these types and annotate the mutation variables.

### Steps

1. Run lint on Journal.tsx after Task 3 (icon casts removed):
   ```bash
   cd frontend && npx eslint src/pages/Journal.tsx
   # Note remaining count (~2–4)
   ```

2. Add imports at top of `Journal.tsx`:
   ```diff
   +import type { CreateJournalEntryRequest, CreateTradeRequest } from '../api/journal';
   ```

3. Fix the `createEntryMutation`:
   ```diff
   -  mutationFn: (data: any) => journalApi.createEntry(data),
   +  mutationFn: (data: CreateJournalEntryRequest) => journalApi.createEntry(data),
   ```

4. Fix the `createTradeMutation`:
   ```diff
   -  mutationFn: (data: any) => journalApi.createTrade(data),
   +  mutationFn: (data: CreateTradeRequest) => journalApi.createTrade(data),
   ```
   Also fix the call sites `createEntryMutation.mutate({...})` and `createTradeMutation.mutate({...})` if TypeScript now flags the passed object — shape the object to match the request interface.

5. Fix any remaining `any`s in the icon-cast pass (should already be done in Task 3).

6. Run lint and tsc:
   ```bash
   cd frontend && npx eslint src/pages/Journal.tsx && npx tsc --noEmit
   # Expected: 0 warnings, exits 0
   ```

**Commit:**
```bash
git add frontend/src/pages/Journal.tsx
git commit -m "fix(#239): type Journal.tsx mutation params — CreateJournalEntryRequest/CreateTradeRequest"
```

---

## Task 8: Fix `Chart.tsx` data types

**Files:**
- `frontend/src/components/ui/Chart.tsx`

### Context

Four `any`s: `data: any[]`, `events?: any[]`, `liveData?: any`, and `{ active, payload, label }: any` in the `CustomTooltip`. Per spec, view-model shapes (Recharts data arrays) may use a local interface.

### Steps

1. Run lint on Chart.tsx:
   ```bash
   cd frontend && npx eslint src/components/ui/Chart.tsx
   # Expected: 4 warnings
   ```

2. Add import for `ScannerEvent`:
   ```diff
   +import type { ScannerEvent } from '../../api/scanner';
   ```

3. Add a `TooltipProps` import from Recharts and add local `ChartDataPoint` interface at top of file:
   ```ts
   import type { TooltipProps } from 'recharts';
   import type { ValueType, NameType } from 'recharts/types/component/DefaultTooltipContent';

   interface ChartDataPoint {
     [key: string]: unknown;
   }
   ```

4. Fix the `ChartProps` interface:
   ```diff
   -  data: any[];
   +  data: ChartDataPoint[];
   -  events?: any[];
   +  events?: ScannerEvent[];
   -  liveData?: any;
   +  liveData?: Record<string, unknown>;
   ```

5. Fix `CustomTooltip`:
   ```diff
   -  const CustomTooltip = ({ active, payload, label }: any) => {
   +  const CustomTooltip = ({ active, payload, label }: TooltipProps<ValueType, NameType>) => {
   ```

6. Run lint and tsc:
   ```bash
   cd frontend && npx eslint src/components/ui/Chart.tsx && npx tsc --noEmit
   # Expected: 0 warnings, exits 0
   ```

**Commit:**
```bash
git add frontend/src/components/ui/Chart.tsx
git commit -m "fix(#239): type Chart.tsx data props — ChartDataPoint interface + ScannerEvent[] events"
```

---

## Task 9: Fix `useScannerWs.ts` — WS message handler and typed state setter

**Files:**
- `frontend/src/hooks/useScannerWs.ts`

### Context

Four `any`s: `setActiveScan: (v: any)` in the state slice, `handleWsMessage = (msg: any)`, and two `(next[k] as any) = msg[k]` assignments. Fix approach:
- `setActiveScan` → `Dispatch<SetStateAction<ActiveScanRef | null>>`
- `msg: any` → `msg: unknown` + narrow to `Record<string, unknown>` after the existing `typeof !== 'object'` guard
- Dynamic key assignments → use `(msg as Partial<LiveProgress>)[k]` to eliminate `any`

### Steps

1. Run lint:
   ```bash
   cd frontend && npx eslint src/hooks/useScannerWs.ts
   # Expected: 4 warnings
   ```

2. Add `ActiveScanRef` to the existing `useScannerState` import on line 5 (do **not** add a new import — `LiveProgress` is already imported there and a duplicate would cause a TypeScript error):
   ```diff
   -import { ACTIVE_SCAN_LS_KEY, type LiveProgress } from './useScannerState';
   +import { ACTIVE_SCAN_LS_KEY, type ActiveScanRef, type LiveProgress } from './useScannerState';
   ```

3. Fix the `WsStateSlice` interface:
   ```diff
    interface WsStateSlice {
      wsRef: MutableRefObject<WebSocket | null>;
      setIsScanning: (v: boolean) => void;
   -  setActiveScan: (v: any) => void;
   +  setActiveScan: Dispatch<SetStateAction<ActiveScanRef | null>>;
      setScanError: (v: string | null) => void;
      setLiveProgress: Dispatch<SetStateAction<LiveProgress>>;
    }
   ```

4. Fix `handleWsMessage` signature:
   ```diff
   -  const handleWsMessage = (msg: any) => {
   +  const handleWsMessage = (msg: unknown) => {
        if (!msg || typeof msg !== 'object') return;
   +    const msgObj = msg as Record<string, unknown>;
   ```

5. Throughout `handleWsMessage`, replace bare `msg.` accesses with `msgObj['...']`:
   ```diff
   -  if (msg.type === 'snapshot' || msg.type === 'started') {
   -    next.total_days = msg.total_days ?? next.total_days;
   -    next.total_tickers = msg.total_tickers ?? msg.tickers ?? next.total_tickers;
   -    next.estimated_pairs = msg.estimated_pairs ?? (next.total_days * next.total_tickers);
   +  if (msgObj['type'] === 'snapshot' || msgObj['type'] === 'started') {
   +    next.total_days = (msgObj['total_days'] as number) ?? next.total_days;
   +    next.total_tickers = (msgObj['total_tickers'] as number) ?? (msgObj['tickers'] as number) ?? next.total_tickers;
   +    next.estimated_pairs = (msgObj['estimated_pairs'] as number) ?? (next.total_days * next.total_tickers);
   ```
   Apply similar substitution for `msg.type`, `msg.day_index`, `msg.total_days`, `msg.date`, `msg.error`, `msg.task_id` etc. throughout the function body.

6. Fix the two dynamic key assignments (lines 49, 64). Replace `as any` with `Partial<LiveProgress>` cast:
   ```diff
   -  if (msg.type === 'snapshot') {
   +  if (msgObj['type'] === 'snapshot') {
        for (const k of [
          'day_index', 'total_days', 'evaluated', 'no_data', 'no_prior_close',
          'no_baseline', 'fired_pre', 'fired_post', 'errors', 'events_detected',
        ] as (keyof LiveProgress)[]) {
   -      if (msg[k] != null) (next[k] as any) = msg[k];
   +      const val = (msgObj as Partial<LiveProgress>)[k];
   +      if (val != null) next[k] = val;
        }
      }
   ```
   Apply the same change at the second occurrence (day_completed block, line 64).

7. Fix the terminal `if/else`:
   ```diff
   -  if (msg.type === 'completed') finishScan('completed');
   -  else if (msg.type === 'failed') finishScan('failed', msg.error || 'Scan failed');
   -  else if (msg.type === 'cancelled') finishScan('cancelled');
   +  if (msgObj['type'] === 'completed') finishScan('completed');
   +  else if (msgObj['type'] === 'failed') finishScan('failed', (msgObj['error'] as string) || 'Scan failed');
   +  else if (msgObj['type'] === 'cancelled') finishScan('cancelled');
   ```

8. Run lint and tsc:
   ```bash
   cd frontend && npx eslint src/hooks/useScannerWs.ts && npx tsc --noEmit
   # Expected: 0 warnings, exits 0
   ```

**Commit:**
```bash
git add frontend/src/hooks/useScannerWs.ts
git commit -m "fix(#239): type useScannerWs.ts — unknown msg + Partial<LiveProgress> key assignments"
```

---

## Task 10: Fix `useScannerState.ts` and `Scanner/index.tsx`

**Files:**
- `frontend/src/hooks/useScannerState.ts`
- `frontend/src/pages/Scanner/index.tsx`

### Context

`useScannerState` has `useState<any>(null)` for `scanResults`. The value is `ScannerRunResponse | null`. `Scanner/index.tsx` has `setScanResults((prev: any) => ...)` and `onError: (error: any) =>`.

### Steps

1. Run lint on both files:
   ```bash
   cd frontend && npx eslint src/hooks/useScannerState.ts src/pages/Scanner/index.tsx
   ```

2. In **`useScannerState.ts`**, add import and fix the `useState`:
   ```diff
   +import type { ScannerRunResponse } from '../api/scanner';

   -  const [scanResults, setScanResults] = useState<any>(null);
   +  const [scanResults, setScanResults] = useState<ScannerRunResponse | null>(null);
   ```

3. In **`Scanner/index.tsx`**, fix the `setScanResults` callback. After `useScannerState` returns `setScanResults: Dispatch<SetStateAction<ScannerRunResponse | null>>`, the lambda must be typed:
   ```diff
   -  state.setScanResults((prev: any) => {
   -    if (prev && prev.scan_id !== 'historical') return prev;
   -    return { scan_id: 'historical', status: 'completed', stocks_scanned: 0, events_detected: existingResults.length, execution_time_ms: 0, events: existingResults };
   +  state.setScanResults((prev) => {
   +    if (prev && prev.scan_id !== 'historical') return prev;
   +    return { scan_id: 'historical', status: 'completed', stocks_scanned: 0, scanner_type: '', events_detected: existingResults.length, execution_time_ms: 0, events: existingResults };
   ```
   (`scanner_type` is required in `ScannerRunResponse` — add `scanner_type: ''` as a placeholder if it's unknown at this point.)

4. Fix `onError: (error: any)` in `Scanner/index.tsx` at ~line 81:
   ```diff
   -  onError: (error: any) => {
   -    const status = error?.response?.status;
   -    const detail = error?.response?.data?.detail;
   +  onError: (error: unknown) => {
   +    const status = (error as { response?: { status?: number } })?.response?.status;
   +    const detail = (error as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
   ```

5. Run lint and tsc:
   ```bash
   cd frontend && npx eslint src/hooks/useScannerState.ts src/pages/Scanner/index.tsx && npx tsc --noEmit
   # Expected: 0 warnings, exits 0
   ```

**Commit:**
```bash
git add frontend/src/hooks/useScannerState.ts frontend/src/pages/Scanner/index.tsx
git commit -m "fix(#239): type useScannerState scanResults and Scanner/index.tsx error handler"
```

---

## Task 11: Fix StockDetailPage components

**Files:**
- `frontend/src/pages/StockDetailPage/ChartPanel.tsx`
- `frontend/src/pages/StockDetailPage/MetadataPanel.tsx`
- `frontend/src/pages/StockDetailPage/ScannerHistoryPanel.tsx`
- `frontend/src/pages/StockDetailPage/index.tsx`

### Context

These share a common pattern: props typed `any` where real types exist in `api/stocks.ts`, `api/scanner.ts`, or the existing domain types. `ChartPanel` icon casts already removed in Task 3.

### Steps

1. Run lint:
   ```bash
   cd frontend && npx eslint src/pages/StockDetailPage/
   ```

2. In **`ChartPanel.tsx`** — after icon-cast removal, remaining `any`s are prop types. Add imports and fix:
   ```diff
   +import type { StockDetailConsolidated } from '../../api/stocks';
   +import type { ScannerEvent } from '../../api/scanner';

    export interface ChartPanelProps {
      symbol: string;
   -  historicalData: any[];
   +  historicalData: Record<string, unknown>[];
      loadingHistorical: boolean;
      fetchingHistorical: boolean;
   -  liveData: any;
   +  liveData: Record<string, unknown> | null;
   -  events: any[];
   +  events: ScannerEvent[];
      ...
   -  details: any;
   +  details: StockDetailConsolidated;
    }
   ```

3. In **`MetadataPanel.tsx`** — fix props after icon-cast removal:
   ```diff
   +import type { StockDetailConsolidated } from '../../api/stocks';
   +import type { ScannerEvent } from '../../api/scanner';

    export interface MetadataPanelProps {
      symbol: string;
   -  details: any;
   -  scannerResults: any;
   -  events: any[];
   +  details: StockDetailConsolidated;
   +  scannerResults: ScannerEvent[];
   +  events: ScannerEvent[];
    }
   ```
   Fix the `some((e: any) =>` at line 26:
   ```diff
   -  scannerResults && scannerResults.some((e: any) => e.metadata?.catalyst_summary)
   +  scannerResults && scannerResults.some((e) => e.metadata?.catalyst_summary)
   ```

4. In **`ScannerHistoryPanel.tsx`** — check lines 16, 42, 110 for the three `any`s. Fix each by importing the relevant type:
   ```diff
   +import type { ScannerEvent } from '../../api/scanner';
   ```
   Remove `: any` annotations where TypeScript can infer from typed arrays.

5. In **`StockDetailPage/index.tsx`** — fix the 5 `any`s at lines 187–250:
   - Line 187: `(scannerResults as any)?.data` — use a narrowed check:
     ```diff
     -  const resultsArray = Array.isArray(scannerResults) ? scannerResults : (scannerResults as any)?.data || (scannerResults as any)?.results || [];
     +  const resultsArray: ScannerEvent[] = Array.isArray(scannerResults) ? scannerResults : [];
     ```
   - Lines 188–191: `resultsArray.map((e: any) =>` — after typing `resultsArray` as `ScannerEvent[]`, remove `: any`.
   - Line 214: `tickerUniverses.map((u: any) =>` — import `StockUniverse` and fix:
     ```diff
     +import type { StockUniverse } from '../../api/scanner';
     -  tickerUniverses.map((u: any) => (
     +  tickerUniverses.map((u: StockUniverse) => (
     ```
   - Line 250: additional `any` — fix similarly.

6. Run lint and tsc:
   ```bash
   cd frontend && npx eslint src/pages/StockDetailPage/ && npx tsc --noEmit
   # Expected: 0 warnings, exits 0
   ```

**Commit:**
```bash
git add frontend/src/pages/StockDetailPage/
git commit -m "fix(#239): type StockDetailPage props — StockDetailConsolidated/ScannerEvent"
```

---

## Task 12: Fix remaining page and component files

**Files:**
- `frontend/src/pages/AutoTrading/AccountPanel.tsx` (5 any — props interface)
- `frontend/src/pages/AutoTrading/ConfigPanel.tsx` (2 any — event handlers)
- `frontend/src/pages/Alerts/AlertLogsPanel.tsx` (2 any — props interface)
- `frontend/src/pages/Alerts/AlertRuleModal.tsx` (2 any — channel config cast)
- `frontend/src/pages/ActiveWatchlist/index.tsx` (1 any — onError)
- `frontend/src/pages/PreMarketMovers.tsx` (4 any — callbacks)
- `frontend/src/pages/Settings.tsx` (1 any — event handler)
- `frontend/src/pages/Scanner/ResultsPanel.tsx` (1 any — props interface)
- `frontend/src/components/ScannerResults.tsx` (4 any — renderIndicator + map)
- `frontend/src/components/UniverseFormModal.tsx` (5 any — event handlers / maps)
- `frontend/src/components/SyncUniverseModal.tsx` (1 any — map callback)
- `frontend/src/components/ExportUniverseModal.tsx` (1 any — event handler)
- `frontend/src/components/QualityReportModal.tsx` (3 any — onError + other)
- `frontend/src/components/ui/StockChart.tsx` (2 any — internal logic)

### Steps

For each file, the pattern is:
- **Props interface `any`** → import the real type from the appropriate `api/` file, annotate the prop.
- **`onError: (error: any)`** → `onError: (error: unknown)` with narrowing.
- **`map/filter((item: any)`** → remove annotation; TypeScript infers from the array type.
- **`as any` on a cast** → find the real type or use `as unknown as TargetType`.

1. Run lint on all remaining files:
   ```bash
   cd frontend && npx eslint \
     src/pages/AutoTrading/ \
     src/pages/Alerts/ \
     src/pages/ActiveWatchlist/ \
     src/pages/PreMarketMovers.tsx \
     src/pages/Settings.tsx \
     src/pages/Scanner/ResultsPanel.tsx \
     src/components/ScannerResults.tsx \
     src/components/UniverseFormModal.tsx \
     src/components/SyncUniverseModal.tsx \
     src/components/ExportUniverseModal.tsx \
     src/components/QualityReportModal.tsx \
     src/components/ui/StockChart.tsx
   ```

2. **`AutoTrading/AccountPanel.tsx`** — 5 `any`s: 4 in the props interface (lines 10–15) + 1 inner map callback (line 70). Use `AccountSummary` (not `IBKRAccount` — confirmed in `api/trading.ts`):
   ```diff
   +import type { AccountSummary, TradingStats, TradingConfig } from '../../api/trading';

    export interface AccountPanelProps {
   -  account: any;
   -  stats: any;
   -  config: any;
   -  onUpdateConfig: (cfg: any) => void;
   +  account: AccountSummary | null;
   +  stats: TradingStats | null;
   +  config: TradingConfig | null;
   +  onUpdateConfig: (cfg: TradingConfig) => void;
    }
   ```
   Fix the line-70 inner map callback — once `account` is typed as `AccountSummary`, remove the `: any` annotation so TypeScript infers the element type from `AccountSummary['open_broker_orders']`:
   ```diff
   -  {account.open_broker_orders.map((o: any) => (
   +  {account.open_broker_orders.map((o) => (
   ```

3. **`AutoTrading/ConfigPanel.tsx`** — lines 196 and 217 are `e.target.value as any` casts on union-typed select fields. The `e` is already inferred; the cast target is wrong. Fix using `TradingStrategy`'s literal unions:
   ```diff
   +import type { TradingStrategy } from '../../api/trading';
   
   -  onChange={e => onStratForm({ ...stratForm, entry_type: e.target.value as any })}
   +  onChange={e => onStratForm({ ...stratForm, entry_type: e.target.value as TradingStrategy['entry_type'] })}
   
   -  onChange={e => onStratForm({ ...stratForm, direction: e.target.value as any })}
   +  onChange={e => onStratForm({ ...stratForm, direction: e.target.value as TradingStrategy['direction'] })}
   ```
   (`TradingStrategy['entry_type']` = `'market' | 'limit'`; `TradingStrategy['direction']` = `'long_only' | 'short_only' | 'both'`)

4. **`Alerts/AlertLogsPanel.tsx`** — `logs: any[]` props (AlertActivityCardProps and AlertLogsPanelProps). Import `AlertLog` from `api/alerts.ts`:
   ```diff
   +import type { AlertLog } from '../../api/alerts';

    export interface AlertActivityCardProps {
   -  logs: any[];
   +  logs: AlertLog[];
    }
    export interface AlertLogsPanelProps {
   -  logs: any[];
   +  logs: AlertLog[];
    }
   ```

5. **`Alerts/AlertRuleModal.tsx`** — two `any`s:
   - Line 89: `severity_filter: sev.id as any` — `AlertRule['severity_filter']` is `'any' | 'high' | 'medium' | 'low'`:
     ```diff
     +import type { AlertRule } from '../../api/alerts';
     -  onFormState({ ...formState, severity_filter: sev.id as any })
     +  onFormState({ ...formState, severity_filter: sev.id as AlertRule['severity_filter'] })
     ```
   - Line 182: `(formState.channel_config as any)?.[ch.field]` — `channel_config` is already typed in `AlertRule`; use `Record<string, unknown>` to access dynamically:
     ```diff
     -  value={(formState.channel_config as any)?.[ch.field] ?? ''}
     +  value={((formState.channel_config ?? {}) as Record<string, unknown>)[ch.field] as string ?? ''}
     ```

6. **`ActiveWatchlist/index.tsx`** — `onError: (err: any)` → `onError: (err: unknown)`:
   ```diff
   -  onError: (err: any) => {
   -    const msg = err?.response?.data?.detail ?? err?.message ?? 'Delete failed';
   +  onError: (err: unknown) => {
   +    const msg = (err as { response?: { data?: { detail?: unknown } }; message?: string })?.response?.data?.detail
   +      ?? (err as { message?: string })?.message ?? 'Delete failed';
   ```

7. **`PreMarketMovers.tsx`** — 4 `any`s at lines 37, 106, 112, 118. These are callback params on arrays returned by React Query. Import `PreMarketMover` from `api/scanner.ts` (it's already exported there):
   ```diff
   +import type { PreMarketMover } from '../api/scanner';
   
   -  data?.map((mover: any) => (
   +  data?.map((mover: PreMarketMover) => (
   ```
   Remove the remaining 3 `: any` annotations on callback params where the array element type is inferred from `PreMarketMover[]`.

8. **`Settings.tsx`** — 1 `any` at line 140 is an icon cast (`icon={Database as any}`), not an event handler. Fix by removing `as any` (same Pattern 1 as Task 3):
   ```diff
   -  <Card title="Data & Storage" icon={Database as any}>
   +  <Card title="Data & Storage" icon={Database}>
   ```

9. **`Scanner/ResultsPanel.tsx`** — `scanResults: any` prop. Import `ScannerRunResponse` and type it:
   ```diff
   +import type { ScannerRunResponse } from '../../api/scanner';

    export interface ResultsPanelProps {
   -  scanResults: any;
   +  scanResults: ScannerRunResponse | null;
   ```

10. **`ScannerResults.tsx`** — `renderIndicator(key: string, val: any)`: the `val` comes from `event.indicators` which is `Record<string, unknown>`. Fix:
    ```diff
    -  const renderIndicator = (key: string, val: any) => {
    +  const renderIndicator = (key: string, val: unknown) => {
    ```
    The existing `typeof val === 'number'` check already narrows correctly. For the remaining `(event: any)` map callbacks, TypeScript infers from `ScannerEvent[]` after the array is properly typed — remove the annotations.

11. **`UniverseFormModal.tsx`** — 5 `any`s (lines 61, 217, 270). These are event handler casts and form-state map callbacks. Check what type the `apiClient.get()` returns for universes and fix the callbacks to infer from typed arrays. For event handlers, use `React.ChangeEvent<HTMLInputElement>`.

12. **`SyncUniverseModal.tsx`** — 1 `any` at line 75. Remove the map callback annotation; TypeScript infers from the array.

13. **`ExportUniverseModal.tsx`** — 1 `any` at line 114. Remove the event handler annotation or type it with `React.ChangeEvent`.

14. **`QualityReportModal.tsx`** — `onError: (err: any)` (3 occurrences at lines 399, 451, 452) → `onError: (err: unknown)` with the same narrowing pattern as step 6.

15. **`StockChart.tsx`** — 2 `any`s:
    - **Line 101**: `const seriesRef = useRef<ISeriesApi<any> | null>(null)`. The existing comment explains the library limitation: `ISeriesApi<SeriesType>` as a union makes `.setData()` unsatisfiable because TypeScript requires the argument to match ALL union members simultaneously. Fix by using a **single** concrete type for the ref (candlestick, the dominant path), then casting through `unknown` at the specific call sites that use a different series type:
      ```diff
      -  const seriesRef = useRef<ISeriesApi<any> | null>(null);
      +  const seriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null);
      ```
      Four call sites to update:
      - **Line 326** (`seriesRef.current.setData(candleData)`): No change — `candleData` is `CandlestickData[]`, compatible with `ISeriesApi<'Candlestick'>`.
      - **Line 450** (`seriesRef.current.setData(uniqueData)`, in the `else`/line–area branch): `uniqueData` is `(LineData | AreaData)[]` — not assignable to `CandlestickData[]`. Cast through `unknown`:
        ```diff
        -  seriesRef.current.setData(uniqueData);
        +  (seriesRef.current as unknown as ISeriesApi<'Line'>).setData(uniqueData as LineData[]);
        ```
      - **Line 509** (`seriesRef.current.update(barData)`): No change — `barData` is a candlestick-bar update.
      - **Line 531** (`seriesRef.current.update({ time: timeValue, value: liveData.c })`): Line/area live data — cast through `unknown`:
        ```diff
        -  seriesRef.current.update({ time: timeValue, value: liveData.c });
        +  (seriesRef.current as unknown as ISeriesApi<'Line'>).update({ time: timeValue, value: liveData.c });
        ```
      No `any` anywhere — all cross-series casts go through `unknown`.

    - **Line 366**: `stCloudSeriesRef.current?.setData(cloudData as any)`. The `cloudData` array includes `color`/`borderColor`/`wickColor` which are not in the base `CandlestickData` type. Fix by defining a local extended type and removing the cast:
      ```ts
      import type { CandlestickData, Time } from 'lightweight-charts';

      interface StyledCandleData extends CandlestickData {
        color?: string;
        borderColor?: string;
        wickColor?: string;
      }
      ```
      Then type `cloudData`:
      ```diff
      -  const cloudData = stData.map(d => ({
      +  const cloudData: StyledCandleData[] = stData.map(d => ({
      ```
      Change `setData(cloudData as any)` to `stCloudSeriesRef.current?.setData(cloudData)`.

14. After all files are fixed:
    ```bash
    cd frontend && npx eslint . --report-unused-disable-directives-severity error 2>&1 | tail -5
    # Should be approaching 0 warnings (only test utils and the 2 useScannerState remain)
    ```
    ```bash
    cd frontend && npx tsc --noEmit
    # Expected: exits 0
    ```

**Commit:**
```bash
git add frontend/src/pages/AutoTrading/ \
  frontend/src/pages/Alerts/ \
  frontend/src/pages/ActiveWatchlist/ \
  frontend/src/pages/PreMarketMovers.tsx \
  frontend/src/pages/Settings.tsx \
  frontend/src/pages/Scanner/ResultsPanel.tsx \
  frontend/src/components/ScannerResults.tsx \
  frontend/src/components/UniverseFormModal.tsx \
  frontend/src/components/SyncUniverseModal.tsx \
  frontend/src/components/ExportUniverseModal.tsx \
  frontend/src/components/QualityReportModal.tsx \
  frontend/src/components/ui/StockChart.tsx
git commit -m "fix(#239): type remaining pages and components — eliminate callback/prop any annotations"
```

---

## Task 13: Fix test utilities

**Files:**
- `frontend/src/test-utils/MockWebSocket.ts`
- `frontend/src/hooks/useScorecard.test.ts`

### Context

`MockWebSocket.ts` uses `(globalThis as any).WebSocket` for mocking. `useScorecard.test.ts` uses `{} as any` and `mockScorecard as any` as `fetchScorecard` mock return values. Fix both with real types.

### Steps

1. Run lint on test files:
   ```bash
   cd frontend && npx eslint src/test-utils/MockWebSocket.ts src/hooks/useScorecard.test.ts
   # Expected: 3 + 2 = 5 warnings
   ```

2. In **`MockWebSocket.ts`** — replace `(globalThis as any).WebSocket` with typed cast:
   ```diff
    export function installMockWebSocket(): () => void {
   -  const original = (globalThis as any).WebSocket;
   -  (globalThis as any).WebSocket = MockWebSocket;
   +  const original = (globalThis as { WebSocket: typeof WebSocket }).WebSocket;
   +  (globalThis as { WebSocket: typeof WebSocket }).WebSocket = MockWebSocket as unknown as typeof WebSocket;
      MockWebSocket.lastInstance = null;
      return () => {
   -    (globalThis as any).WebSocket = original;
   +    (globalThis as { WebSocket: typeof WebSocket }).WebSocket = original;
      };
    }
   ```

3. In **`useScorecard.test.ts`** — add `Scorecard` import and fix fixtures:
   ```diff
   +import type { Scorecard } from '../api/outcomes';
   
   -  vi.mocked(fetchScorecard).mockResolvedValue({} as any);
   +  vi.mocked(fetchScorecard).mockResolvedValue({} as Scorecard);
   
   -  vi.mocked(fetchScorecard).mockResolvedValue(mockScorecard as any);
   +  vi.mocked(fetchScorecard).mockResolvedValue(mockScorecard as Partial<Scorecard> as Scorecard);
   ```

4. Run lint:
   ```bash
   cd frontend && npx eslint src/test-utils/MockWebSocket.ts src/hooks/useScorecard.test.ts
   # Expected: 0 warnings
   ```
5. Run `tsc --noEmit`:
   ```bash
   cd frontend && npx tsc --noEmit
   # Expected: exits 0
   ```

**Commit:**
```bash
git add frontend/src/test-utils/MockWebSocket.ts frontend/src/hooks/useScorecard.test.ts
git commit -m "fix(#239): type test utilities — globalThis cast and Scorecard fixture types"
```

---

## Task 14: Verify zero warnings, then promote ESLint rule + restore CI/pre-commit

**Files:**
- `frontend/eslint.config.js`
- `.github/workflows/ci.yml`
- `.pre-commit-config.yaml`

### Steps

1. **Pre-flight check** — confirm zero warnings before touching the config:
   ```bash
   cd frontend && npx eslint . --report-unused-disable-directives-severity error 2>&1 | tail -5
   # MUST be: ✖ 0 problems (0 errors, 0 warnings)
   # If any warnings remain, fix them before proceeding.
   ```

2. **Promote ESLint rule** in `frontend/eslint.config.js`:
   ```diff
   -  '@typescript-eslint/no-explicit-any': 'warn',
   +  '@typescript-eslint/no-explicit-any': 'error',
   ```

3. **Run `npm run lint`** to confirm the now-strict gate passes:
   ```bash
   cd frontend && npm run lint
   # Expected: exits 0, 0 problems
   ```

4. **Restore CI lint step** in `.github/workflows/ci.yml`. Find the line:
   ```yaml
   run: npx eslint . --report-unused-disable-directives-severity error
   ```
   Replace with:
   ```yaml
   run: npm run lint
   ```

5. **Restore pre-commit hook** in `.pre-commit-config.yaml`. Find the eslint hook entry:
   ```yaml
   entry: bash -c 'cd frontend && npx eslint . --report-unused-disable-directives-severity error'
   ```
   Replace with:
   ```yaml
   entry: bash -c 'cd frontend && npm run lint'
   ```

6. **Final verification**:
   ```bash
   cd frontend && npm run lint
   # Expected: exits 0

   cd frontend && npx tsc --noEmit
   # Expected: exits 0
   ```

**Commit:**
```bash
git add frontend/eslint.config.js .github/workflows/ci.yml .pre-commit-config.yaml
git commit -m "fix(#239): promote no-explicit-any to error; restore npm run lint in CI and pre-commit"
```

---

## Summary

| Task | Files Changed | `any` Eliminated |
|------|--------------|-----------------|
| 1 | — | — (baseline) |
| 2 | `api/scanner.ts` | 0 (types added for Task 6) |
| 3 | 8 page/component files | ~50 icon casts |
| 4 | 3 Scanner components | ~20 props |
| 5 | `Dashboard.tsx` | 5 |
| 6 | `EdgeExplorer.tsx` | 9 |
| 7 | `Journal.tsx` | 2 |
| 8 | `Chart.tsx` | 4 |
| 9 | `useScannerWs.ts` | 4 |
| 10 | `useScannerState.ts`, `Scanner/index.tsx` | 3 |
| 11 | `StockDetailPage/` (4 files) | ~17 |
| 12 | 14 pages/components/StockChart | ~17 |
| 13 | `MockWebSocket.ts`, `useScorecard.test.ts` | 5 |
| 14 | `eslint.config.js`, `ci.yml`, `.pre-commit-config.yaml` | — (gate promoted) |

**Total:** 131 `any`s eliminated, strict ESLint gate restored.
