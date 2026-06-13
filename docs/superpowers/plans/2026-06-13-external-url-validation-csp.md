# External URL Validation and Content Security Policy

**Date:** 2026-06-13  
**Issue:** #381  
**Epic:** #372 (Defensive Security Review 2026-06-12)  
**Branch:** refine/issue-381--security--f-front-01--external-content-  
**Status:** Plan

---

## Goal

Eliminate open-redirect / javascript-scheme injection vectors in four frontend
locations that bind third-party URLs to `href`/`src`/`openWindow` without
validation, and add a Content Security Policy header from Caddy as a
second line of defence for any future XSS.

---

## Architecture

A thin shared utility (`url.ts`) performs scheme and allowlist validation.
The three component-level fixes import and call that utility; the two
point-fixes (`sw.js`, `GlobalErrorToast.tsx`) are self-contained. The CSP
header is a Caddy configuration change — no backend or React changes.

```
frontend/src/utils/url.ts       ← new shared validator (pure function)
frontend/src/utils/url.test.ts  ← new unit tests
frontend/src/components/NewsFeed.tsx        ← apply safeExternalUrl
frontend/src/components/ScannerResults.tsx  ← apply safeExternalUrl + allowlist
frontend/public/sw.js                       ← same-origin guard
frontend/src/components/ui/GlobalErrorToast.tsx  ← rel="noopener noreferrer"
caddy/Caddyfile                             ← add CSP header
```

---

## Tech Stack

**Frontend:** React 18 + TypeScript + Vitest + React Testing Library  
**Test runner:** `npx vitest run` (jsdom environment)  
**Type check:** `npx tsc --noEmit`  
**Infrastructure:** Caddy (reverse proxy / header injection)

---

## File Structure

| File | Change |
|------|--------|
| `frontend/src/utils/url.ts` | **New** — `safeExternalUrl()` function |
| `frontend/src/utils/url.test.ts` | **New** — 10 unit tests |
| `frontend/src/components/NewsFeed.tsx` | **Modify** — apply validation to `article_url`, `image_url` |
| `frontend/src/components/NewsFeed.test.tsx` | **New** — 4 component tests |
| `frontend/src/components/ScannerResults.tsx` | **Modify** — apply validation + allowlist to `tweet_url` |
| `frontend/src/components/ScannerResults.test.tsx` | **New** — 4 component tests |
| `frontend/public/sw.js` | **Modify** — same-origin guard on `clients.openWindow` |
| `frontend/src/components/ui/GlobalErrorToast.tsx` | **Modify** — add `noopener` to `rel` attribute |
| `caddy/Caddyfile` | **Modify** — add `Content-Security-Policy` header |

---

## Tasks

---

### Task 1 — URL Validation Utility (`url.ts`)

**Files:** `frontend/src/utils/url.test.ts`, `frontend/src/utils/url.ts`

**Why first:** Every component fix imports from this module. Establishing it with
full unit-test coverage before touching components keeps each subsequent task
small and independently verifiable.

#### Step 1.1 — Write failing tests

Create `frontend/src/utils/url.test.ts`:

