/workspace/markethawk/Docs/superpowers/specs/2026-06-03-ws-url-consolidation-design.md

The spec covers all four key decisions:

1. `wsUrl()` location — exported from `frontend/src/api/client.ts` alongside `apiClient`, sharing direct access to the `API_BASE` constant without an import chain.

2. All 8 WS call sites migrated — per-file migration instructions for every site in `api/scanner.ts` (x2), `hooks/useLiveStockData.ts`, `hooks/useScanTask.ts`, `hooks/useWatchlistLive.ts`, `components/SystemActivityMonitor.tsx`, `components/NewsFeed.tsx`, and `components/TweetFeed.tsx`. Also notes the `useWatchlistLive.ts` protocol bug that gets silently corrected.

3. Regression guard — ESLint `no-restricted-syntax` with two selectors (one for `Literal`, one for `TemplateLiteral > TemplateElement`) targeting `/api/` strings outside `src/api/**`, added to `frontend/eslint.config.js`. Companion Vitest unit test in `frontend/src/api/client.test.ts` validates the helper's output but is not the primary guard.

4. Backend audit scope — documented as "no action required": backend httpx calls target only external Polygon.io URLs, no nginx config exists, `.env.example` mentions are already correct.

The complete inventory of hand-constructed API URLs (8 WS sites + 2 `fetch()` calls in `EdgeExplorer.tsx`) is included in the spec with their current paths verified correct and migration status noted.
