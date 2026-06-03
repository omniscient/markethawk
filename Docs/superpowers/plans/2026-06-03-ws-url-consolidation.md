# Plan: WS URL Consolidation — Issue #158

**Goal:** Centralise all WebSocket and ad-hoc fetch URLs behind shared helpers (`wsUrl()` and `apiClient`) so a single env-var change propagates to every connection, then lock that pattern in with an ESLint rule that fires in CI before tests.
**Architecture:** Frontend only — `src/api/`, `src/hooks/`, `src/components/`, `src/pages/`
**Tech Stack:** Frontend (TypeScript, React, Vitest, ESLint)
**Status:** Draft

---

## File Structure

| File | Change |
|------|--------|
| `frontend/src/api/client.ts` | Add `wsUrl()` helper export |
| `frontend/src/api/client.test.ts` | New: Vitest unit tests for `wsUrl()` |
| `frontend/src/api/scanner.ts` | Replace 2 WS literals (lines 270, 722) with `wsUrl()` |
| `frontend/src/hooks/useLiveStockData.ts` | Replace WS literal with `wsUrl()` |
| `frontend/src/hooks/useScanTask.ts` | Replace WS literal with `wsUrl()` |
| `frontend/src/hooks/useWatchlistLive.ts` | Replace WS literal (fix protocol bug) with `wsUrl()` |
| `frontend/src/components/SystemActivityMonitor.tsx` | Replace WS literal with `wsUrl()` |
| `frontend/src/components/TweetFeed.tsx` | Replace WS literal with `wsUrl()` |
| `frontend/src/components/NewsFeed.tsx` | Replace WS literal + remove `VITE_WS_URL` override with `wsUrl()` |
| `frontend/src/pages/EdgeExplorer.tsx` | Replace two `fetch()` calls with `apiClient.get()` |
| `frontend/eslint.config.js` | Add `no-restricted-syntax` guard block scoped outside `src/api/**` |

---

## Task 1: Add `wsUrl()` helper to `client.ts` and write unit tests

**Files:** `frontend/src/api/client.ts`, `frontend/src/api/client.test.ts`

### Step 1.1 — Write failing test

Create `frontend/src/api/client.test.ts` with:

```typescript
import { wsUrl } from './client';

describe('wsUrl', () => {
  it('generates ws:// URL from relative API_BASE', () => {
    // jsdom environment: window.location.protocol = 'http:', host = 'localhost'
    // VITE_API_BASE_URL is undefined in test → API_BASE falls back to '/api/v1'
    expect(wsUrl('/scanner/ws/runs/abc')).toBe('ws://localhost/api/v1/scanner/ws/runs/abc');
  });

  it('includes dynamic path segments', () => {
    expect(wsUrl('/live/ws/AAPL/minute')).toBe('ws://localhost/api/v1/live/ws/AAPL/minute');
  });
});
```

### Step 1.2 — Verify test fails

```bash
cd /workspace/markethawk/frontend && npx vitest run src/api/client.test.ts
```

Expected failure:

```
FAIL  src/api/client.test.ts
  × generates ws:// URL from relative API_BASE

SyntaxError: The requested module './client' does not provide an export named 'wsUrl'
```

(The function does not exist yet so the import fails or the test throws a "not a function" error.)

### Step 1.3 — Implement `wsUrl()` in `client.ts`

Add the following block immediately after the `API_BASE` constant declaration (before the `apiClient` definition):

