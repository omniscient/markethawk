# Frontend Code Splitting and Lazy Loading Design

**Date**: 2026-05-28  
**Status**: Draft  
**Scope**: Route-level code splitting for all non-critical-path pages in `frontend/src/App.tsx` using `React.lazy()` and `<Suspense>`, plus a permanent bundle verification tool.

---

## Overview

All 13 protected route-level page components in `App.tsx` are currently statically imported, causing the entire frontend to be bundled and parsed on initial page load — including pages the user may never visit (AutoTrading, EdgeExplorer, Journal). With 86 frontend files and heavyweight dependencies (`recharts`, `lightweight-charts`), this adds unnecessary parse cost to every first visit.

The fix is route-level code splitting: convert page imports to `React.lazy()` so Vite generates per-page chunks loaded on demand, add a single `<Suspense>` boundary with a lightweight fallback, and add `rollup-plugin-visualizer` as a permanent devDependency for bundle monitoring.

---

## Requirements

1. **Login stays as a static import.** Login is the first-paint entry point for unauthenticated users. Lazy-loading it adds a network round-trip before the login form appears, with no bundle-size benefit.

2. **13 pages converted to `React.lazy()`:** Dashboard, Scanner, Universes, Alerts, Settings, StockDetailPage, Journal, EdgeExplorer, PreMarketMovers, ActiveWatchlist, AutoTrading, ScorecardOverview, ScorecardDetail.

3. **Single `PageLoader` component** — a centered spinner on `bg-financial-dark`, used as the `<Suspense>` fallback for all lazy routes. No per-page fallback variants.

4. **Single Suspense boundary** wrapping all lazy routes inside `ProtectedRoute`'s `<Layout>`.

5. **No `manualChunks` configuration.** Vite's default chunking is sufficient. Each page's sub-components (e.g. `Scanner/ResultsPanel.tsx`, `AutoTrading/OrdersPanel.tsx`) are only imported by their parent page and bundle into that page's chunk automatically.

6. **`rollup-plugin-visualizer` added as a permanent `devDependency`**, gated by `ANALYZE=true`. Generates `stats.html` (gitignored). Invoked with `ANALYZE=true npm run build`.

7. **WebSocket hooks verified after lazy load.** `useScannerWs` (Scanner page) and `useWatchlistLive` (ActiveWatchlist page) must establish connections correctly after a lazy-loaded page first mounts. Manual test: navigate to each page after a hard reload and confirm WebSocket connections appear in DevTools Network tab.

---

## Architecture / Approach

### Chosen Approach: `React.lazy` + Single `<Suspense>` Boundary

**`frontend/src/App.tsx` — change all 13 protected page imports:**

```tsx
// Before (static):
import Dashboard from './pages/Dashboard';
import Scanner from './pages/Scanner';
// ...

// After (lazy):
const Dashboard = React.lazy(() => import('./pages/Dashboard'));
const Scanner = React.lazy(() => import('./pages/Scanner'));
// ... repeat for all 13 protected pages

// Login stays static:
import Login from './pages/Login';
```

**Suspense boundary placement — wrap the inner `<Routes>` inside `<Layout>`:**

```tsx
<Layout>
  <Suspense fallback={<PageLoader />}>
    <Routes>
      <Route path="/" element={<Dashboard />} />
      <Route path="/scanner" element={<Scanner />} />
      {/* ... all other routes */}
    </Routes>
  </Suspense>
</Layout>
```

This placement means the Layout shell (nav sidebar, header) renders immediately while only the page content area shows the spinner during chunk fetch.

**New component: `frontend/src/components/ui/PageLoader.tsx`**

```tsx
export function PageLoader() {
  return (
    <div className="min-h-screen bg-financial-dark flex items-center justify-center">
      <div className="w-8 h-8 border-2 border-financial-light/20 border-t-financial-light rounded-full animate-spin" />
    </div>
  );
}
```