```typescript
import { describe, it, expect } from 'vitest';
import { safeExternalUrl } from './url';

describe('safeExternalUrl — null / undefined / empty inputs', () => {
  it('returns null for undefined', () => {
    expect(safeExternalUrl(undefined)).toBeNull();
  });
  it('returns null for null', () => {
    expect(safeExternalUrl(null)).toBeNull();
  });
  it('returns null for empty string', () => {
    expect(safeExternalUrl('')).toBeNull();
  });
});

describe('safeExternalUrl — scheme enforcement', () => {
  it('accepts a valid https: URL and returns it unchanged', () => {
    expect(safeExternalUrl('https://example.com/path?q=1')).toBe('https://example.com/path?q=1');
  });
  it('rejects javascript: scheme', () => {
    expect(safeExternalUrl('javascript:alert(1)')).toBeNull();
  });
  it('rejects http: scheme', () => {
    expect(safeExternalUrl('http://example.com/article')).toBeNull();
  });
  it('rejects data: scheme', () => {
    expect(safeExternalUrl('data:text/html,<h1>hi</h1>')).toBeNull();
  });
  it('rejects a string that is not a valid URL (new URL() throws)', () => {
    expect(safeExternalUrl('not-a-url')).toBeNull();
  });
});

describe('safeExternalUrl — allowedHosts', () => {
  const TWEET_HOSTS = ['twitter.com', 'x.com', 't.co'];

  it('accepts exact host match', () => {
    expect(
      safeExternalUrl('https://twitter.com/user/status/123', { allowedHosts: TWEET_HOSTS })
    ).toBe('https://twitter.com/user/status/123');
  });
  it('accepts subdomain of an allowed host (*.twitter.com)', () => {
    expect(
      safeExternalUrl('https://mobile.twitter.com/status/123', { allowedHosts: TWEET_HOSTS })
    ).toBe('https://mobile.twitter.com/status/123');
  });
  it('rejects a host not in the allowlist', () => {
    expect(
      safeExternalUrl('https://evil.com/phish', { allowedHosts: TWEET_HOSTS })
    ).toBeNull();
  });
  it('rejects a host that contains an allowed value as a suffix without dot boundary (nottwitter.com)', () => {
    expect(
      safeExternalUrl('https://nottwitter.com/status/123', { allowedHosts: TWEET_HOSTS })
    ).toBeNull();
  });
});
```

#### Step 1.2 — Verify tests fail

```bash
cd /workspace/markethawk/frontend
npx vitest run src/utils/url.test.ts 2>&1 | tail -20
```

Expected: `Cannot find module './url'` errors (file does not yet exist).

#### Step 1.3 — Implement `url.ts`

Create `frontend/src/utils/url.ts`:

```typescript
export function safeExternalUrl(
  url: string | undefined | null,
  opts?: { allowedHosts?: string[] }
): string | null {
  if (!url) return null;
  try {
    const parsed = new URL(url);
    if (parsed.protocol !== 'https:') return null;
    if (opts?.allowedHosts) {
      const host = parsed.hostname;
      const allowed = opts.allowedHosts.some(
        (h) => host === h || host.endsWith(`.${h}`)
      );
      if (!allowed) return null;
    }
    return url;
  } catch {
    return null;
  }
}
```

#### Step 1.4 — Verify tests pass

```bash
npx vitest run src/utils/url.test.ts 2>&1 | tail -10
```

Expected output:
```
✓ src/utils/url.test.ts (12)
Test Files  1 passed (1)
Tests  12 passed (12)
```

#### Step 1.5 — TypeScript check

```bash
npx tsc --noEmit 2>&1
```

Expected: no errors.

#### Step 1.6 — Coverage gate

```bash
npx vitest run --coverage 2>&1 | tail -20
```

Verify all four thresholds (statements ≥30, branches ≥27, functions ≥22, lines ≥30) still pass.
The new fully-tested `url.ts` will push coverage up, not down.

#### Step 1.7 — Commit

```bash
git add frontend/src/utils/url.ts frontend/src/utils/url.test.ts
git commit -m "feat(security): add safeExternalUrl utility for external URL validation (#381)"
```

---

### Task 2 — `NewsFeed.tsx` — apply scheme-only validation

**Files:** `frontend/src/components/NewsFeed.test.tsx`, `frontend/src/components/NewsFeed.tsx`

**Context:** The `renderArticle()` function (lines 130-178) binds `article.article_url`
directly to `href` and `article.image_url` directly to `img src`. After this task,
unsafe URLs render as plain text / no thumbnail.

#### Step 2.1 — Write failing component tests

Create `frontend/src/components/NewsFeed.test.tsx`:

```tsx
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import NewsFeed from './NewsFeed';

// Prevent real HTTP and WebSocket traffic in tests
vi.mock('../api/news', () => ({
  fetchRecentNews: vi.fn(),
  triggerNewsRefresh: vi.fn().mockResolvedValue(undefined),
}));
vi.mock('../api/client', () => ({
  wsUrl: vi.fn(() => 'ws://localhost/news/ws'),
  apiClient: { get: vi.fn() },
}));

// jsdom has no WebSocket — stub it so the useEffect does not throw
const mockWs = {
  addEventListener: vi.fn(),
  removeEventListener: vi.fn(),
  onopen: null as unknown,
  onmessage: null as unknown,
  onclose: null as unknown,
  onerror: null as unknown,
  readyState: 3,
  close: vi.fn(),
};
vi.stubGlobal('WebSocket', vi.fn(() => mockWs));

import { fetchRecentNews } from '../api/news';
const mockFetch = fetchRecentNews as ReturnType<typeof vi.fn>;

const BASE_ARTICLE = {
  id: 'a1',
  title: 'Safe News Article',
  published_utc: '2026-06-13T10:00:00Z',
  provider: 'Reuters',
  author: null,
  article_url: 'https://reuters.com/article/1',
  image_url: 'https://reuters.com/img/1.jpg',
  tickers: ['AAPL'],
  keywords: [],
  description: null,
};

describe('NewsFeed — URL validation (NewsFeed.tsx renderArticle)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockFetch.mockResolvedValue([]);
  });
  afterEach(() => vi.clearAllMocks());

  it('renders a clickable link when article_url is valid https', async () => {
    mockFetch.mockResolvedValueOnce([BASE_ARTICLE]);
    render(<NewsFeed />);
    await waitFor(() => {
      const link = screen.getByRole('link', { name: /Safe News Article/i });
      expect(link).toHaveAttribute('href', 'https://reuters.com/article/1');
      expect(link).toHaveAttribute('rel', 'noopener noreferrer');
    });
  });

  it('renders article title as plain text (no link) when article_url is javascript: scheme', async () => {
    mockFetch.mockResolvedValueOnce([
      { ...BASE_ARTICLE, article_url: 'javascript:alert(1)' },
    ]);
    render(<NewsFeed />);
    await waitFor(() => {
      expect(screen.queryByRole('link', { name: /Safe News Article/i })).toBeNull();
      expect(screen.getByText('Safe News Article')).toBeInTheDocument();
    });
  });

  it('renders <img> thumbnail when image_url is valid https', async () => {
    mockFetch.mockResolvedValueOnce([BASE_ARTICLE]);
    render(<NewsFeed />);
    await waitFor(() => {
      const img = screen.getByRole('img');
      expect(img).toHaveAttribute('src', 'https://reuters.com/img/1.jpg');
    });
  });

  it('omits <img> thumbnail when image_url scheme is http (not https)', async () => {
    mockFetch.mockResolvedValueOnce([
      { ...BASE_ARTICLE, image_url: 'http://cdn.example.com/img.jpg' },
    ]);
    render(<NewsFeed />);
    await waitFor(() => {
      expect(screen.queryByRole('img')).toBeNull();
    });
  });
});
```

#### Step 2.2 — Verify tests fail

```bash
npx vitest run src/components/NewsFeed.test.tsx 2>&1 | tail -20
```

Expected: link tests pass vacuously (link is rendered), but test 2 fails because
the `<a>` is present even for `javascript:` URL. Tests 3 and 4 will also fail
since `<img>` is always rendered when `image_url` is truthy.

#### Step 2.3 — Modify `NewsFeed.tsx`

In `frontend/src/components/NewsFeed.tsx`, add the import at the top of the file
after the existing imports:

```typescript
import { safeExternalUrl } from '../utils/url';
```

Replace the `renderArticle` function body (lines 130-178). The change is confined
to the variable extraction at the top and the JSX that binds those variables:

**Before** (lines 130-178 of `renderArticle`):
```tsx
const renderArticle = (article: NewsArticle) => (
    <div
        key={article.id}
        className="bg-gray-800/50 rounded-lg p-4 border border-gray-700 hover:border-gray-600 transition-colors animate-fade-in"
    >
        <div className="flex justify-between items-start mb-2">
            <div className="flex flex-wrap gap-1 mb-1">
                {article.tickers?.slice(0, 3).map(t => (
                    <span key={t} className="text-xs font-mono bg-financial-blue/20 text-financial-blue px-1.5 rounded">
                        {t}
                    </span>
                ))}
                {article.tickers && article.tickers.length > 3 && (
                    <span className="text-xs font-mono bg-gray-700 text-gray-300 px-1.5 rounded">
                        +{article.tickers.length - 3}
                    </span>
                )}
            </div>
            <div className="text-xs text-gray-400 flex items-center whitespace-nowrap ml-2">
                <Clock className="w-3 h-3 mr-1" />
                {formatDistanceToNow(parsePublishedUtc(article.published_utc), { addSuffix: true })}
            </div>
        </div>

        <a
            href={article.article_url}
            target="_blank"
            rel="noopener noreferrer"
            className="font-medium text-financial-light hover:text-white transition-colors group flex items-start"
        >
            <div className="flex-1">
                <h4 className="leading-snug line-clamp-2">{article.title}</h4>
                <p className="text-xs text-gray-400 mt-2 flex items-center">
                    <span className="truncate max-w-[150px] inline-block">{article.provider || article.author || 'Unknown source'}</span>
                    <ExternalLink className="w-3 h-3 ml-1 opacity-0 group-hover:opacity-100 transition-opacity" />
                </p>
            </div>
            {article.image_url && (
                <div className="ml-3 shrink-0">
                    <img
                        src={article.image_url}
                        alt=""
                        className="w-16 h-12 object-cover rounded shadow-sm border border-gray-700"
                    />
                </div>
            )}
        </a>
    </div>
);
```

**After:**
```tsx
const renderArticle = (article: NewsArticle) => {
    const safeArticleUrl = safeExternalUrl(article.article_url);
    const safeImageUrl   = safeExternalUrl(article.image_url);
    const titleContent = (
        <div className="flex-1">
            <h4 className="leading-snug line-clamp-2">{article.title}</h4>
            <p className="text-xs text-gray-400 mt-2 flex items-center">
                <span className="truncate max-w-[150px] inline-block">{article.provider || article.author || 'Unknown source'}</span>
                {safeArticleUrl && <ExternalLink className="w-3 h-3 ml-1 opacity-0 group-hover:opacity-100 transition-opacity" />}
            </p>
        </div>
    );
    const thumbnail = safeImageUrl ? (
        <div className="ml-3 shrink-0">
            <img
                src={safeImageUrl}
                alt=""
                className="w-16 h-12 object-cover rounded shadow-sm border border-gray-700"
            />
        </div>
    ) : null;

    return (
        <div
            key={article.id}
            className="bg-gray-800/50 rounded-lg p-4 border border-gray-700 hover:border-gray-600 transition-colors animate-fade-in"
        >
            <div className="flex justify-between items-start mb-2">
                <div className="flex flex-wrap gap-1 mb-1">
                    {article.tickers?.slice(0, 3).map(t => (
                        <span key={t} className="text-xs font-mono bg-financial-blue/20 text-financial-blue px-1.5 rounded">
                            {t}
                        </span>
                    ))}
                    {article.tickers && article.tickers.length > 3 && (
                        <span className="text-xs font-mono bg-gray-700 text-gray-300 px-1.5 rounded">
                            +{article.tickers.length - 3}
                        </span>
                    )}
                </div>
                <div className="text-xs text-gray-400 flex items-center whitespace-nowrap ml-2">
                    <Clock className="w-3 h-3 mr-1" />
                    {formatDistanceToNow(parsePublishedUtc(article.published_utc), { addSuffix: true })}
                </div>
            </div>

            {safeArticleUrl ? (
                <a
                    href={safeArticleUrl}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="font-medium text-financial-light hover:text-white transition-colors group flex items-start"
                >
                    {titleContent}
                    {thumbnail}
                </a>
            ) : (
                <div className="font-medium text-financial-light flex items-start">
                    {titleContent}
                    {thumbnail}
                </div>
            )}
        </div>
    );
};
```

