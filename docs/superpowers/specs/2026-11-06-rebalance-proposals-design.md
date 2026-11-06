# Rebalance Proposals — check/create tools, Proposals tab, accept/reject, drift — Design Spec

**Issue:** #908
**Date:** 2026-11-06
**Status:** Proposed — pending implementation plan
**Epic:** #902 (Long-term ETF investing) — slice 5 of 5, serial
**Depends on:** #907 (LT-4 Portfolio)

## 1. Overview / Problem Statement

Epic #902 lets an agent reason about a long-term portfolio and propose rebalances; a human
decides. This slice is the last link: an agent calls `check_allocation` to preview a proposed
set of target percentages against active constraints, calls `create_proposal` to record one
with a rationale, a human reviews it on a new Proposals tab (diff against current holdings,
constraint pass/fail) and accepts or rejects it, and an accepted proposal becomes the new
current target — shown as drift on the Portfolio tab. Holdings are never touched by this flow;
only the target changes.

This spec assumes #904 (roster, `lt_etf`, static universe, `fx_rate_daily`), #905 (signals,
`/long-term` page shell), #906 (MCP server sidecar, `backend/mcp_server/`), and #907 (`lt_account`,
`lt_position`, `lt_constraint`, `LongTermPortfolioService.get_allocation()`/`evaluate_constraints()`,
the Portfolio tab) are merged into `main` by the time this issue is implemented. None exist in
this checkout today (confirmed: no `lt_*` model or `backend/mcp_server/` directory exists); this
spec is written against #907's spec (`docs/superpowers/specs/2026-11-06-portfolio-accounts-positions-constraints-design.md`,
on `origin/refine/issue-907-lt-4--portfolio---accounts--positions--c` at the time of writing) as
the authoritative interface, consistent with the epic's serial rollout ordering.

## 2. Requirements (from Q&A)

1. Models: `lt_target_allocation` (+`_line`), `lt_proposal` (+`_line`) — see §3.1 for exact
   columns.
2. A proposal is a **complete** portfolio-wide target. Any active held ticker (from
   `lt_position`, including cash pseudo-tickers and unpriced positions) absent from the
   submitted lines becomes an implied `sell` line to 0%.
3. **Submitted lines + implied sells must sum to exactly 100% (±0.01pp), each in [0, 100];
   cash is always explicit** (`CASH:USD`/`CASH:CAD`), never an implicit residual — a total
   other than 100%, an unknown/inactive ticker, a duplicate ticker, or a negative percentage
   is rejected outright (422 / MCP tool error), never stored or silently rescaled. *(Q1)*
4. Constraint violations on an otherwise-valid (100%-summing) proposal are **stored**
   (`has_violations=true`) so a human sees what was proposed, but block Accept.
5. **An incomplete current-allocation baseline (`complete=False` from `get_allocation()`)
   does not block `check_allocation`/`create_proposal` and does not set `has_violations`** —
   it is carried through as `baseline_complete`/`unpriced_positions` on the response and the
   stored proposal; diff rows for unpriced tickers show `current_pct: null`/`est_amount: null`
   with a `reason`, never a fabricated 0. *(Q2)*
6. Accept creates a new current `lt_target_allocation` (archive-then-insert, so exactly one
   row has `is_current=true`) copied from the proposal's lines (including implied-sell 0%
   lines, so the next diff treats them as explicitly targeted). Holdings are untouched.
   Reject stores an optional `decision_note`. Both require `status="pending"` (409 otherwise).
7. REST: proposals list/get/create, `POST /proposals/{id}/accept|reject`, targets current,
   drift. Accept/reject use the same cookie session auth as every other state-changing
   endpoint in this codebase — no new auth mechanism; "browser-session only" is enforced by
   omitting accept/reject from the MCP tool list, not by a REST-side check.
8. MCP tools: `check_allocation`, `create_proposal`, `list_proposals`, `get_proposal`. No
   accept/reject tool.
