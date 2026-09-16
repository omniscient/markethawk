# Data Quality Gate — Backtesting Integration Contract (#502)

**Status:** contract definition (epic #491). The backtesting facility does not exist yet; this is the
contract the **future** backtesting persistence slice MUST follow so that backtest performance claims are
never treated as trusted unless the underlying data passed the quality gate. It builds on the gate
contract delivered in #492–#501 and the Scorecard filtering in #497.

## 1. Preflight call

Before running a backtest, the backtesting facility MUST obtain a quality-gate assessment via either:

- in-process: `QualityGateService.assess(db, request)` → `QualityGateAssessment`, or
- HTTP preflight: `POST /api/v1/data-quality/gate` with a `GateRequest` body.

`GateRequest` fields the facility MUST set (all already exist — `backend/app/schemas/data_quality.py`):

| field | value for backtesting |
|---|---|
| `consumer` | `"backtesting"` |
| `policy` | `"strict"` for a **trusted** run; `"advisory"` for an **exploratory** run (see §3) |
| `universe_id` | the backtest universe |
| `start_date` / `end_date` | the backtest window (drives staleness `as_of_date` semantics and historical scope) |
| `requirements` | the timespans/lookback the strategy needs |

`consumer="backtesting"` is a **historical-analysis scope**: per #501 it triggers the `survivorship_bias`
check (see §6).

## 2. Trusted-persistence rule (the core invariant)

A backtest result MAY be persisted/presented as **trusted** only when a **`policy="strict"`** assessment
returns `trusted == True` (equivalently `verdict == "trusted"`, i.e. no blocker issues). If the strict
assessment returns `verdict == "blocked"`, the facility MUST NOT persist the result as trusted — either
refuse the run or persist it explicitly labeled not-trusted (§3).

Pseudocode the facility must honor:

```python
assessment = QualityGateService.assess(db, GateRequest(consumer="backtesting", policy="strict", ...))
if not assessment.trusted:                      # verdict == blocked
    # refuse to persist trusted results; surface assessment.issues to the user
    raise QualityGateBlocked(assessment)
# else: verdict == trusted → safe to persist trusted backtest metrics
```

## 3. Exploratory runs

Exploratory/degraded-data backtests run with `policy="advisory"`. Advisory downgrades blocker issues to
`verdict == "warning"` with `trusted == False`. Such runs MAY proceed and persist, but their output MUST
be **visibly labeled not-trusted** in every surface (UI, exports, API) and MUST NOT contribute to trusted
Scorecard metrics (§5). Never present an advisory/`warning`/`blocked`/`skipped` result as a trusted
performance claim.

## 4. Durable evidence

Every persisted backtest result record MUST include a durable `quality_gate` JSONB field holding the full
`QualityGateAssessment` (`schema_version`, `policy`, `verdict`, `trusted`, `scope`, `issues`, `warnings`,
`generated_at`) — mirroring the existing precedent `ScannerRun.quality_gate`
(`backend/app/models/scanner_run.py`). This makes the trust decision auditable after the fact and lets the
UI/Scorecard filter without re-running the gate.

## 5. Verdict → UI / Scorecard effects

| `verdict` | `trusted` | Backtest UI | Trusted Scorecard metrics (#497) |
|---|---|---|---|
| `trusted` | True | shown normally | **included** |
| `warning` | False | shown with a "data-quality warnings — not trusted" badge; `warnings` listed | **excluded** |
| `blocked` | False | trusted persistence refused; if run is exploratory, shown not-trusted with `issues` listed | **excluded** |
| `skipped` | False | gate not applied (`policy="off"`); treat as ungated/not-trusted | **excluded** |

Scorecard already excludes untrusted events (#497); backtest results follow the same rule keyed off the
persisted `quality_gate.trusted`.

## 6. Survivorship bias (#501) interaction

Because `consumer="backtesting"` is a historical-analysis scope and MarketHawk has no delisted-symbol /
survivorship tracking yet, the gate emits `survivorship_bias` for backtest universes. Under `policy="strict"`
this is a **blocker** → trusted backtests are blocked until a universe can be proven survivorship-safe (the
future unblock path documented on `_build_assessment` in `quality_gate.py`). Until then, trusted backtest
persistence will be refused for ordinary universes; exploratory (`advisory`) runs proceed labeled
not-trusted. This is intentional: survivorship-biased performance numbers must not be presented as trusted.

## 7. Linkage

When the backtesting epic/first-persistence slice is created, link it to this contract and to #491. The
persistence slice's definition-of-done MUST include: the strict preflight (§1–2), the `quality_gate` JSONB
field (§4), the not-trusted labeling (§3, §5), and Scorecard exclusion of untrusted backtests (§5).
