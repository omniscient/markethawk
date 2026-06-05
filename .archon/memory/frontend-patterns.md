# Frontend Patterns — Accumulated Lessons

This file is maintained automatically by the dark factory implement agent. Do not edit manually.
Entries are advisory. If an entry conflicts with CLAUDE.md or ARCHITECTURE.md, follow those documents.

## Frontend: Data Fetching

- [PATTERN] Use React Query (`useQuery` / `useMutation`) for all server state — never `useState` + `useEffect` + `fetch`. The existing query client is configured in `frontend/src/main.tsx`. <!-- bootstrap date:2026-06-02 expires:2026-12-02 source:implement -->

- [PATTERN] Query keys follow the format `['resource', id?]` — e.g. `['scanner-results']`, `['stock', ticker]`. Keep keys consistent across the file so React Query can cache and invalidate correctly. <!-- bootstrap date:2026-06-02 expires:2026-12-02 source:implement -->

## Frontend: TypeScript

- [AVOID] Do not use `any` in TypeScript — it defeats type-checking and will cause `tsc --noEmit` to fail in strict mode. Prefer `unknown` with narrowing, or derive types from the API response schema in `frontend/src/api/`. <!-- bootstrap date:2026-06-02 expires:2026-12-02 source:implement -->

- [PATTERN] Reuse API response types defined in `frontend/src/api/*.ts` rather than re-declaring interfaces in components. Type imports keep the schema as the single source of truth. <!-- bootstrap date:2026-06-02 expires:2026-12-02 source:implement -->

## Frontend: Component Structure

- [PATTERN] Pages (route-level views) live in `frontend/src/pages/`. Reusable UI pieces live in `frontend/src/components/`. A component that is only used by one page can live in a `components/` subdirectory named after the page. <!-- bootstrap date:2026-06-02 expires:2026-12-02 source:implement -->

- [PATTERN] Styling is Tailwind CSS utility classes only — no custom CSS files, no inline `style` objects. If a design requires a custom class, add it to `tailwind.config.js` as a theme extension. <!-- bootstrap date:2026-06-02 expires:2026-12-02 source:implement -->

## Frontend: WebSocket URLs

- [PATTERN] Use `wsUrl(path)` from `frontend/src/api/client.ts` for all WebSocket connections — it derives the base from the same `VITE_API_BASE_URL` as `apiClient`, so one env-var change propagates everywhere. Never inline `window.location.protocol`/`host`/`/api/v1/` manually. <!-- issue:#158 date:2026-06-03 expires:2026-12-03 source:implement -->

- [AVOID] Do not call `fetch('/api/v1/...')` directly in pages or components — it bypasses `apiClient`'s auth interceptor and hardcodes the base path. Use `apiClient.get('/path')` instead, which is relative to `API_BASE`. <!-- issue:#158 date:2026-06-03 expires:2026-12-03 source:implement -->

- [FIX] ESLint `no-restricted-syntax` selector `Literal[value=/\\/api\\//]` matches import paths like `'../api/client'` as false positives. Use the start-anchored form `Literal[value=/^\\/api\\//]` to only flag string literals that actually begin with `/api/`. <!-- issue:#158 date:2026-06-03 expires:2026-12-03 source:implement -->

## Frontend: ESLint Flat Config (v8+)

- [PATTERN] In `@typescript-eslint` v8, `tsPlugin.configs['flat/recommended']` returns an **array** of config objects (plugin, parser, rules entries). Spread it directly into the export array: `...tsPlugin.configs['flat/recommended']`. Apply custom overrides in a separate config block after the spread. <!-- issue:#197 date:2026-06-05 expires:2026-12-05 source:refine -->

- [AVOID] Do not call `.rules` on `tsPlugin.configs['flat/recommended']` — in v8 the value is an array, so `.rules` is `undefined` and the spread silently loads nothing. This was the root cause of the TS recommended ruleset never enforcing in MarketHawk. <!-- issue:#197 date:2026-06-05 expires:2026-12-05 source:refine -->

- [PATTERN] When CI should tolerate `warn`-level ESLint findings (pre-existing debt) but local dev stays strict: keep `--max-warnings 0` in `package.json` lint script for local use; in CI, invoke ESLint directly (`npx eslint . --report-unused-disable-directives-severity error`) without `--max-warnings 0`. This blocks on errors while surfacing warnings as advisory. <!-- issue:#197 date:2026-06-05 expires:2026-12-05 source:refine -->

## Frontend: Routing

- [PATTERN] New routes are registered in `frontend/src/App.tsx` using React Router `<Route>` elements. Match the existing pattern of lazy-loaded page components (`React.lazy` + `Suspense`). <!-- bootstrap date:2026-06-02 expires:2026-12-02 source:implement -->
