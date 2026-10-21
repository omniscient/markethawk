# Calibrated Decisions C1: Typed Decision Schema, Provenance, and Provider-Neutral Contract

**Issue:** #872
**Date:** 2026-10-21
**Status:** Proposed — pending implementation plan

## 1. Overview / Problem Statement

Epic #871 wants a provider-neutral, typed-decision shadow lane downstream of validated
MarketHawk strategy artifacts: a slow research/reasoning process may propose atomic questions,
but deterministic MarketHawk code must keep sole authority over data cutoffs, thresholds,
abstention, risk policy, and persistence. This ticket (C1) ships none of that runtime
behavior — it defines the vendor-neutral *contracts* the rest of the epic builds on:
`DecisionSchema`, `DecisionRequest`, `DecisionResult`, a `DecisionProvider` protocol, and a
deterministic three-valued policy contract. No provider implementation, persistence layer,
backtest, shadow service, or trading logic is in scope.

The hard constraint driving the design is architectural, not functional: an external model
or provider must never be able to smuggle an order, a position size, or an implicit
probability into a MarketHawk decision record. The contract has to make that structurally
impossible, not policy-impossible.

## 2. Requirements (from Q&A)

- New, dependency-light top-level package `backend/app/decisions/`, structurally isolated
  from `backend/app/schemas/`, `backend/app/providers/`, and `backend/app/services/`. Depends
  only on the standard library and Pydantic.
- `DecisionProvider` is a standalone `typing.Protocol`, unrelated to `BaseDataProvider`
  (which is a market-data ABC tied to a broker/vendor provider-factory registry — the wrong
  shape and the wrong dependency for a decision provider).
- An architecture-boundary test (AST-walk, following the existing pattern in
  `backend/tests/live_scanner/test_main_imports.py`) forbids `app/decisions/` production code
  from importing `ib_insync`, `app.providers`, `app.services`, `app.schemas.auto_trade`,
  `app.models`, `app.routers`, or `app.tasks`. A second, subprocess-based check imports
  `app.decisions` and asserts `sys.modules` contains no `ib_insync`, `app.providers*`, or
  `*auto_trade*` module, to catch transitive leaks the AST check would miss.
- `DecisionRequest.quality_gate` is a new, locally-defined, frozen `QualityGateRef` summary
  type (not a bare id — `QualityGateAssessment` has no id of its own; see §3.3), copied by
  value, and **required** (not `Optional`). A request with no gate available (e.g. the
  nightly/live scan paths, where `ScannerRun.quality_gate` is null) fails validation — this is
  the "low-quality external state" fixture, not a feature to design around.
- Prompt-injection resistance is structural, not content-based: bounded strings, no
  `Any`/`Dict[str, Any]`, `extra="forbid"` at every nesting level, closed answer enums, no
  deny-list scanning (see §3.4).
- `provider_confidence` and `calibrated_probability` are separate fields on `DecisionResult`
  with no implicit aliasing path between them (no shared validator, no field alias, no
  `populate_by_name` overlap).
- Deterministic `schema_hash` (sha256 over canonical JSON) on `DecisionSchema`; frozen,
  immutable instances; a new `Literal` `schema_version` per breaking change; no in-place
  mutation of historical decisions.
- Fixtures covering four categories of adversarial/degraded external state: malformed, stale,
  low-quality (missing/blocked quality gate), and prompt-injected.

## 3. Architecture / Approach

### 3.1 Package layout

```
backend/app/decisions/
    __init__.py       # minimal re-exports only
    schema.py          # DecisionSchema, question/answer-space types, canonical hashing
    request.py         # DecisionRequest, QualityGateRef
    result.py          # DecisionResult
    provider.py         # DecisionProvider Protocol, capabilities, timeout/error taxonomy
    policy.py           # pure RECORD / ABSTAIN / ESCALATE_FOR_OFFLINE_REVIEW function
backend/tests/decisions/
    test_schema.py
    test_request.py
    test_result.py
    test_policy.py
    test_architecture_boundary.py   # AST-walk + subprocess sys.modules check
    fixtures/                       # malformed, stale, low-quality, prompt-injected cases
```

`backend/app/__init__.py` is effectively empty today, so `app/decisions/` starts with no
inherited side effects. Cross-references to other subsystems (quality gate, the #845 artifact
registry) are by typed ID/version/hash value fields only — `app/decisions/` never imports
`app.schemas`, `app.providers`, or the (not-yet-merged) #845 registry module.

### 3.2 `DecisionSchema`

Frozen Pydantic model (`model_config = ConfigDict(frozen=True, extra="forbid")`):