9. Frontend Proposals tab (pending first, each with rationale, diff table, constraint report,
   Accept disabled while `has_violations`, Reject with note; history below) and a drift widget
   added to the existing Portfolio tab (#907's file) comparing current allocation to current
   target.
10. Done when: `check_allocation` → `create_proposal` → human accepts on the page →
    `get_allocation`-adjacent drift view shows the new target; a violating proposal cannot be
    accepted.

## 3. Architecture / Approach

### 3.1 Models (`backend/app/models/long_term.py`, extends #907's file; new Alembic migration)

Following the same conventions #907 used (`Integer` PK + `utc_now` timestamps, unparameterized
`Numeric` for money/percent columns, `String(N)` + comment for status/enum-like fields, JSONB
for structured blobs) plus this codebase's "anchor table gets a `uuid`" convention
(`scanner_event.py`, `backtest_run.py`, `scanner_run.py`) and the service-layer
archive-then-insert singleton pattern (`RegimeModel`/`regime_service.py` — no DB constraint
anywhere in this codebase enforces "exactly one current row"):

```python
class LtTargetAllocation(Base):
    __tablename__ = "lt_target_allocations"
    id = Column(Integer, primary_key=True, index=True)
    uuid = Column(UUID(as_uuid=True), default=uuid.uuid4, unique=True, index=True)
    created_at = Column(DateTime, default=utc_now)
    source_proposal_id = Column(Integer, ForeignKey("lt_proposals.id"), nullable=True)
    is_current = Column(Boolean, default=False, nullable=False, index=True)

class LtTargetAllocationLine(Base):
    __tablename__ = "lt_target_allocation_lines"
    id = Column(Integer, primary_key=True, index=True)
    target_allocation_id = Column(Integer, ForeignKey("lt_target_allocations.id", ondelete="CASCADE"), nullable=False, index=True)
    ticker = Column(String(20), nullable=False)
    target_pct = Column(Numeric, nullable=False)
    __table_args__ = (UniqueConstraint("target_allocation_id", "ticker", name="uq_lt_target_line_alloc_ticker"),)

class LtProposal(Base):
    __tablename__ = "lt_proposals"
    id = Column(Integer, primary_key=True, index=True)
    uuid = Column(UUID(as_uuid=True), default=uuid.uuid4, unique=True, index=True)
    created_at = Column(DateTime, default=utc_now)
    created_by = Column(String(100), nullable=False)  # free-text agent or user identity
    status = Column(String(10), nullable=False, default="pending")  # pending | accepted | rejected
    rationale = Column(Text, nullable=False)
    constraint_report = Column(JSONB, nullable=False, default=dict)
    has_violations = Column(Boolean, nullable=False, default=False, index=True)
    decided_at = Column(DateTime, nullable=True)
    decision_note = Column(Text, nullable=True)

class LtProposalLine(Base):
    __tablename__ = "lt_proposal_lines"
    id = Column(Integer, primary_key=True, index=True)
    proposal_id = Column(Integer, ForeignKey("lt_proposals.id", ondelete="CASCADE"), nullable=False, index=True)
    ticker = Column(String(20), nullable=False)
    target_pct = Column(Numeric, nullable=False)
    action = Column(String(10), nullable=False)  # buy | sell | hold (see §5 for the unpriced-baseline edge case)
    est_amount = Column(Numeric, nullable=True)  # null when baseline for this ticker is unpriced
    account_id = Column(Integer, ForeignKey("lt_accounts.id"), nullable=True)  # display-only execution hint
    note = Column(Text, nullable=True)
    __table_args__ = (UniqueConstraint("proposal_id", "ticker", name="uq_lt_proposal_line_proposal_ticker"),)
```

`constraint_report` JSONB shape (same for the `check_allocation` response and the stored
`lt_proposal.constraint_report`):
```json
{
  "constraints": [{"kind": "max_pct", "scope": "tag", "scope_value": "energy",
                    "threshold_pct": 15, "proposed_exposure": 18.2, "pass": false}],
  "has_violations": true,
  "baseline_complete": false,
  "unpriced_positions": [{"ticker": "XEG.TO", "reason": "no_price"}]
}
```