**`frontend/vite.config.ts` — add visualizer with env gate:**

```ts
import { visualizer } from 'rollup-plugin-visualizer';

export default defineConfig({
  plugins: [
    react(),
    tailwindcss(),
    process.env.ANALYZE === 'true' && visualizer({ open: true, filename: 'stats.html' }),
  ].filter(Boolean),
  // ... rest unchanged
});
```

**`.gitignore` — add:**

```
stats.html
```

**`frontend/package.json` — add devDependency:**

```json
"rollup-plugin-visualizer": "^5.x"
```

### Expected Vite Output After Implementation

Vite will produce one chunk per lazy-loaded page. Sub-components within each page's directory bundle into that page's chunk automatically:

| Chunk | Contents |
|-------|----------|
| `index.js` | App shell, Login, shared components, React, React Router |
| `Dashboard-[hash].js` | Dashboard.tsx |
| `Scanner-[hash].js` | Scanner/index + ScanConfigPanel + ScanStatusCard + LiveProgressPanel + ResultsPanel |
| `AutoTrading-[hash].js` | AutoTrading/index + OrdersPanel + StrategyPanel + ConfigPanel + AccountPanel + components |
| `ScorecardOverview-[hash].js` | ScorecardOverview.tsx |
| `ScorecardDetail-[hash].js` | ScorecardDetail.tsx |
| *(plus 8 more single-file page chunks)* | |

Vendor libraries (`recharts`, `lightweight-charts`) may be further split by Vite's default vendor chunking heuristic. No action needed — verify with `ANALYZE=true npm run build` after implementation.

---

## Alternatives Considered

### A: All 14 pages lazy (including Login)
Rejected. Login is the first visible page for unauthenticated users. Lazy-loading it delays the authentication UI with no bundle benefit — Login is a small, single-form component.

### B: Selective lazy loading (heavy pages only)
Rejected. Identifying "heavy" pages requires profiling that will become stale as the app grows. Uniform lazy loading of all non-critical-path pages is simpler to maintain and automatically applies to new pages added in the future.

### C: Manual chunk grouping via `rollupOptions.output.manualChunks`
Rejected. Vite's automatic chunking already groups each page's sub-components into that page's chunk. The Scanner sub-panels are only imported by `Scanner/index.tsx`; `ScorecardOverview` and `ScorecardDetail` share no sub-components. `manualChunks` would add configuration complexity with no measurable benefit.

---

## Open Questions (non-blocking)

1. **Error boundary for failed chunk fetches** — If a lazy chunk fails to load (network error, CDN cache bust mid-session), React throws an error that renders a white screen without an error boundary. A `ChunkErrorBoundary` wrapping the Suspense boundary could show a "Reload the page" recovery prompt. This is a good follow-up but out of scope for this issue.

2. **Modulepreload hints** — `React.lazy` chunks can be prefetched on hover for predictable navigation paths (e.g., preload Scanner when the user hovers the sidebar link). Not required here; Vite already injects `<link rel="modulepreload">` for the initial bundle.

---

## Assumptions

- **⚠ Assumption**: The `border-financial-light` Tailwind class resolves correctly in production builds (it is a custom `@theme` color defined in `index.css`). If the spinner ring is invisible, fall back to `border-white/30 border-t-white`.

- **⚠ Assumption**: `useScannerWs` and `useWatchlistLive` use standard `useEffect` mount lifecycle and do not rely on the component tree being synchronously resolved before connecting. Lazy loading only delays when the component _code_ is fetched; once the chunk loads, mount behavior is identical to a static import. If either hook has an unusual initialization pattern, the Suspense boundary placement may need adjustment.

- `rollup-plugin-visualizer` v5.x is compatible with Vite 8.x (it is a Rollup plugin; Vite uses Rollup for production builds).

- Vite 8.x (current in `package.json`) handles dynamic `import()` and chunk splitting natively — no additional plugin needed for lazy loading itself.
