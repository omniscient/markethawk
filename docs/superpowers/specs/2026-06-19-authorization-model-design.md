# Authorization Model — Design Spec

**Date:** 2026-06-19
**Status:** Approved (brainstorm complete) — pending implementation-plan + epic breakdown
**Source finding:** F-AUTHZ-01 (Defensive Security Review 2026-06-12), tracked as #373
**Supersedes:** #373 as a single ticket — #373 is promoted to an epic; this spec is its design pass.
**Standard:** OWASP A01:2021 Broken Access Control · CWE-639 (IDOR) / CWE-862 (Missing Authorization)

---

## 1. Problem

MarketHawk authenticates but does not **authorize**. A valid JWT cookie grants full access to
every record and every action, including arming live IBKR trades. The schema cannot express
ownership — no data table carries a `user_id` — so adding a second user silently shares all
trade journals, watchlists, strategies, and scanner configs (horizontal privilege escalation by
construction).

**What already exists** (authentication foundation is in place):
- `users` table: `id` (UUID), `username`, `password_hash`, `created_at`, `is_active`. **No role.**
- JWT-in-cookie auth (`{sub, exp}`, HS256), `get_current_user` / `ws_get_current_user`
  dependencies, refresh-token rotation, an ASGI `AuthMiddleware` that validates the signature on
  all non-exempt routes.
- Registration is **bootstrap-only** (blocks after the first user).

**What is missing** (pure authorization gap):
- No `role` on `User`; no role/scope claim used for decisions.
- `get_current_user` is wired into only **6 endpoints** today (logout, `/me`, the WebSockets) — every
  other endpoint authenticates via middleware but **never extracts the user**.
- No `user_id` on any data table; no per-user query scoping anywhere.

## 2. Goal & end-state decisions

The end-state is **real multi-user**, reached in phases. Decisions locked during brainstorming:

| Dimension | Decision |
|---|---|
| Tenancy shape | **Flat multi-user, one workspace.** `user_id` only — **no** org/tenant entity, no `org_id`. |
| Trading-account boundary | **Shared IBKR account/desk.** Per-user (BYO) broker accounts are a **separate later epic** — out of scope here. |
| Work-product ownership | Universes, scanner configs, strategies, backtests are **personal, private by default.** |
| Roles | **`admin` / `member`** (two fixed roles). |
| Provisioning | **Invite links/tokens.** Admin issues a one-time, expiring invite; invitee completes signup; defaults to `member`. |
| Enforcement | **Hybrid (Approach C):** explicit `require_admin` for the small role surface + centralized, can't-forget data scoping for the large data surface, rolled out router-by-router with a two-user test per router. |

### Explicitly out of scope
- Per-user (BYO) IBKR broker accounts / per-user positions isolation — **later epic**.
- Organizations / tenants / workspaces — not building an `org_id`.
- Cross-user admin analytics/views — deferred (the mechanism allows it via `unscoped()`).
- Granular capability flags — fixed two-role model only.

## 3. Resource classification

Every table falls into one of three buckets.

### ① Personal — gets `user_id` FK (NOT NULL, indexed); queries scoped to owner
`Trade` (+ `TradeExecution` via parent), `JournalEntry`, `Tag`, `ActiveWatchlist`,
`AlertRule` (+ `AlertDeliveryLog` via parent), `PushSubscription`, `NewsPreference`,
`StockUniverse`, `ScannerConfig`, `TradingStrategy`, `AutoTradeOrder`,
`BacktestRun` (+ `BacktestTrade` via parent).

Child rows (`TradeExecution`, `AlertDeliveryLog`, `BacktestTrade`) inherit ownership through their
parent FK and do **not** get their own `user_id` column.

### ② Global / shared reference — NO `user_id`; everyone reads; admin-only writes where applicable
`StockAggregate`, `FuturesAggregate`, `FuturesContract`, `FuturesRollover`, `StockMetric`,
`StockSplit`, `TickerReference`, `MarketHoliday`, `NewsArticle`, `RegimeModel`, `SystemConfig`,
all outcome/signal-analysis models (`Scanner*Outcome*`, `SignalAnalysisRun`, `SignalCluster`,
`SignalReview`), `TweetSignal`.

### ③ Attributed-but-global — gets `user_id` for "who ran it" + per-user rate-limiting; results stay globally readable
`ScannerRun` — carries `user_id` for attribution and per-user rate-limiting, but the `ScannerEvent`s
it produces are **global** market facts (see edge case 1).

(`BacktestRun` is **fully personal** — bucket ①: it carries `user_id` and both the run and its
`BacktestTrade` results are scoped to the owner. It is listed only under ①.)