#### Step 2.4 — Verify tests pass

```bash
npx vitest run src/components/NewsFeed.test.tsx 2>&1 | tail -10
```

Expected:
```
✓ src/components/NewsFeed.test.tsx (4)
Test Files  1 passed (1)
Tests  4 passed (4)
```

#### Step 2.5 — TypeScript check

```bash
npx tsc --noEmit 2>&1
```

Expected: no errors.

#### Step 2.6 — Commit

```bash
git add frontend/src/components/NewsFeed.tsx frontend/src/components/NewsFeed.test.tsx
git commit -m "fix(security): validate article_url and image_url before binding in NewsFeed (#381)"
```

---

### Task 3 — `ScannerResults.tsx` — apply scheme + allowlist validation

**Files:** `frontend/src/components/ScannerResults.test.tsx`, `frontend/src/components/ScannerResults.tsx`

**Context:** Lines 240-250 bind `event.metadata.tweet_url` directly to `href`. The
fix adds an allowlist (`twitter.com`, `x.com`, `t.co`) via `safeExternalUrl`.

#### Step 3.1 — Write failing component tests

Create `frontend/src/components/ScannerResults.test.tsx`:

```tsx
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import ScannerResults from './ScannerResults';
import type { ScannerEvent } from '../api/scanner';

// Stub sub-components that are irrelevant to URL validation
vi.mock('./Ticker', () => ({
  default: ({ ticker }: { ticker: string }) => <span data-testid="ticker">{ticker}</span>,
}));
vi.mock('./ReviewControls', () => ({
  default: () => <div data-testid="review-controls" />,
}));
vi.mock('./ui/Card', () => ({
  default: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));

const BASE_RESULTS = {
  scan_id: 'test-scan-1',
  status: 'completed',
  stocks_scanned: 1,
  events_detected: 1,
  execution_time_ms: 100,
  events: [] as ScannerEvent[],
};

const SOCIAL_EVENT: ScannerEvent = {
  id: 1,
  uuid: 'uuid-1',
  ticker: 'AAPL',
  event_date: '2026-06-13',
  scanner_type: 'social_callout',
  severity: 'medium',
  indicators: {},
  criteria_met: {},
  metadata: {
    tweet_url: 'https://twitter.com/user/status/123',
    source_account: 'testaccount',
  },
  created_at: '2026-06-13T10:00:00Z',
  updated_at: '2026-06-13T10:00:00Z',
};

describe('ScannerResults — tweet_url validation', () => {
  it('renders a link for a valid twitter.com tweet_url', () => {
    render(<ScannerResults results={{ ...BASE_RESULTS, events: [SOCIAL_EVENT] }} />);
    const link = screen.getByRole('link', { name: /@testaccount/i });
    expect(link).toHaveAttribute('href', 'https://twitter.com/user/status/123');
    expect(link).toHaveAttribute('rel', 'noopener noreferrer');
  });

  it('renders plain text @label (no link) when tweet_url uses javascript: scheme', () => {
    render(<ScannerResults results={{
      ...BASE_RESULTS,
      events: [{
        ...SOCIAL_EVENT,
        metadata: { tweet_url: 'javascript:alert(1)', source_account: 'testaccount' },
      }],
    }} />);
    expect(screen.queryByRole('link', { name: /@testaccount/i })).toBeNull();
    expect(screen.getByText('@testaccount')).toBeInTheDocument();
  });

  it('renders plain text @label (no link) when tweet_url host is off-allowlist', () => {
    render(<ScannerResults results={{
      ...BASE_RESULTS,
      events: [{
        ...SOCIAL_EVENT,
        metadata: { tweet_url: 'https://evil.com/phish', source_account: 'badactor' },
      }],
    }} />);
    expect(screen.queryByRole('link', { name: /@badactor/i })).toBeNull();
    expect(screen.getByText('@badactor')).toBeInTheDocument();
  });

  it('accepts x.com as an allowed domain', () => {
    render(<ScannerResults results={{
      ...BASE_RESULTS,
      events: [{
        ...SOCIAL_EVENT,
        metadata: { tweet_url: 'https://x.com/user/status/456', source_account: 'xaccount' },
      }],
    }} />);
    const link = screen.getByRole('link', { name: /@xaccount/i });
    expect(link).toHaveAttribute('href', 'https://x.com/user/status/456');
  });
});
```