```typescript
/**
 * Build a WebSocket URL for the given API path.
 *
 * Handles two cases:
 *  - API_BASE is an absolute URL (e.g. http://staging.example.com/api/v1)
 *    → replaces the http/https scheme with ws/wss.
 *  - API_BASE is a relative path (e.g. /api/v1, the default)
 *    → derives the scheme from window.location.protocol and prepends the current host.
 *
 * Either way, a single env-var change (VITE_API_BASE_URL) propagates to every
 * WebSocket connection automatically.
 */
export function wsUrl(path: string): string {
  if (API_BASE.startsWith('http')) {
    // Absolute URL: http://host/api/v1 → ws://host/api/v1/path
    return API_BASE.replace(/^http/, 'ws') + path;
  }
  // Relative path: /api/v1 → ws://host/api/v1/path
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  return `${protocol}//${window.location.host}${API_BASE}${path}`;
}
```

The full top of `client.ts` after the edit:

```typescript
import axios from 'axios';

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? '/api/v1';

/**
 * Build a WebSocket URL for the given API path.
 * ...
 */
export function wsUrl(path: string): string {
  if (API_BASE.startsWith('http')) {
    return API_BASE.replace(/^http/, 'ws') + path;
  }
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  return `${protocol}//${window.location.host}${API_BASE}${path}`;
}