Add the four models to `backend/app/models/__init__.py` per CLAUDE.md's "New Models" rule,
then `python -m alembic revision --autogenerate -m "add_lt_proposal_lt_target_allocation"` and
`alembic upgrade head`, following the same single-migration-for-related-tables + hand-reviewed
`op.create_index` style as `f33989688da3_add_alerting_tables.py`.

### 3.2 `LongTermProposalService` (`backend/app/services/long_term/proposals.py`)

Plain functions taking `db: Session`, matching this codebase's house style for
shared write logic (`approve_order`/`auto_trade_service.py`) rather than a stateful class —
called identically from the REST router and the MCP tools so they can never disagree:

```
_validate_and_build_lines(db, submitted_lines) -> list[ProposedLine]:
    reject (422/ToolError) if: unknown/inactive ticker; duplicate ticker in submitted_lines;
      target_pct outside [0, 100]
    held = active LtPosition rows (including cash pseudo-tickers, including unpriced ones)
    implied_sells = held tickers not present in submitted_lines -> target_pct=0
    lines = submitted_lines + implied_sells
    reject (422/ToolError) if sum(line.target_pct for line in lines) not within 0.01 of 100
    return lines

check_allocation(db, lines) -> CheckResult:
    lines = _validate_and_build_lines(db, lines)
    baseline = LongTermPortfolioService.get_allocation(db)       # from #907
    proposed_allocation = { line.ticker: line.target_pct for line in lines }  # + segment/tag rollup
    report = LongTermPortfolioService.evaluate_constraints(db, proposed_allocation)
    for line in lines:
        current = baseline.allocations.get(line.ticker)  # None if unpriced/not held
        line.est_amount = None if current is None else (line.target_pct - current.pct) / 100 * baseline.total_value
        line.action = _infer_action(current, line.target_pct)   # see §5
    return CheckResult(lines=lines, constraint_report={**report, "baseline_complete": baseline.complete,
                                                        "unpriced_positions": baseline.unpriced_positions})

create_proposal(db, lines, rationale, created_by) -> LtProposal:
    result = check_allocation(db, lines)   # same validation + computation path
    persist LtProposal(status="pending", rationale=rationale, created_by=created_by,
                        constraint_report=result.constraint_report,
                        has_violations=result.constraint_report["has_violations"])
    persist one LtProposalLine per result.lines (including implied sells)
    return the proposal

accept_proposal(db, proposal_id) -> LtProposal:
    proposal = get_or_404(db, LtProposal, proposal_id, "Proposal")
    if proposal.status != "pending": raise HTTPException(409, ...)
    if proposal.has_violations: raise HTTPException(409, "Cannot accept a proposal with constraint violations")
    db.query(LtTargetAllocation).filter(LtTargetAllocation.is_current.is_(True)) \
        .update({"is_current": False})                      # archive-then-insert, one transaction
    new_target = LtTargetAllocation(source_proposal_id=proposal.id, is_current=True)
    db.add(new_target); db.flush()
    for line in proposal.lines:
        db.add(LtTargetAllocationLine(target_allocation_id=new_target.id,
                                       ticker=line.ticker, target_pct=line.target_pct))
    proposal.status = "accepted"; proposal.decided_at = utc_now()
    db.commit()
    return proposal

reject_proposal(db, proposal_id, decision_note=None) -> LtProposal:
    proposal = get_or_404(db, LtProposal, proposal_id, "Proposal")
    if proposal.status != "pending": raise HTTPException(409, ...)
    proposal.status = "rejected"; proposal.decided_at = utc_now(); proposal.decision_note = decision_note
    db.commit()
    return proposal

get_drift(db) -> DriftResult:
    current = LongTermPortfolioService.get_allocation(db)                     # from #907
    target = current LtTargetAllocation's lines, or [] if none accepted yet
    merge by ticker -> [{ticker, current_pct, target_pct, drift_pct}], baseline_complete passthrough
```