#### Step 3.2 — Verify tests fail

```bash
npx vitest run src/components/ScannerResults.test.tsx 2>&1 | tail -20
```

Expected: tests 2 and 3 fail because a link is always rendered when
`event.metadata?.tweet_url` is truthy, regardless of scheme or host.

#### Step 3.3 — Modify `ScannerResults.tsx`

Add the import at the top of `frontend/src/components/ScannerResults.tsx`
after the existing imports:

```typescript
import { safeExternalUrl } from '../utils/url';
```

Add the constant just before the component function body:

```typescript
const TWEET_HOSTS = ['twitter.com', 'x.com', 't.co'];
```

Replace lines 240-250 (the tweet URL render block):

**Before:**
```tsx
{event.scanner_type === 'social_callout' && Boolean(event.metadata?.tweet_url) && (
  <a
    href={event.metadata.tweet_url as string}
    target="_blank"
    rel="noopener noreferrer"
    className="text-[10px] text-financial-blue hover:underline truncate max-w-[120px]"
    title={`@${(event.metadata?.source_account as string) ?? ''}`}
  >
    @{(event.metadata?.source_account as string) ?? 'unknown'}
  </a>
)}
```

**After:**
```tsx
{event.scanner_type === 'social_callout' && (() => {
  const safeTweetUrl = safeExternalUrl(
    event.metadata?.tweet_url as string | undefined,
    { allowedHosts: TWEET_HOSTS }
  );
  const account = (event.metadata?.source_account as string) ?? 'unknown';
  return safeTweetUrl ? (
    <a
      href={safeTweetUrl}
      target="_blank"
      rel="noopener noreferrer"
      className="text-[10px] text-financial-blue hover:underline truncate max-w-[120px]"
      title={`@${account}`}
    >
      @{account}
    </a>
  ) : (
    Boolean(event.metadata?.tweet_url) && (
      <span
        className="text-[10px] text-gray-400 truncate max-w-[120px]"
        title={`@${account}`}
      >
        @{account}
      </span>
    )
  );
})()}
```

#### Step 3.4 — Verify tests pass

```bash
npx vitest run src/components/ScannerResults.test.tsx 2>&1 | tail -10
```

Expected:
```
✓ src/components/ScannerResults.test.tsx (4)
Test Files  1 passed (1)
Tests  4 passed (4)
```

#### Step 3.5 — TypeScript check

```bash
npx tsc --noEmit 2>&1
```

Expected: no errors.

#### Step 3.6 — Full test + coverage run

```bash
npx vitest run --coverage 2>&1 | tail -20
```

Verify all four thresholds pass (statements ≥30, branches ≥27, functions ≥22, lines ≥30).

#### Step 3.7 — Commit

```bash
git add frontend/src/components/ScannerResults.tsx frontend/src/components/ScannerResults.test.tsx
git commit -m "fix(security): validate tweet_url with scheme+allowlist in ScannerResults (#381)"
```

---

### Task 4 — `sw.js` — same-origin guard on `clients.openWindow`

**Files:** `frontend/public/sw.js`

**Context:** Line 38 passes `notification.data?.url` directly to `clients.openWindow`.
An attacker-influenced push payload with an absolute off-origin URL would navigate
the user to an arbitrary site. All backend-generated push notification URLs today
are relative paths (`/alerts`, `/scanner`) so the guard is behaviour-preserving.

`sw.js` is a plain JavaScript service worker — there is no Vitest test runner for
service workers in this project. Verification is by code inspection.