### Confirmed edge cases
1. **`ScannerEvent`** → **global** market fact (outcome ML already aggregates across all events).
2. **`MonitoredAccount`** (Twitter/X handles the backend polls) → **admin-managed global ingestion
   config**, not personal — the poller produces `TweetSignal`s consumed by everyone.
3. **`NewsPreference`** → **personal** (each user tracks their own tickers).

## 4. Role & capability model

Two roles. **Authorization decisions read `current_user.role` from the DB**, never the JWT claim —
so demoting/deactivating a user takes effect immediately rather than waiting for token expiry. The
`role` claim is added to the JWT **only** so the frontend can render role-aware UI.

- **`admin`** — everything `member` can do, plus: arm/approve live trades, toggle `paper_mode`,
  destructive/global mutations, system config writes, and user management. Bootstrap (first) user is
  `admin`.
- **`member`** — own personal data + full app use + all global reads. **Cannot** arm/approve live
  trades, write system config, perform destructive global mutations, or manage users.

### Admin-only endpoints (`require_admin`)

| Capability | Endpoints |
|---|---|
| Live trading (shared account) | `POST /trading/orders/{id}/approve` · `/reject` · `/cancel` · `GET /trading/account` · `PATCH /trading/config` (paper_mode) |
| Destructive / global mutations | `DELETE /universe/aggregates` · `POST /system/apply-split-adjustments` · `PATCH /system/config` · `POST /alerts/push/generate-keys` |
| User management (new) | `GET /users` · `POST /users/invite` · `DELETE /users/invite/{id}` · `PATCH /users/{id}` (role/active) · `DELETE /users/{id}` |

`GET /system/config` and other `GET /system/*` stay readable by members (app settings, not secrets).
`GET /trading/account` is **admin-only** (shared-account financials).

### Approval workflow this creates
A member builds a strategy → it generates an `AutoTradeOrder` they own → only an **admin** can
approve/arm it on the shared IBKR account. This dovetails with the existing `requires_approval`
flag and with #368 (notional cap + kill switch) on that same path.

## 5. Enforcement architecture (Approach C)

1. **`OwnedModel` mixin** — adds `user_id: Mapped[uuid.UUID]` FK to `users.id`, `nullable=False`,
   indexed. The ~13 personal parent models inherit it.

2. **`current_user` wired everywhere** — add `Depends(get_current_user)` at the **router level** for
   all authenticated routers so every handler has the user object; layer `require_admin` on the
   admin endpoints in §4. (`require_admin` depends on `get_current_user` and checks
   `current_user.role`.)

3. **`scoped(model, user)` query helper** — the canonical read path for owned data:
   `select(model).where(model.user_id == user.id)`. Creates set `user_id = user.id`. Update/delete
   fetch **through** `scoped()` first; touching another user's row returns **404** (not 403 — do not
   reveal existence).

4. **`with_loader_criteria` safety net** — a request-scoped SQLAlchemy filter, driven by a
   `contextvar` the auth dependency sets, that auto-injects `user_id == current_user.id` on every
   owned-model SELECT. Belt-and-suspenders: a handler that forgets `scoped()` still cannot leak.
   - **Escape hatch** — `unscoped()` context (admin cross-user reads, background tasks) disables the
     criteria explicitly.

### Background workers (critical edge)
The safety net is **request-scoped and inert in Celery** (no request user). Tasks that create owned
rows — e.g. an alert-rule evaluation spawning an `AutoTradeOrder` — must set `user_id` **explicitly**
from the parent resource's owner (`strategy.user_id`). Per-task `user_id`-stamping is a checklist
item in each affected rollout slice.

## 6. Provisioning & invite flow

- `POST /users/invite {role}` (admin) → generate a random token; store only its **hash** + expiry +
  issuing admin + role; return the one-time link/token in plaintext to the admin to hand off.
- `GET /auth/invite/{token}` → validate (unused, unexpired) and show the signup form.
- `POST /auth/invite/{token}/accept {username, password}` → create the user with the invited role,
  mark the token `used` (one-time), and log them in (issue JWT).
- The existing bootstrap `/register` stays **first-user-only** (becomes `admin`); all subsequent
  users arrive via invites. Open registration stays blocked.
- Admin can revoke an unused invite (`DELETE /users/invite/{id}`).

### `invite_tokens` table
`id`, `token_hash`, `created_by` (admin user_id FK), `role` (granted role), `expires_at`,
`used_at` (nullable), `used_by` (nullable user_id FK).

## 7. Migration & backfill strategy

