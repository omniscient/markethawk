# Calibrated Decisions C1: Typed Decision Schema, Provenance, and Provider-Neutral Contract
**Revised:** 2026-10-21 (operator amendment after spec gate — hash round-trip and canonicalisation, null-gate rule, validate_request/validate_result + decide rule table, prefix-matched import boundary, #845 binding, per-AC tests, strict models)

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
  from importing any module whose dotted name starts with one of these **prefixes**:
  `ib_insync`, `app.schemas` (the whole package — see Alternative 1), `app.providers`,
  `app.services`, `app.models`, `app.routers`, `app.tasks`. A second, subprocess-based check
  imports `app.decisions` in a fresh interpreter and asserts `sys.modules` contains no module
  matching the same seven prefixes and additionally no module whose name contains
  `auto_trade`, to catch transitive leaks the AST check would miss. The subprocess is
  required because `backend/tests/conftest.py:31` does `from app.main import app`, which
  imports every router, service, and provider into the test process — an in-process
  `sys.modules` assertion would be meaningless.
- `DecisionRequest.quality_gate` is a new, locally-defined, frozen `QualityGateRef` summary
  type (not a bare id — `QualityGateAssessment` has no id of its own; see §3.3), copied by
  value, and **required** (not `Optional`). A request built from a run with no gate
  assessment (the nightly/live scan paths, where `ScannerRun.quality_gate` is null) still
  constructs, with the designated no-assessment ref
  `QualityGateRef(verdict="skipped", trusted=False, issue_codes=("no_assessment",),
  assessment_sha256=sha256(b""))`; the policy function returns `ABSTAIN` for it (§3.6).
  This is the "low-quality external state" fixture, not a feature to design around.
- Prompt-injection resistance is structural, not content-based: bounded strings, no
  `Any`/`Dict[str, Any]`, `extra="forbid"` and `strict=True` at every nesting level
  (fail-closed on type coercion — `"0.9"` is not a float, `1` is not a bool), closed answer
  enums, no deny-list scanning (see §3.4).
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
    request.py         # DecisionRequest, QualityGateRef, DecisionMarketSnapshot
    result.py          # DecisionResult
    provider.py         # DecisionProvider Protocol, capabilities, timeout/error taxonomy
    policy.py           # validate_request, validate_result, decide (RECORD / ABSTAIN / ESCALATE_FOR_OFFLINE_REVIEW)
backend/tests/decisions/
    test_schema.py
    test_request.py
    test_result.py
    test_policy.py
    test_architecture_boundary.py   # AST-walk + subprocess sys.modules check
    fixtures/                       # malformed, stale, low-quality, prompt-injected cases
                                    # (JSON/.py data files loaded by the tests, not pytest fixtures)
```

`backend/app/__init__.py` is effectively empty today, so `app/decisions/` starts with no
inherited side effects. Cross-references to other subsystems (quality gate, the #845 artifact
registry) are by typed ID/version/hash value fields only — `app/decisions/` never imports
`app.schemas`, `app.providers`, or the (not-yet-merged) #845 registry module.

### 3.2 `DecisionSchema`

Frozen Pydantic model (`model_config = ConfigDict(frozen=True, extra="forbid", strict=True)`):

- `schema_version: Literal["decision_schema.v1"]`
- `schema_hash: str` — sha256 hex digest over the canonical JSON of every other field on the
  instance, computed by a `@model_validator`. It is **derived, not supplied**: if a caller
  passes `schema_hash` on input it must equal the recomputed digest, otherwise
  `ValidationError` (tamper check). This keeps persisted schemas reloadable —
  `DecisionSchema.model_validate(s.model_dump()) == s` must hold — while
  `model_validate({**s.model_dump(), "schema_hash": "ff" * 32})` must raise.
- **Canonicalisation** (the only hash input accepted): every `datetime` is normalised to UTC
  before dumping, then
  `json.dumps(model_dump(mode="json", exclude={"schema_hash"}), sort_keys=True,
  separators=(",", ":"), ensure_ascii=True)`. Tuples therefore serialise as JSON arrays and
  datetimes as UTC ISO-8601 strings, so construction order and source tz offset cannot change
  the digest.
- `strategy_artifact_ref: str` — bounded (`max_length=128`). Its concrete shape is bound to
  #845's merged artifact id at plan time (see §6); the bounded string is the fallback only.
- `strategy_artifact_sha256: str` — sha256 hex digest (`pattern=^[0-9a-f]{64}$`) of the #845
  artifact file the schema was compiled from, mirroring `QualityGateRef.assessment_sha256`
  (tamper evidence; see §6).
- `questions: Tuple[DecisionQuestionDef, ...]` — non-empty, max length bounded (e.g. 32).
  Each `DecisionQuestionDef` has a `question_type: Literal[...]` drawn from a **closed**
  enum defined in this module (not an open string) and an `answer_space` that is itself a
  closed, bounded description (e.g. a fixed `Tuple[str, ...]` of allowed labels for a
  categorical question, or a `(min, max)` numeric bound for a bounded-numeric question) —
  this is what makes "reject unknown question types" and "reject unbounded outputs"
  structurally true rather than enforced by convention.
- `required_state_fields: Tuple[str, ...]` — bounded list of field names the request must
  supply.
- `data_cutoff: datetime` — timezone-aware, required (no default). It is the latest
  timestamp any data in a request's `market_snapshot` may carry: data visible to a provider
  must not postdate it (`validate_request`, §3.6).
- `calibration_policy: Literal["none", "platt", "isotonic"]` (extensible via a new version,
  not a free string).
- `invalidation_conditions: Tuple[str, ...]` — bounded.

A schema change that isn't purely additive-and-compatible requires a new `schema_version`
literal (`decision_schema.v2`, etc.) in a new class; the old version's class is never
mutated. `schema_hash` changes automatically with any field change, so a silent edit to a
"v1" schema is self-detecting even if someone forgets to bump the version literal.

### 3.3 `DecisionRequest`

Frozen Pydantic model, `extra="forbid"`, `strict=True`:

- `request_id: UUID`
- `schema_ref: str` — the `schema_hash` of the `DecisionSchema` this request answers against
  (value, not an import).
- `as_of: datetime` — timezone-aware; the moment the decision is asked. Must be
  `>= market_snapshot.observed_at` (a decision cannot be asked before its inputs existed;
  checked by `validate_request`, §3.6).
- `market_snapshot: DecisionMarketSnapshot` — immutable, bounded set of numeric/enum fields
  (no free-form text) plus an explicit `observed_at: datetime` (timezone-aware, required):
  the timestamp of the newest datum in the snapshot. `observed_at <= schema.data_cutoff` is
  required; a violation is a future-data leak and `validate_request` rejects it.
- `event_run_lineage: DecisionRunLineage` — `scanner_event_uuid: Optional[UUID]`,
  `scanner_run_uuid: Optional[UUID]`, `feature_provenance_ref: str` (bounded, required, no
  default).
- `quality_gate: QualityGateRef` — **required**, defined in this module:
  - `schema_version: Literal["quality_gate.v1"]`
  - `verdict: Literal["trusted", "warning", "blocked", "skipped"]` — a local `Literal`
    mirror of `QualityGateVerdict`'s four values, not an import of the enum from
    `app.schemas.quality_gate`
  - `trusted: bool`
  - `issue_codes: Tuple[Literal["missing_bars", "split_dividend_anomaly", "stale_quote",
    "provider_gap", "session_mismatch", "survivorship_bias", "insufficient_lookback",
    "no_assessment"], ...]` — bounded (`max_length=8`); the first seven mirror
    `QualityIssueCode` (`backend/app/schemas/quality_gate.py:33-40`) by value, and
    `no_assessment` is local to this module (see the null-gate rule below)
  - `generated_at: datetime` — timezone-aware
  - `source_run_uuid: Optional[UUID]` (maps to `ScannerRun.uuid`)
  - `assessment_sha256: str` — sha256 hex digest of the *persisted JSONB form* of the
    upstream `QualityGateAssessment`, i.e. the `json.loads(json.dumps(model_dump(),
    default=str))` payload written to `ScannerRun.quality_gate`
    (`backend/app/tasks/scanning.py:416`), canonicalised as in §3.2 — so the digest matches
    what is actually on the row, for tamper evidence
  
  Rationale: `QualityGateAssessment` (`backend/app/schemas/quality_gate.py`) has no `id` of
  its own — it is persisted only as an untyped JSONB blob on `ScannerRun.quality_gate`
  (`backend/app/models/scanner_run.py:42`), written at scan start for interactive
  `run_universe_scan` runs and **null** for nightly/scheduled and live scanner runs
  (`backend/app/tasks/scanning.py`). A bare id/string reference has nothing stable to point
  at. `QualityGateRef` copies the decision-relevant fields by value instead.

  **Null-gate rule** (the single behaviour used in §2, §3.6, §3.7 and §6): a request built
  from a run with no gate assessment (the nightly/live case) constructs with the designated
  no-assessment ref — `QualityGateRef(verdict="skipped", trusted=False,
  issue_codes=("no_assessment",), assessment_sha256=sha256(b""))`, `generated_at` set to the
  request's `as_of`, `source_run_uuid` set to the run's uuid when known. The field stays
  required and non-optional; "no gate" is valid, recordable, degraded data, and the policy
  function returns `ABSTAIN` for it — this *is* the designed behavior for "low-quality
  external state," not a gap to patch over.
- A `UntrustedText` wrapper type (see §3.4) for the handful of fields that must carry
  external free text (e.g. a catalyst headline snippet, if a question type needs it) —
  there is no such field in the v1 schema's required set, but the type exists so a future
  question type that needs bounded text doesn't reach for a bare `str`.

### 3.4 `DecisionResult`

Frozen Pydantic model, `extra="forbid"` and `strict=True` at every nesting level:

- `request_ref: str` (the `DecisionRequest.request_id`, stringified)
- `schema_ref: str` (the `DecisionSchema.schema_hash` this result answers against)
- `answers: Tuple[DecisionAnswer, ...]` — one per question in the schema; each
  `DecisionAnswer` is self-bounding at the Pydantic layer (bounded label `str`, bounded
  numeric) and is additionally validated against its question's closed `answer_space` by
  `validate_result(result, schema)` (§3.6), which rejects any value outside it. The Pydantic
  model alone cannot do that check — it holds only `schema_ref`, not the schema.
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
- `calibration_ref: Optional[str]` — bounded; **null until fitted**, identifies the
  calibration version that produced `calibrated_probability` (epic #871 requires every
  decision to store its calibration version; declaring the field now avoids a result `v2`
  when #874/#875 fit one).
- `provider_name: str`, `model_version: str` — bounded, the same two names as on the
  `DecisionProvider` protocol (§3.5); no required Claude/Anthropic-specific field anywhere
  in the model (contract is checked against this in a test using at least one non-Anthropic
  example provider identity).
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

`provider_name` and `model_version` are the same two attribute names a provider must copy
onto every `DecisionResult` it returns (§3.4).

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
def validate_request(request: "DecisionRequest", schema: "DecisionSchema") -> None: ...
def validate_result(result: "DecisionResult", schema: "DecisionSchema") -> None: ...

def decide(
    request: "DecisionRequest", result: "DecisionResult", schema: "DecisionSchema"
) -> Literal["RECORD", "ABSTAIN", "ESCALATE_FOR_OFFLINE_REVIEW"]:
    ...
```

All three are pure functions in `policy.py`, no I/O. The two validators exist because the
checks that span a request/result *and* its schema cannot live on a Pydantic model that
holds only `schema_ref` (a hash):

- `validate_request` raises on `request.schema_ref != schema.schema_hash`, on
  `market_snapshot.observed_at > schema.data_cutoff` (future-data leak), on
  `request.as_of < market_snapshot.observed_at`, and on a `required_state_fields` entry the
  snapshot does not supply.
- `validate_result` raises on `result.schema_ref != schema.schema_hash`, on an answer count
  that differs from the schema's question count, and on any answer or distribution value
  outside its question's closed `answer_space`.

`decide` has a three-valued output only — no path returns or implies an order, size, or
action beyond those three outcomes. The **v1 rule table**, evaluated in this order, is the
only policy logic this child ships (nothing further is deferred into it — thresholds,
calibration and promotion belong to #874–#876):

1. `request.schema_ref != schema.schema_hash` or `result.schema_ref != schema.schema_hash`
   → `ABSTAIN`
2. `result.abstention_reason is not None` → `ABSTAIN`
3. `request.quality_gate.verdict == "blocked"` → `ESCALATE_FOR_OFFLINE_REVIEW`
4. `request.quality_gate.verdict == "skipped"` (including the `no_assessment` null-gate
   ref) → `ABSTAIN`
5. any answer outside its question's `answer_space` (i.e. `validate_result` would raise)
   → `ABSTAIN`
6. otherwise → `RECORD`

A `blocked` or `skipped` `QualityGateRef.verdict` is accepted at the *schema* layer (it's
valid data) but `decide` never returns `RECORD` for either; unit tests pin rules 3 and 4
individually. (Design note: the schema layer accepts degraded gates rather than rejecting
them, so that a `blocked`-gate or no-gate request is still an observable, recordable
*fixture* of degraded state — the call happens at the policy layer, where MarketHawk's own
logic owns it, not at the data-shape layer.)

### 3.7 Tests and fixtures

One named test per acceptance criterion of #872:

| Acceptance criterion | Test |
|---|---|
| Unknown question types rejected | `test_schema.py::test_rejects_unknown_question_type` — `question_type="momentum_vibes"` raises `ValidationError` |
| Unbounded outputs rejected | `test_result.py::test_rejects_out_of_range_numeric_answer` (Pydantic bound) and `test_policy.py::test_validate_result_rejects_answer_outside_answer_space` (label not in the categorical space, numeric outside `(min, max)`) |
| Absent cutoff/provenance rejected | `test_schema.py::test_rejects_missing_data_cutoff` and `test_request.py::test_rejects_missing_feature_provenance_ref` — field omitted entirely, not just `None` |
| Model-supplied order/position-size rejected | `test_result.py::test_rejects_order_shaped_keys` — parametrised over `quantity`, `side`, `order_type`, `position_size`, `notional`, `stop_loss`, each probed at the result root **and** inside `answers`, `distributions`, and `usage`; every case raises `ValidationError` (`extra="forbid"`) |
| `confidence` cannot become `calibrated_probability` | `test_result.py::test_confidence_key_rejected` — a payload with the literal key `"confidence"` raises (`extra="forbid"`); `test_result.py::test_provider_confidence_does_not_populate_calibrated_probability` — `model_validate({..., "provider_confidence": 0.9})` leaves `calibrated_probability is None` and `calibration_ref is None` |
| Schema hashes deterministic and persisted with every result | `test_schema.py::test_schema_hash_deterministic` — same content built in different field order and with `data_cutoff` given as `+02:00` vs `Z` yields one digest; `test_schema.py::test_schema_hash_changes_on_any_field` — every single-field change changes the digest; `test_schema.py::test_schema_hash_round_trip_and_tamper` — `model_validate(s.model_dump()) == s` and `"ff" * 32` raises; `test_result.py::test_result_carries_schema_ref` — `schema_ref` is required, non-empty |
| Schema changes create a new immutable version | `test_schema.py::test_frozen_instance_rejects_mutation` — attribute assignment raises; `test_schema.py::test_v1_literal_rejects_v2` — `schema_version="decision_schema.v2"` raises on the v1 class |
| Provider/model neutral | `test_result.py::test_non_anthropic_provider_identity` — a result built with `provider_name="deterministic_baseline"`, `model_version="0"` validates; `test_result.py::test_no_vendor_field_names` — scans `model_json_schema()` of every model in `app.decisions` and asserts no property name matches `jev|anthropic|claude|opus` (case-insensitive) |
| Architecture tests prohibit broker/order imports | `test_architecture_boundary.py::test_no_forbidden_import_prefixes` (AST-walk over every file in `app/decisions/`, prefix-matching the seven prefixes in §2) and `test_architecture_boundary.py::test_fresh_import_leaves_no_forbidden_modules` (subprocess `sys.modules` check: same seven prefixes plus any module name containing `auto_trade`) |
| Fixtures cover malformed/stale/low-quality/prompt-injected | the four directories below, each driven by a parametrised test |

Fixture directories under `backend/tests/decisions/fixtures/` are JSON/`.py` data files
loaded by the tests, not pytest fixtures:

- `fixtures/malformed/`: wrong types (including strict-mode coercion cases such as `"0.9"`
  for a float), extra fields, missing required fields, out-of-range numerics — assert
  `ValidationError`.
- `fixtures/stale/`: a snapshot whose `observed_at` postdates the schema's `data_cutoff`
  (future-data leak), and an `as_of` earlier than `observed_at` — assert `validate_request`
  rejects both.
- `fixtures/low_quality/`: `quality_gate.verdict in {"blocked", "skipped"}` and the
  null-gate (nightly/live run) case built as the `no_assessment` ref from §3.3 — assert the
  request still constructs (gate is valid data), `decide` returns
  `ESCALATE_FOR_OFFLINE_REVIEW` for `blocked` and `ABSTAIN` for `skipped`/`no_assessment`,
  and never `RECORD`.
- `fixtures/prompt_injected/`: adversarial strings in every text-shaped field — assert each
  either fails validation or round-trips as inert `UntrustedText` with zero effect on
  `question_type`/`answer_space`/policy outcome.

CI note: the `test` job in `.github/workflows/ci.yml` runs `pip-audit` before
`python -m pytest` with no `continue-on-error`, so until markethawk #889 (pip-audit
python-jose / npm audit) is fixed this suite is evidenced by a local
`python -m pytest backend/tests/decisions -q` run recorded on the PR, not by a green check.

## 4. Alternatives Considered

1. **Place contracts in `backend/app/schemas/` alongside `quality_gate.py`.** Rejected:
   `schemas/__init__.py` unconditionally imports `AutoTradeOrderResponse`/
   `TradingStrategyResponse` from `app.schemas.auto_trade` at package-import time, so
   importing *any* `app.schemas.*` submodule triggers it — which is why the boundary test
   forbids the whole `app.schemas` prefix, not just `app.schemas.auto_trade`. The
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
- `strategy_artifact_ref` binding: #872 depends on #845 (the hypothesis-artifact registry),
  so implementation cannot dispatch before #845 is Done — by then its addressing scheme is
  fixed. The **plan phase therefore binds** `strategy_artifact_ref` to #845's merged artifact
  id (bounded, pattern-constrained to that id format) and pairs it with
  `strategy_artifact_sha256` of the artifact file, mirroring `assessment_sha256`. Only if
  #845 is still unmerged at plan time does `decision_schema.v1` fall back to the bounded
  free string (`max_length=128`) described in §3.2, with the reconciliation becoming a
  `decision_schema.v2` change rather than a breaking edit to v1.
- `QualityGateRef.source_run_uuid` is optional (not every request will trace back to a
  `ScannerRun`) but `quality_gate` itself is required — a run with no assessment is
  represented by the `no_assessment` ref defined in §3.3 (`verdict="skipped"`,
  `trusted=False`, `issue_codes=("no_assessment",)`, `assessment_sha256=sha256(b"")`),
  which `decide` maps to `ABSTAIN`, without the whole field being `Optional`.