export const apiClient = axios.create({
  // ...
```

### Step 1.4 — Verify test passes

```bash
cd /workspace/markethawk/frontend && npx vitest run src/api/client.test.ts
```

Expected output:

```
✓ src/api/client.test.ts (2)
  ✓ wsUrl > generates ws:// URL from relative API_BASE
  ✓ wsUrl > includes dynamic path segments

Test Files  1 passed (1)
Tests       2 passed (2)
```

### Step 1.5 — Type check

```bash
cd /workspace/markethawk/frontend && npx tsc --noEmit
```

Expected: zero errors, no output.

### Step 1.6 — Commit

```bash
git add frontend/src/api/client.ts frontend/src/api/client.test.ts
git commit -m "feat(frontend/api): add wsUrl() WebSocket URL helper and unit test"
```

---

## Task 2: Migrate `api/scanner.ts` (2 WS call sites)

**Files:** `frontend/src/api/scanner.ts`

### Step 2.1 — Current hardcoded code (what the ESLint rule will catch)

Line 268–274 (`createScanRunWebSocket`):

```typescript
const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
return new WebSocket(`${protocol}//${window.location.host}/api/v1/scanner/ws/runs/${taskId}`);
```

Line 720–722 (`createScannerWebSocket`):

```typescript
const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
const ws = new WebSocket(`${protocol}//${window.location.host}/api/v1/ws/scanner`);
```

### Step 2.2 — Add import

Add `wsUrl` to the existing import from `./client` at the top of `scanner.ts`. The current import line is:

```typescript
import { apiClient } from './client';
```

Change it to:

```typescript
import { apiClient, wsUrl } from './client';
```

### Step 2.3 — Replace `createScanRunWebSocket` (line ~269)

Replace:

```typescript
const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
return new WebSocket(`${protocol}//${window.location.host}/api/v1/scanner/ws/runs/${taskId}`);
```

With:

```typescript
return new WebSocket(wsUrl(`/scanner/ws/runs/${taskId}`));
```

### Step 2.4 — Replace `createScannerWebSocket` (line ~721)

Replace:

```typescript
const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
const ws = new WebSocket(`${protocol}//${window.location.host}/api/v1/ws/scanner`);
```

With:

```typescript
const ws = new WebSocket(wsUrl('/ws/scanner'));
```

### Step 2.5 — Type check

```bash
cd /workspace/markethawk/frontend && npx tsc --noEmit
```

Expected: zero errors.

### Step 2.6 — Commit

```bash
git add frontend/src/api/scanner.ts
git commit -m "refactor(frontend/api): migrate scanner.ts WS URLs to wsUrl() helper"
```

---

## Task 3: Migrate `hooks/useLiveStockData.ts` and `hooks/useScanTask.ts`

**Files:** `frontend/src/hooks/useLiveStockData.ts`, `frontend/src/hooks/useScanTask.ts`

### Step 3.1 — Current hardcoded code

`useLiveStockData.ts` (lines 24–28):

```typescript
const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
const host = window.location.host;
const wsUrl = `${protocol}//${host}/api/v1/live/ws/${symbol.toUpperCase()}/${resolution}`;
```

`useScanTask.ts` (lines 41–42):

```typescript
const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
const wsUrl = `${protocol}//${window.location.host}/api/v1/live/ws/scan-task/${taskId}`;
```

### Step 3.2 — Add import to `useLiveStockData.ts`

At the top of `useLiveStockData.ts`, add:

```typescript
import { wsUrl } from '../api/client';
```

### Step 3.3 — Replace in `useLiveStockData.ts`

Note: the local variable is named `wsUrl` which shadows the import — rename the import alias or rename the local variable. Rename the local variable to avoid conflict:

Replace these three lines:

```typescript
const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
const host = window.location.host;
const wsUrl = `${protocol}//${host}/api/v1/live/ws/${symbol.toUpperCase()}/${resolution}`;
```

With:

```typescript
const wsEndpoint = wsUrl(`/live/ws/${symbol.toUpperCase()}/${resolution}`);
```

Then update the reference on the `console.log` line and the `new WebSocket(...)` call to use `wsEndpoint` instead of `wsUrl`. Concretely, any occurrence of `wsUrl` in the `connect` function body that referred to the old local variable becomes `wsEndpoint`.

Full replacement block in context (the `connect` function preamble):

```typescript
const connect = () => {
  if (!isMounted) return;
  const wsEndpoint = wsUrl(`/live/ws/${symbol.toUpperCase()}/${resolution}`);
  console.log(`Connecting to live updates: ${wsEndpoint}`);

  // ... remainder of connect() unchanged ...
  const ws = new WebSocket(wsEndpoint);
```

### Step 3.4 — Add import to `useScanTask.ts`

At the top of `useScanTask.ts`, add:

```typescript
import { wsUrl } from '../api/client';
```

### Step 3.5 — Replace in `useScanTask.ts`

Replace:

```typescript
const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
const wsUrl = `${protocol}//${window.location.host}/api/v1/live/ws/scan-task/${taskId}`;

let isMounted = true;

const ws = new WebSocket(wsUrl);
```

With:

```typescript
let isMounted = true;

const ws = new WebSocket(wsUrl(`/live/ws/scan-task/${taskId}`));
```

(The local `wsUrl` variable is removed entirely; the imported function is called inline.)

### Step 3.6 — Type check

```bash
cd /workspace/markethawk/frontend && npx tsc --noEmit
```

Expected: zero errors.

### Step 3.7 — Commit

```bash
git add frontend/src/hooks/useLiveStockData.ts frontend/src/hooks/useScanTask.ts
git commit -m "refactor(frontend/hooks): migrate useLiveStockData and useScanTask to wsUrl()"
```

---

## Task 4: Migrate `hooks/useWatchlistLive.ts`

**Files:** `frontend/src/hooks/useWatchlistLive.ts`

### Step 4.1 — Current hardcoded code with protocol bug

Lines 74–75:

```typescript
const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws';  // BUG: missing colon
const ws = new WebSocket(`${protocol}://${window.location.host}/api/v1/live/ws/watchlist`);
```

The ternary returns `'wss'` / `'ws'` (no trailing colon), then the template uses `://`. This produces `wss://host/...` which happens to work in modern browsers because they parse it correctly, but the intent is inconsistent with all other sites (which use `'wss:'` + `//`). `wsUrl()` corrects this silently.

### Step 4.2 — Add import

At the top of `useWatchlistLive.ts`, add:

```typescript
import { wsUrl } from '../api/client';
```

### Step 4.3 — Replace

Replace:

```typescript
const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws';
const ws = new WebSocket(`${protocol}://${window.location.host}/api/v1/live/ws/watchlist`);
```

With:

```typescript
const ws = new WebSocket(wsUrl('/live/ws/watchlist'));
```

### Step 4.4 — Type check

```bash
cd /workspace/markethawk/frontend && npx tsc --noEmit
```

Expected: zero errors.

### Step 4.5 — Commit

```bash
git add frontend/src/hooks/useWatchlistLive.ts
git commit -m "refactor(frontend/hooks): migrate useWatchlistLive to wsUrl() helper"
```

---

## Task 5: Migrate `components/SystemActivityMonitor.tsx` and `components/TweetFeed.tsx`

**Files:** `frontend/src/components/SystemActivityMonitor.tsx`, `frontend/src/components/TweetFeed.tsx`

### Step 5.1 — Current hardcoded code

`SystemActivityMonitor.tsx` (lines 24–27):

```typescript
const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
const host = window.location.host;
ws = new WebSocket(`${protocol}//${host}/api/v1/system/ws/tasks`);
```

`TweetFeed.tsx` (lines 28–30):

```typescript
const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
const host = window.location.host;
const WS_URL = `${protocol}//${host}/api/v1/tweets/feed`;
```

### Step 5.2 — Add import to `SystemActivityMonitor.tsx`

```typescript
import { wsUrl } from '../api/client';
```

### Step 5.3 — Replace in `SystemActivityMonitor.tsx`

Replace:

```typescript
const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
const host = window.location.host;
ws = new WebSocket(`${protocol}//${host}/api/v1/system/ws/tasks`);
```

With:

```typescript
ws = new WebSocket(wsUrl('/system/ws/tasks'));
```

### Step 5.4 — Add import to `TweetFeed.tsx`

```typescript
import { wsUrl } from '../api/client';
```

### Step 5.5 — Replace in `TweetFeed.tsx`

Replace:

```typescript
const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
const host = window.location.host;
const WS_URL = `${protocol}//${host}/api/v1/tweets/feed`;
// ...
const connectWs = () => {
  if (!isMounted) return;
  if (ws.current) ws.current.close();
```

With:

```typescript
const WS_URL = wsUrl('/tweets/feed');

let reconnectTimer: number | undefined;
let isMounted = true;

const connectWs = () => {
  if (!isMounted) return;
  if (ws.current) ws.current.close();
```

(The `protocol` and `host` local variables are removed; `WS_URL` is now assigned via `wsUrl()`.)

Then update every usage of `new WebSocket(WS_URL)` inside `connectWs` — it is already correct because `WS_URL` is still the variable name, just computed differently.

### Step 5.6 — Type check

```bash
cd /workspace/markethawk/frontend && npx tsc --noEmit
```

Expected: zero errors.

### Step 5.7 — Commit

```bash
git add frontend/src/components/SystemActivityMonitor.tsx frontend/src/components/TweetFeed.tsx
git commit -m "refactor(frontend/components): migrate SystemActivityMonitor and TweetFeed to wsUrl()"
```

---

## Task 6: Migrate `components/NewsFeed.tsx` — remove `VITE_WS_URL` override

**Files:** `frontend/src/components/NewsFeed.tsx`

### Step 6.1 — Current hardcoded code

Lines 50–52:

```typescript
const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
const host = window.location.host;
const WS_URL = import.meta.env.VITE_WS_URL || `${protocol}//${host}/api/v1/news/ws`;
```

The `VITE_WS_URL` env override exists as a workaround for the missing base — once `wsUrl()` derives the base from `VITE_API_BASE_URL`, the override is redundant and potentially misleading. It must be removed.

### Step 6.2 — Add import

```typescript
import { wsUrl } from '../api/client';
```

### Step 6.3 — Replace

Replace:

```typescript
const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
const host = window.location.host;
const WS_URL = import.meta.env.VITE_WS_URL || `${protocol}//${host}/api/v1/news/ws`;
```

With:

```typescript
const WS_URL = wsUrl('/news/ws');
```

### Step 6.4 — Verify `VITE_WS_URL` not referenced elsewhere

```bash
grep -r "VITE_WS_URL" /workspace/markethawk/frontend/src/
```

Expected: no output (the only usage was in `NewsFeed.tsx` and it is now removed).

### Step 6.5 — Type check

```bash
cd /workspace/markethawk/frontend && npx tsc --noEmit
```

Expected: zero errors.

### Step 6.6 — Commit

```bash
git add frontend/src/components/NewsFeed.tsx
git commit -m "refactor(frontend/components): migrate NewsFeed to wsUrl(), drop VITE_WS_URL override"
```

---

## Task 7: Migrate `pages/EdgeExplorer.tsx` — replace `fetch()` with `apiClient.get()`

**Files:** `frontend/src/pages/EdgeExplorer.tsx`

### Step 7.1 — Current hardcoded code

Lines 62 and 76:

```typescript
const response = await fetch(`/api/v1/scanner/edge-stats?${params.toString()}`);
if (!response.ok) return [];
return response.json();
```

```typescript
const response = await fetch(`/api/v1/scanner/edge-distribution?${params.toString()}`);
if (!response.ok) return { events: [] };
return response.json();
```

These bypass `apiClient` entirely, losing auth interceptors and the shared base URL.

### Step 7.2 — Add import

`apiClient` is not currently imported in `EdgeExplorer.tsx`. Add it to the existing API import line. Current:

```typescript
import { fetchScannerConfigs, getSignalQualityDistribution } from '../api/scanner';
```

Add a second import line:

```typescript
import { apiClient } from '../api/client';
```

### Step 7.3 — Replace `edge-stats` fetch

Replace:

```typescript
const response = await fetch(`/api/v1/scanner/edge-stats?${params.toString()}`);
if (!response.ok) return [];
return response.json();
```

With:

```typescript
const response = await apiClient.get(`/scanner/edge-stats?${params.toString()}`);
return response.data;
```

(`apiClient` baseURL is `/api/v1`, so the path is `/scanner/edge-stats`. Axios throws on non-2xx responses, so the `if (!response.ok)` guard is replaced by the React Query error boundary. Return `response.data` directly — no `.json()` needed since Axios parses JSON automatically.)

### Step 7.4 — Replace `edge-distribution` fetch

Replace:

```typescript
const response = await fetch(`/api/v1/scanner/edge-distribution?${params.toString()}`);
if (!response.ok) return { events: [] };
return response.json();
```

With:

```typescript
const response = await apiClient.get(`/scanner/edge-distribution?${params.toString()}`);
return response.data;
```

### Step 7.5 — Type check

```bash
cd /workspace/markethawk/frontend && npx tsc --noEmit
```

Expected: zero errors.

### Step 7.6 — Commit

```bash
git add frontend/src/pages/EdgeExplorer.tsx
git commit -m "refactor(frontend/pages): replace EdgeExplorer fetch() with apiClient"
```

---

## Task 8: Add ESLint `no-restricted-syntax` guard

**Files:** `frontend/eslint.config.js`

### Step 8.1 — Verify lint is currently clean (before adding the rule)

Run lint on the non-api sources to confirm there are no pre-existing issues after all migrations:

```bash
cd /workspace/markethawk/frontend && npm run lint
```

Expected: zero errors (all hardcoded `/api/` strings have been removed from hooks, components, and pages in Tasks 2–7; the remaining `/api/` strings live inside `src/api/**` which the new rule will exclude).

### Step 8.2 — Add the guard rule block to `eslint.config.js`

Append a **new config block** after the existing TypeScript+React block. The new block uses `ignores: ['src/api/**']` so the `src/api/` layer (which legitimately constructs paths like `/api/v1/...`) is exempt.

Current `eslint.config.js` ends with:

```javascript
  // TypeScript + React files
  {
    files: ['src/**/*.{ts,tsx}'],
    // ...
    rules: {
      // ...
      '@typescript-eslint/no-unused-vars': ['error', { argsIgnorePattern: '^_', varsIgnorePattern: '^_' }],
    },
  },
]
```

Add immediately before the closing `]`:

```javascript
  // Regression guard: ban raw /api/ strings outside the api/ layer.
  // All WS and HTTP URLs must go through wsUrl() or apiClient so a single
  // env-var change propagates everywhere.
  {
    files: ['src/**/*.{ts,tsx}'],
    ignores: ['src/api/**'],
    rules: {
      'no-restricted-syntax': [
        'error',
        {
          selector: "Literal[value=/\\/api\\//]",
          message:
            "Raw /api/ string detected outside src/api/**. Use wsUrl() or apiClient instead.",
        },
        {
          selector: "TemplateLiteral > TemplateElement[value.raw=/\\/api\\//]",
          message:
            "Raw /api/ in template literal outside src/api/**. Use wsUrl() or apiClient instead.",
        },
      ],
    },
  },
```

### Step 8.3 — Verify lint passes with the new rule

```bash
cd /workspace/markethawk/frontend && npm run lint
```

Expected: zero errors. If any `/api/` strings were missed in Tasks 2–7 they will now surface here. Fix any that appear before committing.

### Step 8.4 — Run full test suite to confirm nothing broken

```bash
cd /workspace/markethawk/frontend && npx vitest run
```

Expected: all tests pass, including the two new `client.test.ts` tests from Task 1.

### Step 8.5 — Final type check

```bash
cd /workspace/markethawk/frontend && npx tsc --noEmit
```

Expected: zero errors.

### Step 8.6 — Commit

```bash
git add frontend/eslint.config.js
git commit -m "feat(frontend/lint): add no-restricted-syntax guard for raw /api/ strings"
```

---

## Summary

| Task | Commit message | Files changed |
|------|---------------|---------------|
| 1 | `feat(frontend/api): add wsUrl() WebSocket URL helper and unit test` | `client.ts`, `client.test.ts` |
| 2 | `refactor(frontend/api): migrate scanner.ts WS URLs to wsUrl() helper` | `scanner.ts` |
| 3 | `refactor(frontend/hooks): migrate useLiveStockData and useScanTask to wsUrl()` | `useLiveStockData.ts`, `useScanTask.ts` |
| 4 | `refactor(frontend/hooks): migrate useWatchlistLive to wsUrl() helper` | `useWatchlistLive.ts` |
| 5 | `refactor(frontend/components): migrate SystemActivityMonitor and TweetFeed to wsUrl()` | `SystemActivityMonitor.tsx`, `TweetFeed.tsx` |
| 6 | `refactor(frontend/components): migrate NewsFeed to wsUrl(), drop VITE_WS_URL override` | `NewsFeed.tsx` |
| 7 | `refactor(frontend/pages): replace EdgeExplorer fetch() with apiClient` | `EdgeExplorer.tsx` |
| 8 | `feat(frontend/lint): add no-restricted-syntax guard for raw /api/ strings` | `eslint.config.js` |

### Acceptance criteria verification

- **Complete inventory** — all 8 WS sites and 2 fetch sites documented and migrated.
- **Single source of truth** — `wsUrl()` in `client.ts` derives its base from `API_BASE`, which is set by `VITE_API_BASE_URL`. One env-var change now covers all WebSocket connections.
- **Regression guard** — the ESLint `no-restricted-syntax` rule in Task 8 fires on any future `/api/` string literal outside `src/api/**`, catching drift at lint time in CI.
- **Bug fix** — `useWatchlistLive.ts` protocol inconsistency (`'wss'` without colon) is silently corrected by `wsUrl()`.
- **Cleanup** — `VITE_WS_URL` env override in `NewsFeed.tsx` removed; it was a workaround for the missing base and is now obsolete.
- **PR reference** — each commit message is linked to the branch for issue #158.