- `schema_version: Literal["decision_schema.v1"]`
- `schema_hash: str` — sha256 hex digest over the canonical JSON (sorted keys, no
  whitespace) of every other field on the instance; computed by a `@model_validator`,
  **not** settable by a caller (any attempt to pass `schema_hash` explicitly is rejected —
  it is derived, not supplied).
- `strategy_artifact_ref: str` — bounded (`max_length=128`), unconstrained-format string
  (deliberately not a strongly-typed ref; see Assumptions — #845's registry addressing
  scheme is not fixed yet).
- `questions: Tuple[DecisionQuestionDef, ...]` — non-empty, max length bounded (e.g. 32).
  Each `DecisionQuestionDef` has a `question_type: Literal[...]` drawn from a **closed**
  enum defined in this module (not an open string) and an `answer_space` that is itself a
  closed, bounded description (e.g. a fixed `Tuple[str, ...]` of allowed labels for a
  categorical question, or a `(min, max)` numeric bound for a bounded-numeric question) —
  this is what makes "reject unknown question types" and "reject unbounded outputs"
  structurally true rather than enforced by convention.
- `required_state_fields: Tuple[str, ...]` — bounded list of field names the request must
  supply.
- `data_cutoff: datetime` — timezone-aware; data visible to a provider must not postdate
  this.
- `calibration_policy: Literal["none", "platt", "isotonic"]` (extensible via a new version,
  not a free string).
- `invalidation_conditions: Tuple[str, ...]` — bounded.

A schema change that isn't purely additive-and-compatible requires a new `schema_version`
literal (`decision_schema.v2`, etc.) in a new class; the old version's class is never
mutated. `schema_hash` changes automatically with any field change, so a silent edit to a
"v1" schema is self-detecting even if someone forgets to bump the version literal.

### 3.3 `DecisionRequest`

Frozen Pydantic model, `extra="forbid"`:

- `request_id: UUID`
- `schema_ref: str` — the `schema_hash` of the `DecisionSchema` this request answers against
  (value, not an import).
- `as_of: datetime` — timezone-aware; must be `<= ` the referenced schema's `data_cutoff`.
- `market_snapshot: DecisionMarketSnapshot` — immutable, bounded set of numeric/enum fields
  (no free-form text).
- `event_run_lineage: DecisionRunLineage` — `scanner_event_uuid: Optional[UUID]`,
  `scanner_run_uuid: Optional[UUID]`, `feature_provenance_ref: str` (bounded).
- `quality_gate: QualityGateRef` — **required**, defined in this module:
  - `schema_version: Literal["quality_gate.v1"]`
  - `verdict: Literal["trusted", "warning", "blocked", "skipped"]` — a local `Literal`
    mirror of `QualityGateVerdict`'s four values, not an import of the enum from
    `app.schemas.quality_gate`
  - `trusted: bool`
  - `issue_codes: Tuple[str, ...]` — bounded, local `Literal`-mirrored codes
  - `generated_at: datetime` — timezone-aware
  - `source_run_uuid: Optional[UUID]` (maps to `ScannerRun.uuid`)
  - `assessment_sha256: str` — canonical-JSON hash of the full upstream
    `QualityGateAssessment` payload, for tamper evidence
  
  Rationale: `QualityGateAssessment` (`backend/app/schemas/quality_gate.py`) has no `id` of
  its own — it is persisted only as an untyped JSONB blob on `ScannerRun.quality_gate`
  (`backend/app/models/scanner_run.py:42`), written at scan start for interactive
  `run_universe_scan` runs and **null** for nightly/scheduled and live scanner runs
  (`backend/app/tasks/scanning.py`). A bare id/string reference has nothing stable to point
  at. `QualityGateRef` copies the decision-relevant fields by value instead. Because the
  field is required and non-optional, any request built from a run with no gate assessment
  (the nightly/live case) fails validation at construction — this *is* the designed
  behavior for "low-quality external state," not a gap to patch over.
- A `UntrustedText` wrapper type (see §3.4) for the handful of fields that must carry
  external free text (e.g. a catalyst headline snippet, if a question type needs it) —
  there is no such field in the v1 schema's required set, but the type exists so a future
  question type that needs bounded text doesn't reach for a bare `str`.

### 3.4 `DecisionResult`

Frozen Pydantic model, `extra="forbid"` at every nesting level:

- `request_ref: str` (the `DecisionRequest.request_id`, stringified)
- `schema_ref: str` (the `DecisionSchema.schema_hash` this result answers against)
- `answers: Tuple[DecisionAnswer, ...]` — one per question in the schema; each answer's
  value is validated against that question's closed `answer_space`, rejecting any value
  outside it.