This mirrors #907's own "shared by both callers so they can't disagree" rule (§3.4 of that
spec): REST and MCP both call `check_allocation`/`create_proposal`/`accept_proposal`/
`reject_proposal` directly, never reimplementing validation or constraint evaluation.

### 3.3 REST API (`backend/app/routers/long_term.py`, extends #907's router, prefix `/api/v1/long-term`)

Same cookie auth as every other router (no new auth mechanism — see Requirement 7):

- `POST /proposals/check` → `check_allocation` (no persistence); body `{lines: [{ticker, target_pct, account_id?, note?}]}`.
- `POST /proposals` → `create_proposal`; same body plus `rationale`, `created_by`.
- `GET /proposals?status=` → list, ordered `created_at desc`; `GET /proposals/{id}`.
- `POST /proposals/{id}/accept`, `POST /proposals/{id}/reject` (body: `{decision_note?}`) —
  409 on wrong status or (accept only) `has_violations`, mirroring the `AutoTradeOrder`
  approve/reject precedent (`auto_trading.py`).
- `GET /targets/current` → the current `lt_target_allocation` + lines, or 404-shaped
  "no target set yet" if none has ever been accepted.
- `GET /drift` → `get_drift()`.

Pydantic schemas added to #907's `backend/app/schemas/long_term.py`
(`ProposalLineIn`, `ProposalLineOut`, `ConstraintReport`, `ProposalCreate`, `ProposalOut`,
`DriftRow`), `response_model=` style per `journal.py`.

### 3.4 MCP tools (`backend/mcp_server/`, extends the tool set #906/#907 scaffold)

`check_allocation(lines[])`, `create_proposal(lines[], rationale, created_by)`,
`list_proposals(status?)`, `get_proposal(id)` — import `app.services.long_term.proposals`
directly (no REST round-trip, per epic §4.7), identically to how #907 wires its MCP tools.
No `accept_proposal`/`reject_proposal` tool is registered.

### 3.5 Frontend (`frontend/src/pages/LongTerm/ProposalsPanel.tsx`, new; Portfolio tab, extended)

New tab within the `/long-term` page (shell from #905), following the per-tab-component-file
pattern (`AutoTrading/index.tsx` + `StrategyPanel.tsx` etc.), not a tab library:

- **Proposals tab:** pending proposals first (client-side split of one `useProposals()` list by
  `status`), each card showing `rationale`, the constraint report (reusing the Portfolio tab's
  constraint-bar visual language from #907), and a **new diff table component**
  (`DiffTable.tsx`) — there is no existing diff/before-after table anywhere in this frontend to
  crib from, so this is new UI: columns ticker, current %, target %, action badge (buy/sell/
  hold, color-coded), est. amount (or "no price" when `est_amount` is null, matching #907's
  "no price" convention for unpriced rows). A `baseline_complete=false` proposal shows the same
  warning banner #907 gives the Portfolio tab for unpriced positions. Accept button disabled
  (with a tooltip) while `has_violations`; Reject opens a small note field. Decided proposals
  render below as read-only history (status badge, `decided_at`, `decision_note`).
- **Portfolio tab (extends #907's file):** a drift widget — table or small bar chart (follow
  the `dataviz` skill) comparing `current_pct` vs `target_pct` per ticker from `GET /drift`;
  renders "no target set yet" when `GET /targets/current` has never been set.
- API additions in #907's `frontend/src/api/longTerm.ts` (`useProposals`, `useCheckAllocation`,
  `useCreateProposal`, `useAcceptProposal`, `useRejectProposal`, `useDrift`), React Query
  mutations following `useApproveOrder`/`useRejectOrder` (`api/trading.ts`).
- No "create proposal" form — the issue's frontend scope is Accept/Reject + diff/constraint
  display only; creation is agent-only (MCP) or direct API (e.g. testing), consistent with the
  issue body listing no create UI.

## 4. Alternatives Considered

1. **Treat cash as an implicit 100%-minus-equities residual, never requiring an explicit
   `CASH:*` line.** Rejected in Q&A (A1): contradicts the epic's "complete target" rule, which
   treats a held-but-omitted ticker (cash included) as an implied sell to 0%, not a residual.
2. **Silently rescale a submitted total other than 100% rather than rejecting it.** Rejected
   (A1): matches #907's stance against quiet corrections (e.g. position-upsert currency
   mismatches are 422, never auto-fixed); a rescaled total would also misrepresent what the
   agent actually asked for in the stored `rationale`/lines.
