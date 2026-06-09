# Frontend Patterns — Accumulated Lessons

This file is maintained automatically by the dark factory implement agent. Do not edit manually.
Entries are advisory. If an entry conflicts with CLAUDE.md or ARCHITECTURE.md, follow those documents.

## Frontend: Data Fetching

- [PATTERN] Use React Query (`useQuery` / `useMutation`) for all server state — never `useState` + `useEffect` + `fetch`. The existing query client is configured in `frontend/src/main.tsx`. <!-- bootstrap date:2026-06-02 expires:2026-12-02 source:implement -->

- [PATTERN] Query keys follow the format `['resource', id?]` — e.g. `['scanner-results']`, `['stock', ticker]`. Keep keys consistent across the file so React Query can cache and invalidate correctly. <!-- bootstrap date:2026-06-02 expires:2026-12-02 source:implement -->

## Frontend: TypeScript

- [AVOID] Do not use `any` in TypeScript — it defeats type-checking and will cause `tsc --noEmit` to fail in strict mode. Prefer `unknown` with narrowing, or derive types from the API response schema in `frontend/src/api/`. <!-- bootstrap date:2026-06-02 expires:2026-12-02 source:implement -->

- [PATTERN] Reuse API response types defined in `frontend/src/api/*.ts` rather than re-declaring interfaces in components. Type imports keep the schema as the single source of truth. <!-- bootstrap date:2026-06-02 expires:2026-12-02 source:implement -->

- [PATTERN] `frontend/tsconfig.json` must have an `"exclude"` array covering `**/*.test.ts`, `**/*.test.tsx`, `src/test-utils`, and `src/test-setup.ts` so test files are never compiled by the production `tsc --noEmit` gate. <!-- issue:#193 date:2026-06-05 expires:2026-12-05 source:implement -->

- [PATTERN] `frontend/src/vite-env.d.ts` (single line: `/// <reference types="vite/client" />`) must exist in `src/` so all source files and the test tsconfig can resolve `import.meta.env` without per-file triple-slash references. This is the standard Vite scaffold file that this project was missing. <!-- issue:#193 date:2026-06-05 expires:2026-12-05 source:implement -->

- [PATTERN] `frontend/tsconfig.test.json` extends `tsconfig.json` with `"types": ["vite/client", "vitest/globals"]`, relaxed `noUnusedLocals`/`noUnusedParameters`, and `"include"` limited to test files — used for IDE test-file support and optional `tsc -p tsconfig.test.json --noEmit` gate. <!-- issue:#193 date:2026-06-05 expires:2026-12-05 source:implement -->

## Frontend: Component Structure

- [PATTERN] Pages (route-level views) live in `frontend/src/pages/`. Reusable UI pieces live in `frontend/src/components/`. A component that is only used by one page can live in a `components/` subdirectory named after the page. <!-- bootstrap date:2026-06-02 expires:2026-12-02 source:implement -->

- [PATTERN] Styling is Tailwind CSS utility classes only — no custom CSS files, no inline `style` objects. If a design requires a custom class, add it to `tailwind.config.js` as a theme extension. <!-- bootstrap date:2026-06-02 expires:2026-12-02 source:implement -->

## Frontend: WebSocket URLs

- [PATTERN] Use `wsUrl(path)` from `frontend/src/api/client.ts` for all WebSocket connections — it derives the base from the same `VITE_API_BASE_URL` as `apiClient`, so one env-var change propagates everywhere. Never inline `window.location.protocol`/`host`/`/api/v1/` manually. <!-- issue:#158 date:2026-06-03 expires:2026-12-03 source:implement -->

- [AVOID] Do not call `fetch('/api/v1/...')` directly in pages or components — it bypasses `apiClient`'s auth interceptor and hardcodes the base path. Use `apiClient.get('/path')` instead, which is relative to `API_BASE`. <!-- issue:#158 date:2026-06-03 expires:2026-12-03 source:implement -->

- [FIX] ESLint `no-restricted-syntax` selector `Literal[value=/\\/api\\//]` matches import paths like `'../api/client'` as false positives. Use the start-anchored form `Literal[value=/^\\/api\\//]` to only flag string literals that actually begin with `/api/`. <!-- issue:#158 date:2026-06-03 expires:2026-12-03 source:implement -->

## Frontend: Security Headers

- [PATTERN] Both `apiClient` and `unversionedClient` in `frontend/src/api/client.ts` must carry any security headers (e.g. `X-Requested-With: XMLHttpRequest`) as static defaults in the `headers` block — never add them only to one client, as auth endpoints use `unversionedClient` and API endpoints use `apiClient`. <!-- issue:#192 date:2026-06-05 expires:2026-12-05 source:implement -->

## Frontend: Routing

- [PATTERN] New routes are registered in `frontend/src/App.tsx` using React Router `<Route>` elements. Match the existing pattern of lazy-loaded page components (`React.lazy` + `Suspense`). <!-- bootstrap date:2026-06-02 expires:2026-12-02 source:implement -->

## Frontend: Testing Selectors

- [AVOID] Do not use `screen.getAllByRole('button')[0]` in tests — it couples to DOM order and silently targets the wrong button when the component adds new ones. Use `getByRole('button', { name: /label/i })` to target by accessible name. <!-- issue:#198 date:2026-06-06 expires:2026-12-06 source:implement -->

- [PATTERN] For `input[type="password"]`, there is no implicit ARIA role — RTL's `getByRole` cannot select it. Use `container.querySelector('input[type="password"]')` (stable attribute) when you cannot add `data-testid` to the source. For `input[type="text"]`, prefer `getByRole('textbox')`. <!-- issue:#198 date:2026-06-06 expires:2026-12-06 source:implement -->

- [PATTERN] jsdom-level patches (e.g. `globalThis.Notification = { permission: 'default' }`) belong in `frontend/src/test-setup.ts`, not in per-file `beforeAll` blocks. Moving them there makes the patch available to every test file automatically. <!-- issue:#198 date:2026-06-06 expires:2026-12-06 source:implement -->

## Frontend: ESLint / @typescript-eslint v8

- [AVOID] Do not call `.rules` on `tsPlugin.configs['flat/recommended']` in `frontend/eslint.config.js` — in `@typescript-eslint` v8 the value is an array of 3 config objects, so `.rules` is `undefined` and the spread silently loads zero TS rules. <!-- issue:#197 date:2026-06-05 expires:2026-12-05 source:implement -->

- [PATTERN] Spread `...tsPlugin.configs['flat/recommended']` directly at the top level of the ESLint export array (v8 flat-config idiom); add custom rule overrides in a separate config block after the spread so they win. <!-- issue:#197 date:2026-06-05 expires:2026-12-05 source:implement -->

- [PATTERN] When fixing `eslint.config.js` to enforce warning-level rules that produce many pre-existing warnings, update the pre-commit hook in `.pre-commit-config.yaml` to use `npx eslint . --report-unused-disable-directives-severity error` (errors only) rather than `npm run lint` — otherwise the hook blocks all commits until every warning is cleaned up. <!-- issue:#197 date:2026-06-05 expires:2026-12-05 source:implement -->

---
<!-- PROVISIONAL — entries below are from a single observed run; unverified.
     Do not rely on these as authoritative guidance. They are excluded from
     plan/implement prompt injection except as advisory context.
     Each will be promoted to [PATTERN] on second-run confirmation (different issue number) or dropped at TTL. -->