- `distributions: Tuple[DecisionDistribution, ...]` — full probability/score distribution
  per answer, same closed-shape constraint.
- `provider_confidence: Optional[float]` (`ge=0, le=1`) — the provider's **self-reported**
  confidence statistic.
- `calibrated_probability: Optional[float]` (`ge=0, le=1`) — **nullable until fitted**,
  populated only by MarketHawk's own calibration step (outside this ticket's scope), never
  by a provider. There is no validator, alias, or `populate_by_name` path from
  `provider_confidence` to `calibrated_probability` — they are two independently-settable
  optional fields, and a unit test asserts that constructing a `DecisionResult` with only
  `provider_confidence` set leaves `calibrated_probability` as `None`.
- `provider_name: str`, `provider_version: str` — bounded, no required Claude/Anthropic-
  specific field anywhere in the model (contract is checked against this in a test using at
  least one non-Anthropic example provider identity).
- `latency_ms: int` (`ge=0`), `cost_usd: Optional[Decimal]` (`ge=0`), `usage: DecisionUsage`
  (bounded numeric token/call counters).
- `abstention_reason: Optional[Literal[...]]` — closed enum (timeout, low_confidence,
  schema_mismatch, provider_error, data_cutoff_violation, etc.), set exactly when no answer
  is recorded.

Critically, **no field on `DecisionResult` or any nested type can express an order, a side,
a quantity, or a position size** — there is no `quantity`, `side`, `order_type`, or
`position_size` field anywhere in the model, and `extra="forbid"` rejects an attempt to add
one. This is what makes "model-supplied order or position-size instructions" a schema-level
rejection rather than a runtime check.

**Prompt-injection posture** (structural, not content-based — a deny-list is brittle and
implies a guarantee the contract can't keep): no free-form strings by default anywhere in
`DecisionRequest`/`DecisionResult` — fields are enums, Literals, bounded numerics, or
pattern+length-constrained ids. Where external text is genuinely unavoidable in a future
question type, it must be wrapped in `UntrustedText` (`app/decisions/schema.py`): a frozen
type with `max_length`, control-character stripping/rejection, and a field name that marks
it as inert data. `UntrustedText` never appears in a position that drives a question type,
an answer enum, or a policy branch. Fixtures assert that an injected payload either (a)
fails Pydantic validation (wrong shape, too long, extra field) or (b) passes through
unchanged as opaque `UntrustedText` with no effect on the resulting `question_type`,
`answer_space`, or policy outcome.

### 3.5 `DecisionProvider` protocol

```python
@runtime_checkable
class DecisionProvider(Protocol):
    provider_name: str
    model_version: str
    capabilities: DecisionProviderCapabilities  # max_questions_per_request, supports_distributions, etc.

    def answer(self, request: "DecisionRequest", schema: "DecisionSchema") -> "DecisionResult": ...
```

Modeled on the codebase's existing small-`Protocol` convention (`EmbeddingProvider` in
`backend/app/services/embedding_service.py`; `QualityGateServiceProtocol` in
`backend/app/schemas/quality_gate.py`), not on `BaseDataProvider` — that ABC is a
market-data interface (`get_bars`, `get_snapshots`, `supported_asset_classes`) wired into
`DataProviderFactory`'s broker/vendor registry, the dependency this package is required to
stay clear of.