3. **Block `check_allocation`/`create_proposal` (422) whenever the current-allocation baseline
   is incomplete.** Rejected (A2): would make proposals unusable for up to a day after every
   roster addition, contradicting #907's own exclude-and-surface precedent for the identical
   problem.
4. **Set `has_violations=true` when the baseline is incomplete, to force human attention
   before Accept.** Rejected (A2): `has_violations` is reserved for `lt_constraint` policy
   breaches on the agent-supplied, price-independent proposed target; conflating it with data
   staleness would make a perfectly valid target proposal unacceptable for a reason unrelated
   to the proposal itself. `baseline_complete`/`unpriced_positions` carries the signal instead.
5. **A DB-level singleton constraint (partial unique index) for `lt_target_allocation.is_current`
   instead of service-layer archive-then-insert.** Rejected: no precedent for this anywhere in
   the codebase (`RegimeModel` uses service-layer enforcement); introducing a new DB-constraint
   pattern for one table adds inconsistency without a demonstrated need, since all writes to
   `is_current` go through `accept_proposal`, a single code path.

## 5. Open Questions (non-blocking)

- **`action` for an unpriced held ticker with a nonzero explicit target.** When `current_pct`
  is `null` (baseline unpriced) and the submitted `target_pct` is also nonzero, buy-vs-sell
  can't be determined without a current magnitude — only the `target_pct == 0` case (implied
  or explicit full exit) is unambiguous ("sell"). Left to the implementation plan: either widen
  `action` to accept a fourth value for this edge case (e.g. `"unknown"`) or require `current_pct`
  to be present whenever `target_pct != 0` is submitted for that ticker, surfacing it as a 422
  guided by `unpriced_positions` rather than guessing. Not asked explicitly in Q&A since it's an
  implementation-detail edge case, not a product decision.
- Exact rounding/currency display precision for `est_amount` in the diff table — left to the
  implementation plan, following whatever precision #907's Portfolio tab settles on for
  allocation percentages and reporting-currency amounts.
- Whether `GET /targets/current` returning "no target set yet" is a 404 or a 200 with a null
  body — left to the implementation plan; either is consistent with this codebase's mixed
  precedent (`get_or_404` vs. a nullable-response endpoint elsewhere).

## 6. Assumptions (flagged)

- #904, #905, #906, and #907 are merged into `main` by the time this issue is implemented.
  None exist in this checkout today; this spec is written against #907's spec as the assumed
  end-state interface (`LongTermPortfolioService.get_allocation()`/`evaluate_constraints()`,
  `lt_account`/`lt_position`/`lt_constraint`, the Portfolio tab, the MCP server sidecar and its
  bearer-token auth) — consistent with the epic's serial rollout ordering.
- `LongTermPortfolioService.get_allocation()` returns a per-ticker (not just per-segment)
  breakdown with enough detail to look up `current_pct` by exact ticker for diff computation;
  #907's spec describes aggregation "by ticker, segment, tag, cash" so this is expected but not
  spelled out field-by-field in that spec.
  `AllocationResult.allocations` is assumed indexable by ticker for this reason.
- `evaluate_constraints()` accepts a proposed allocation shaped the same way `get_allocation()`
  returns one (so the single function truly serves both the current-state and proposed-state
  cases per epic §4.4) — #907's spec states the function signature as `evaluate_constraints(allocation)`
  without detailing the accepted shape for a synthetic (not-yet-persisted) allocation; this spec
  assumes the proposed per-ticker/segment/tag/cash percentage map can be passed in directly.
