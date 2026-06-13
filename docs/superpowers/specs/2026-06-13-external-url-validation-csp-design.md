# External URL Validation and Content Security Policy

**Date:** 2026-06-13  
**Issue:** #381  
**Epic:** #372 (Defensive Security Review 2026-06-12)  
**Status:** Spec

---

## Problem

Four locations in the frontend bind external URLs from third-party data sources
directly to `href`/`src` attributes or pass them to `clients.openWindow` without
validation. React escapes text nodes so stored-XSS is not currently exploitable,
but a `javascript:`- or `data:`-scheme URL in an `href` or `src` is a live
open-redirect / scheme injection vector if the upstream data is ever
attacker-influenced. No CSP exists, so a future XSS would have no second line of
defence.

Affected locations (from security review finding F-FRONT-01):
- `frontend/src/components/NewsFeed.tsx:154-176` — `article_url` and `image_url` from Polygon.io news API
- `frontend/src/components/ScannerResults.tsx:240-250` — `metadata.tweet_url` from tweet-monitor service
- `frontend/public/sw.js:38` — `notification.data?.url` passed to `clients.openWindow`
- `frontend/src/components/ui/GlobalErrorToast.tsx:149` — `rel="noreferrer"` missing `noopener`

---

## Requirements

1. External URLs must be validated before use in `href`, `src`, or `openWindow`.
2. For `article_url` and `image_url` (Polygon.io, arbitrary publishers): enforce
   `https:`-scheme-only. Any URL whose scheme is not `https:` is rejected.
3. For `tweet_url` (tweet-monitor, known source): enforce `https:`-scheme **and**
   domain allowlist — only `twitter.com`, `x.com`, and `t.co` (exact host or
   `*.`-subdomain) are accepted.
4. When a URL fails validation: render the news article title as plain text (not a
   link) and omit the `<img>` thumbnail. The tweet source label falls back to
   plain text. Nothing is silently swallowed — the component renders gracefully.
5. `sw.js` `clients.openWindow` must only navigate to same-origin URLs. If the
   push-notification URL is absolute and off-origin, fall back to `/alerts`.
6. `GlobalErrorToast.tsx` Seq link must carry `rel="noopener noreferrer"` (both
   attributes).
7. A `Content-Security-Policy` header must be delivered by Caddy on all responses.
8. CSP must not break existing functionality (news thumbnails, charts, WebSocket).

---

## Architecture / Approach

### 1. Shared URL validation utility — `frontend/src/utils/url.ts`

A new module (sits alongside `frontend/src/utils/indicators.ts`) exporting one function:

```ts
/**
 * Validates an external URL. Returns the original string when safe, or null.
 * scheme: only 'https:' is accepted.
 * allowedHosts: if provided, the URL's hostname must match an exact host or
 *               any subdomain thereof (e.g. 'twitter.com' also permits 't.co').
 */
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

**No external dependency.** Uses the native `URL` constructor (available in all
supported browsers). Null return means "not safe" — callers decide how to render
the fallback.

### 2. `NewsFeed.tsx` — apply scheme-only validation

At the article render site (lines 154-176), wrap `article_url` and `image_url`
before binding:

```tsx
const safeArticleUrl = safeExternalUrl(article.article_url);
const safeImageUrl   = safeExternalUrl(article.image_url);

// Render:
// - If safeArticleUrl is non-null: <a href={safeArticleUrl} target="_blank" rel="noopener noreferrer">…</a>
// - If null: <div>…title as plain text…</div> (no link)
// - If safeImageUrl is non-null: <img src={safeImageUrl} … />
// - If null: omit the thumbnail entirely
```

The existing `rel="noopener noreferrer"` on this link is already correct; no
change needed there.

### 3. `ScannerResults.tsx` — apply scheme + allowlist validation

At the tweet URL render site (lines 240-250), apply the domain allowlist:

```tsx
const TWEET_HOSTS = ['twitter.com', 'x.com', 't.co'];
const safeTweetUrl = safeExternalUrl(event.metadata?.tweet_url as string | undefined, {
  allowedHosts: TWEET_HOSTS,
});