Error/timeout taxonomy (`DecisionProviderError` hierarchy, local to this module):
`DecisionTimeoutError`, `DecisionSchemaRejectedError` (provider can't satisfy the schema),
`DecisionProviderUnavailableError`. All are catchable by callers without importing anything
outside `app.decisions`.

### 3.6 Deterministic policy contract

```python
def decide(result: "DecisionResult", schema: "DecisionSchema", gate: "QualityGateRef") -> Literal["RECORD", "ABSTAIN", "ESCALATE_FOR_OFFLINE_REVIEW"]:
    ...
```

Pure function, no I/O. Three-valued output only — no path returns or implies an order,
size, or action beyond those three outcomes. A `blocked` `QualityGateRef.verdict` is
accepted at the *schema* layer (it's valid data) but the policy function must never return
`RECORD` for a request whose gate is `blocked`; a unit test pins this. (Design note: the
schema layer accepts `blocked` rather than rejecting it, so that a `blocked`-gate request is
still an observable, recordable *fixture* of degraded state — rejection happens at the
policy/decision layer, where MarketHawk's own logic owns the call, not at the data-shape
layer.)

### 3.7 Tests and fixtures

- `test_architecture_boundary.py`: AST-walk over every file in `app/decisions/` forbidding
  the import list in §2; a subprocess-based `sys.modules` check for transitive leaks.
- `fixtures/malformed/`: wrong types, extra fields, out-of-range numerics — assert
  `ValidationError`.
- `fixtures/stale/`: `as_of` after the schema's `data_cutoff` — assert rejection.
- `fixtures/low_quality/`: `quality_gate.verdict in {"blocked", "skipped"}` and the
  null-gate (nightly/live run) case — assert the schema still constructs (gate is valid
  data) but the policy function never returns `RECORD`.
- `fixtures/prompt_injected/`: adversarial strings in every text-shaped field — assert each
  either fails validation or round-trips as inert `UntrustedText` with zero effect on
  `question_type`/`answer_space`/policy outcome.

## 4. Alternatives Considered

1. **Place contracts in `backend/app/schemas/` alongside `quality_gate.py`.** Rejected:
   `schemas/__init__.py` unconditionally imports `AutoTradeOrderResponse`/
   `TradingStrategyResponse` from `app.schemas.auto_trade` at package-import time, so the
   "no broker/order imports" architecture test would fail the instant anything in
   `app.decisions` imported from `app.schemas` — a side effect of package layout, not of
   the actual contract code.
2. **Make `DecisionProvider` extend `BaseDataProvider`.** Rejected: `BaseDataProvider` is a
   market-data ABC wired into `DataProviderFactory`'s registry (`backend/app/providers/`),
   which imports `ib_insync` at package-import time. Subclassing it would both pull in a
   broker dependency and conflate two unrelated interfaces (market data fetch vs. a
   typed-decision answerer).
3. **Bare id/string pointer for the quality-gate reference.** Rejected: `QualityGateAssessment`
   has no id of its own and exists only as an untyped JSONB blob on `ScannerRun.quality_gate`,
   null outside interactive scans — there is nothing stable for a bare id to reference. A
   locally-defined `QualityGateRef` summary type copied by value (chosen, §3.3) gives
   point-in-time immutability and tamper evidence (`assessment_sha256`) without a new table.
4. **Content-based deny-list scan for prompt injection.** Rejected: brittle, and implies a
   completeness guarantee the contract cannot keep. Structural defenses (closed enums,
   bounded/no free-form strings, `extra="forbid"` everywhere, no order/size-shaped fields at
   all) are the testable, maintainable posture (chosen, §3.4).
5. **New isolated package `backend/app/decisions/`, `DecisionProvider` as a standalone
   `Protocol`, structural (not content-based) prompt-injection defense, `QualityGateRef` as a
   local value-copied summary type (chosen).** Matches both the issue's explicit asks and the
   codebase's existing conventions for vendor-neutral `Protocol`s and versioned Pydantic
   contracts (`quality_gate.py`'s own precedent).

## 5. Open Questions (non-blocking)

- Exact bound on `questions` per `DecisionSchema` (proposed 32) and on bounded-string fields
  — deferred to the plan phase as concrete `max_length`/`max_items` values, confirmed against
  the first real question set once #845's artifact shape stabilizes.
- Whether `calibration_policy` needs a fourth value beyond `none`/`platt`/`isotonic` before
  any provider is wired up — deferred; adding one is a compatible, non-breaking schema change
  under the existing `Literal`.
- Whether `UntrustedText` is needed by any v1 question type at all, or only exists as
  forward-compatible plumbing — current acceptance criteria don't require a text-bearing
  question type yet; left available but unused if so.

## 6. Assumptions (flagged)

- No SQLAlchemy model or DB table is introduced in this child. "Persisted with every result"
  (the `schema_hash` requirement) is read as a contract-level requirement — the field always
  exists and is populated on every `DecisionResult` instance — with the actual persistence
  layer (a table, a row) deferred to a later child (tracked against #875 in the epic's
  dependency order).
- `strategy_artifact_ref` stays an unconstrained, bounded string in `decision_schema.v1`
  because dependency #845 (the hypothesis-artifact registry) is still open and its addressing
  scheme (id format, versioning) isn't fixed yet. Reconciling `strategy_artifact_ref` with
  #845's real shape is a `decision_schema.v2` change, not a breaking edit to v1.
- `QualityGateRef.source_run_uuid` is optional (not every request will trace back to a
  `ScannerRun`) but `quality_gate` itself is required — the ref can point at "no gate was
  available" via its `verdict`/`issue_codes` fields without the whole field being `Optional`.