Per personal table, the safe three-step pattern (additive, restartable, idempotent):
1. Add `user_id` **nullable** (+ FK + index).
2. **Backfill** every existing row to the bootstrap admin's id (all current data belongs to the
   single existing user); child tables backfill from their parent.
3. Alter to **NOT NULL**.

Plus: add `User.role` with `server_default='member'`, then set the existing first user to `admin`.
New `invite_tokens` table is a plain create.

### Safety guards
- **Fresh DB** (zero rows): backfill no-ops; NOT NULL trivially satisfied.
- **Existing data but no user**: migration **fails loudly** rather than inventing an owner.
- **Idempotent / restartable** (consistent with the orphaned-preview-schema idempotency rule).
- The backend **entrypoint runs `alembic check`, not `upgrade`** — deploy requires a deliberate
  `alembic upgrade head` step (flag in the epic). Validate against a throwaway DB before merge.

## 8. Frontend

- **Invite acceptance page** — public route `/invite/:token` → set username/password form.
- **User management UI** (admin-only) — list users, generate invite link, revoke invite, change
  role, deactivate.
- **Role-aware gating** — read `role` from `/auth/me`; hide/disable admin-only actions (approve
  order, paper_mode toggle, system config, purge aggregates, user mgmt) for members; handle `403`
  gracefully if a member calls one anyway.
- **No other UI change** — the backend scopes data automatically, so existing pages show "my" data.
  Cross-user admin views are deferred.
- `tsc --noEmit` must stay green.

## 9. Verification

The point of the finding is to **prove the IDOR hole is closed**.

- **Two-user isolation suite** — per personal resource: A creates a row → B gets `404` on
  read/update/delete and B's list excludes it. Regression gate, run per resource-group.
- **Role-gating suite** — `member` gets `403` on every admin-only endpoint; `admin` succeeds.
- **Invite suite** — create/accept/expire/reuse/revoke; first-user bootstrap still works; open
  registration still blocked.
- **Safety-net test** — a deliberately un-`scoped()` query still returns only the caller's rows.
- **Worker test** — alert-rule task stamps the correct `user_id` on a generated `AutoTradeOrder`.
- **Migration test** — throwaway DB seeded with single-user data → assert backfill correctness.
- **Re-run the security review** to confirm F-AUTHZ-01 closed ("verified against code", per #372 DoD).

## 10. Epic phasing → sub-issue slices

Each slice is independently grabbable, vertically sliced, and carries its own tests.

### Phase 1 — Identity & roles (closes the dangerous gap first)
- **S1** — `User.role` + migration + `require_admin` + gate all admin-only endpoints + wire
  `current_user` at router level. *Tracer bullet: a member can no longer arm trades or change
  config. Highest security value, smallest blast radius.*
- **S2** — Invite provisioning: `invite_tokens` table, admin invite/revoke endpoints, accept flow,
  frontend invite page + user-management UI.

### Phase 2 — Per-user ownership (mechanical bulk)
- **S3** — Enforcement scaffolding: `OwnedModel` mixin, `scoped()`, `with_loader_criteria` safety net
  + `unscoped()` escape, contextvar wiring, **proven end-to-end on Watchlist** with a two-user test.
  *Tracer bullet for the scoping mechanism.*
- **S4** — Journals / trades / tags scoping (+ migration + two-user test).
- **S5** — Alerts (rules / delivery / push subs) scoping.
- **S6** — Universes scoping.
- **S7** — Scanner configs + runs scoping.
- **S8** — Strategies + auto-trade orders scoping (+ Celery `user_id` stamping).
- **S9** — Backtests + news preferences scoping.

### Phase 3 — Closeout
- **S10** — Full isolation + role-gating regression suite, throwaway-DB migration validation, **ADR**
  documenting the authz model (`docs/adr/`), re-run security review, update `CONTEXT.md`, close epic.

Phase 1 alone closes the privilege-gating half of F-AUTHZ-01; Phase 2 closes the data-isolation half.

## 11. Risks & mitigations
- **Forgotten scoping filter (IDOR)** → the `with_loader_criteria` safety net + mandatory two-user
  test per slice.
- **Over-broad global filter breaking admin/worker paths** → explicit `unscoped()` escape; workers
  never rely on request scoping and stamp `user_id` from the parent resource.
- **NOT NULL migration on populated tables** → three-step additive pattern + fail-loud guard +
  throwaway-DB validation.
- **Stale role in JWT after demotion** → authz reads DB `current_user.role`, never the claim.
- **Deploy forgets `alembic upgrade head`** (entrypoint is `alembic check` only) → called out in the
  epic and each migration slice.