// Render:
// - If safeTweetUrl is non-null: <a href={safeTweetUrl} target="_blank" rel="noopener noreferrer">…</a>
// - If null: plain text label only (no link)
```

The existing `rel="noopener noreferrer"` is already correct here.

### 4. `sw.js` — restrict `clients.openWindow` to same-origin

Replace the unvalidated `urlToOpen` with a same-origin guard:

```js
self.addEventListener('notificationclick', (event) => {
  event.notification.close();

  const raw = event.notification.data?.url || '/alerts';
  // Resolve against own origin; if the result is off-origin, fall back to /alerts
  let urlToOpen;
  try {
    const resolved = new URL(raw, self.location.origin);
    urlToOpen = resolved.origin === self.location.origin ? resolved.href : '/alerts';
  } catch {
    urlToOpen = '/alerts';
  }
  // … rest of openWindow logic unchanged
});
```

All push notification URLs the backend generates today are relative paths
(`/alerts`, `/scanner`) so this change is behaviour-preserving in production.

### 5. `GlobalErrorToast.tsx` — add `noopener`

Line 149: change `rel="noreferrer"` to `rel="noopener noreferrer"`.

While `noreferrer` implies `noopener` in modern browsers, the explicit form is
the defence-in-depth best practice and satisfies the finding.

### 6. Caddy CSP header

Add to `caddy/Caddyfile` inside the main site block (alongside existing HSTS):

```caddy
header Content-Security-Policy "default-src 'self'; img-src 'self' https: data:; connect-src 'self' wss:; script-src 'self'; style-src 'self' 'unsafe-inline'; font-src 'self' data:; object-src 'none'; base-uri 'self'; frame-ancestors 'self'" always
```

**Directive rationale:**

| Directive | Value | Reason |
|-----------|-------|--------|
| `default-src` | `'self'` | Deny all unlisted origins by default |
| `img-src` | `'self' https: data:` | News thumbnails come from arbitrary publisher CDNs (un-enumerable); `https:` wildcard blocks `http:` mixed-content and `javascript:`/`data:`-script injection in images; `data:` for Vite-inlined small assets |
| `connect-src` | `'self' wss:` | Axios calls are relative (`/api/*`); WebSocket upgrades to same backend origin via `wss://` |
| `script-src` | `'self'` | Bundled scripts only; no inline scripts in `index.html` |
| `style-src` | `'self' 'unsafe-inline'` | Tailwind v4 (via `@tailwindcss/vite`) and Recharts inject runtime inline styles; removing `'unsafe-inline'` breaks charts without a nonce/hash pipeline |
| `font-src` | `'self' data:` | No external font CDN; Vite may inline small fonts as data URIs |
| `object-src` | `'none'` | Blocks Flash/plugin vectors; no `<object>`/`<embed>` in the app |
| `base-uri` | `'self'` | Prevents base-tag injection attacks |
| `frame-ancestors` | `'self'` | Clickjacking defence (replaces `X-Frame-Options: SAMEORIGIN`) |

**Seq link note**: The Seq UI (`http://localhost:5380`) linked from `GlobalErrorToast`
is navigated to as an `<a href>`, not fetched — it is not a `connect-src` target.
In production (non-dev) `VITE_SEQ_UI_URL` is an internal network URL; the CSP
`default-src 'self'` allows same-origin navigation and the `frame-ancestors`
directive only restricts embedding, not anchor navigation.

---

## Alternatives Considered

### Domain allowlist for `article_url` (rejected)

A strict domain allowlist for Polygon.io news (Bloomberg, Reuters, AP, etc.)
would provide stronger open-redirect protection but requires constant maintenance
as Polygon onboards new publishers. A stale allowlist silently breaks the news
feed — a worse outcome than the Low-severity finding it prevents.
`https:`-scheme-only adequately blocks the named attack vectors (`javascript:`,
`data:`, `http:`).

### Block news images in CSP (`img-src 'self' data:`) (rejected)

Setting a restrictive `img-src` without `https:` would blank all news thumbnails
(they come from arbitrary CDN domains). This changes the current UX meaningfully
and would require backend image-proxying — scope creep beyond this security
hardening issue.

### Omit CSP header, treat as a separate issue (rejected)

The issue explicitly requires a CSP header and lists it as a verification
criterion. Deferring it would leave the spec incomplete.

---

## Open Questions

None blocking. All decisions are resolved by the Q&A above.

---

## Assumptions

- Vite's production build emits only bundled scripts with no inline `<script>` blocks
  in `index.html` (confirming `script-src 'self'` is safe).
- All Web Push notification URLs produced by the backend are relative paths — no
  absolute off-origin URLs are intentionally sent in the push payload today.
- The Caddy `header` directive with `always` applies to all response codes (2xx,
  4xx, 5xx), which is the correct behaviour for security headers.
- `'unsafe-inline'` for `style-src` is a known limitation of Tailwind v4 + Recharts
  inline styles. A future nonce-based CSP upgrade would be a separate hardening
  issue.