#### Step 4.1 — Modify `sw.js`

Replace lines 35-55 (the `notificationclick` listener) in
`frontend/public/sw.js`:

**Before:**
```js
self.addEventListener('notificationclick', (event) => {
  event.notification.close();

  const urlToOpen = event.notification.data?.url || '/alerts';

  event.waitUntil(
    clients.matchAll({ type: 'window', includeUncontrolled: true }).then((windowClients) => {
      // If a tab is already open at the URL, focus it
      for (let i = 0; i < windowClients.length; i++) {
        const client = windowClients[i];
        if (client.url.includes(urlToOpen) && 'focus' in client) {
          return client.focus();
        }
      }
      // If no tab is open, open a new one
      if (clients.openWindow) {
        return clients.openWindow(urlToOpen);
      }
    })
  );
});
```

**After:**
```js
self.addEventListener('notificationclick', (event) => {
  event.notification.close();

  // Resolve notification URL against our own origin.
  // Relative paths (e.g. '/alerts') resolve to same-origin automatically.
  // Absolute off-origin URLs are rejected and fall back to /alerts.
  let urlToOpen;
  try {
    const raw = event.notification.data?.url || '/alerts';
    const resolved = new URL(raw, self.location.origin);
    urlToOpen = resolved.origin === self.location.origin ? resolved.href : '/alerts';
  } catch {
    urlToOpen = '/alerts';
  }

  event.waitUntil(
    clients.matchAll({ type: 'window', includeUncontrolled: true }).then((windowClients) => {
      // If a tab is already open at the URL, focus it
      for (let i = 0; i < windowClients.length; i++) {
        const client = windowClients[i];
        if (client.url.includes(urlToOpen) && 'focus' in client) {
          return client.focus();
        }
      }
      // If no tab is open, open a new one
      if (clients.openWindow) {
        return clients.openWindow(urlToOpen);
      }
    })
  );
});
```

#### Step 4.2 — Verify no syntax errors

```bash
node --check /workspace/markethawk/frontend/public/sw.js && echo "Syntax OK"
```

Expected: `Syntax OK`

#### Step 4.3 — Commit

```bash
git add frontend/public/sw.js
git commit -m "fix(security): restrict sw.js clients.openWindow to same-origin URLs (#381)"
```

---

### Task 5 — `GlobalErrorToast.tsx` — add `noopener` to rel attribute

**Files:** `frontend/src/components/ui/GlobalErrorToast.tsx`

**Context:** Line 149 has `rel="noreferrer"`. While `noreferrer` implies `noopener`
in modern browsers, the explicit dual-attribute form is the defence-in-depth
best practice per finding F-FRONT-01.

#### Step 5.1 — Apply the one-line fix

In `frontend/src/components/ui/GlobalErrorToast.tsx` at line 149:

**Before:**
```tsx
              rel="noreferrer"
```

**After:**
```tsx
              rel="noopener noreferrer"
```

#### Step 5.2 — TypeScript check

```bash
cd /workspace/markethawk/frontend && npx tsc --noEmit 2>&1
```

Expected: no errors.

#### Step 5.3 — Commit

```bash
git add frontend/src/components/ui/GlobalErrorToast.tsx
git commit -m "fix(security): add noopener to GlobalErrorToast Seq link rel attribute (#381)"
```

---

### Task 6 — Caddy CSP Header

**Files:** `caddy/Caddyfile`

**Context:** No CSP exists today. This task adds the header to the main site block
alongside the existing HSTS header. The directives are chosen to not break
news thumbnails (arbitrary CDNs → `img-src https:`), charts (Recharts inline
styles → `style-src 'unsafe-inline'`), WebSocket (`connect-src wss:`),
and bundled scripts (`script-src 'self'`).

#### Step 6.1 — Modify `caddy/Caddyfile`

In `caddy/Caddyfile`, within the `{$DOMAIN:localhost}` block, add the CSP header
immediately after the existing HSTS header on line 3:

**Before:**
```caddy
{$DOMAIN:localhost} {
    # HSTS: instruct browsers to use HTTPS for this domain for 1 year
    header Strict-Transport-Security "max-age=31536000; includeSubDomains" always

    # Block external access to the Prometheus metrics endpoint.
```

**After:**
```caddy
{$DOMAIN:localhost} {
    # HSTS: instruct browsers to use HTTPS for this domain for 1 year
    header Strict-Transport-Security "max-age=31536000; includeSubDomains" always

    # CSP: second line of defence against XSS and open-redirect injection.
    # img-src includes https: (news thumbnails from arbitrary publisher CDNs).
    # style-src includes 'unsafe-inline' (Tailwind v4 + Recharts inject runtime styles).
    # connect-src includes wss: (WebSocket upgrades via same backend origin).
    header Content-Security-Policy "default-src 'self'; img-src 'self' https: data:; connect-src 'self' wss:; script-src 'self'; style-src 'self' 'unsafe-inline'; font-src 'self' data:; object-src 'none'; base-uri 'self'; frame-ancestors 'self'" always

    # Block external access to the Prometheus metrics endpoint.
```

#### Step 6.2 — Verify Caddy config syntax

```bash
docker-compose exec caddy caddy validate --config /etc/caddy/Caddyfile 2>&1
```

Expected: `Valid configuration` (or similar success message).

If Caddy is not running in the current environment, validate by restarting:

```bash
docker-compose restart caddy 2>&1 | tail -5
docker-compose logs caddy --tail=10 2>&1
```

Expected: no errors in logs, caddy reports it is serving.

#### Step 6.3 — Verify CSP header is present

```bash
curl -sI http://localhost:3333 | grep -i content-security-policy
```

Expected output (single line):
```
content-security-policy: default-src 'self'; img-src 'self' https: data:; connect-src 'self' wss:; script-src 'self'; style-src 'self' 'unsafe-inline'; font-src 'self' data:; object-src 'none'; base-uri 'self'; frame-ancestors 'self'
```

#### Step 6.4 — Commit

```bash
git add caddy/Caddyfile
git commit -m "feat(security): add Content-Security-Policy header via Caddy (#381)"
```

---

## Verification Checklist (post-implementation)

After all six tasks are committed, run these checks to confirm the full issue
is resolved:

```bash
# 1. All unit + component tests pass
cd /workspace/markethawk/frontend
npx vitest run 2>&1 | tail -5

# 2. Coverage thresholds pass
npx vitest run --coverage 2>&1 | grep -E "statements|branches|functions|lines" | tail -4

# 3. TypeScript clean
npx tsc --noEmit 2>&1

# 4. CSP header present on frontend
curl -sI http://localhost:3333 | grep -i content-security-policy

# 5. CSP header present on API path (Caddy applies to all responses)
curl -sI http://localhost:8000/api/health | grep -i content-security-policy

# 6. javascript: URL is not rendered as a link (no clickable href="javascript:…")
#    → confirmed by tests 2.3 and 3.3

# 7. Off-allowlist tweet_url is rendered as plain text
#    → confirmed by test 3.3

# 8. sw.js syntax
node --check frontend/public/sw.js && echo "OK"
```

### Security verification scenarios (manual)

| Scenario | Expected |
|----------|----------|
| `article_url = "javascript:alert(1)"` | Article title rendered as `<div>` text, no `<a>` |
| `article_url = "http://insecure.com/article"` | Same fallback (http: rejected) |
| `article_url = "https://reuters.com/safe"` | Normal `<a href="…">` rendered |
| `image_url = "http://cdn.example.com/img.jpg"` | No `<img>` in rendered output |
| `tweet_url = "https://twitter.com/status/123"` | `<a>` link rendered with correct href |
| `tweet_url = "https://evil.com/phish"` | `@account` rendered as `<span>`, no link |
| `tweet_url = "javascript:alert(1)"` | Same plain text fallback |
| Push notification with off-origin URL | `sw.js` navigates to `/alerts` |
| Any page request | Response carries `Content-Security-Policy` header |
