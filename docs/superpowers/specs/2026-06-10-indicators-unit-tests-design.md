# Unit Tests for calculateDoubleSuperTrend — Design

**Date:** 2026-06-10
**Status:** Spec pending review
**Issue:** #249
**Author:** Brainstormed with Claude (Opus 4.8)

## Problem

`frontend/src/utils/indicators.ts` exports `calculateDoubleSuperTrend`, a pure TypeScript function that implements a Double SuperTrend ATR indicator (translated from Pine Script). The function contains non-trivial recursive math across six distinct logical branches (short-data guard, ATR initialization, ATR warm-up average, Wilder RMA, TUp/TDown clamping, trend flip/carry). No unit tests exist for it, so regressions in the indicator math go undetected until they appear visually on charts.

This issue was filed as a scope-spillover from #198, where the factory noticed the gap but could not fix it in-scope.

## Goal

Add a colocated Vitest test file (`frontend/src/utils/indicators.test.ts`) with comprehensive, deterministic tests for `calculateDoubleSuperTrend` that:

1. Cover all six distinct behavioral paths with named, independent test cases.
2. Assert exact numeric outputs from hand-computed fixtures (not just shape), using `toBeCloseTo` for float comparisons.
3. Pass cleanly under the existing Vitest config (`vitest.config.ts`) and coverage thresholds without requiring any config changes.

## Non-Goals

- Testing `OHLCVInput` / `DoubleSuperTrendPoint` as runtime type checks — they are compile-time TypeScript interfaces with no runtime presence; they are exercised implicitly via typed fixtures.
- Adding a separate utility test helper directory or refactoring `indicators.ts`.
- Changing coverage thresholds (existing 18/18/13/19 thresholds are already met by other tests; this addition only improves coverage).

## Requirements

Derived from Q&A with the product-owner subagent:

1. **File location**: `frontend/src/utils/indicators.test.ts` — colocated with source, matching project convention (`client.ts` → `client.test.ts`).
2. **Import style**: named imports from `'vitest'` (`describe`, `it`, `expect`) — no jest-style globals, consistent with all existing test files.
3. **Short-data guard**: test returns `[]` for empty input and for any input with `data.length < atrPeriod`.
4. **Boundary**: exactly `atrPeriod` rows produces a result array of length equal to `data.length`.
5. **ATR seeding** (`i === 0`): first bar ATR equals the True Range of bar 0.
6. **ATR warm-up** (`i < atrPeriod`): bars 1..(atrPeriod−1) use a running simple average; verify against hand-computed value.
7. **ATR RMA** (`i >= atrPeriod`): bars ≥ atrPeriod use Wilder's RMA `(prev * (n-1) + tr) / n`; verify against hand-computed value.
8. **TUp clamping**: when `prev.Close > prevTUp`, `tUp = Math.max(up, prevTUp)` — construct a monotone-rising fixture to exercise the `Math.max` path.
9. **TDown clamping**: when `prev.Close < prevTDown`, `tDown = Math.min(dn, prevTDown)` — construct a monotone-falling fixture to exercise the `Math.min` path.
10. **Trend flip to +1**: closing above `prevTDown` forces `trend = 1`; `tsl1` becomes `tUp`, `tsl2` becomes `tDown`.
11. **Trend flip to −1**: closing below `prevTUp` forces `trend = -1`; `tsl1` becomes `tDown`, `tsl2` becomes `tUp`.
12. **Trend carry-over**: close sitting between `prevTUp` and `prevTDown` leaves `trend` unchanged from prior bar.
13. **Default parameters**: calling with only a data array (no `factor` / `atrPeriod` args) produces the same result as calling with `factor=3, atrPeriod=12`.
14. **`time` passthrough**: each output point's `time` field equals the corresponding input bar's `time`.

## Architecture / Approach

### Single approach: colocated pure-function test file

`calculateDoubleSuperTrend` has no imports, no side effects, no DOM, no network, and no async operations. It is completely self-contained. Tests require:

- No mocks or spies.
- No test utilities beyond Vitest's built-in `describe`/`it`/`expect`.
- No DOM environment features (but `jsdom` environment from `vitest.config.ts` is harmless).

**Fixture strategy**: build small, deterministic OHLCV sequences (5–15 bars) where the expected output values can be hand-computed in comments alongside the assertion. Use `atrPeriod=3` or `atrPeriod=4` in most tests (instead of the default 12) to keep fixtures short while still exercising the RMA phase (requires `data.length >= atrPeriod`).

**Float comparisons**: use `expect(value).toBeCloseTo(expected, 6)` for computed numeric fields (`tsl1`, `tsl2`) to tolerate floating-point rounding. Use strict equality for `trend` (always ±1 integer) and `time` (passthrough).

## Alternatives Considered

**A. Snapshot tests**: capture output as a JSON snapshot for a reference dataset. Rejected because snapshots assert shape but not mathematical correctness — they pass even if the formula changes to produce systematically wrong values. Named numeric assertions are more resistant to silent regressions.

**B. Property-based tests (fast-check)**: generate random OHLCV inputs and assert invariants (e.g., result length equals input length when `data.length >= atrPeriod`). Rejected for v1 — the invariants are too coarse to catch formula bugs in the ATR/TUp/TDown math. Targeted hand-computed cases are more effective at pinning the specific algorithmic logic the issue flags as risky.

## Open Questions

None blocking.

## Assumptions

- The existing `vitest.config.ts` coverage thresholds (18/18/13/19) will be met or exceeded after this test file is added — no threshold changes needed.
- `frontend/tsconfig.json` already excludes `**/*.test.ts` from the production build (per the `frontend-patterns.md` pattern from issue #193) — no tsconfig changes needed.
- The `test-setup.ts` patches (jsdom globals) are not needed for a pure-function test, but the existing `setupFiles` entry does not interfere.
- Using `atrPeriod=3` or `atrPeriod=4` in most fixtures is an acceptable simplification; the same code paths run regardless of period length.
