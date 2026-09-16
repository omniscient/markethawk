---
universe_id: 7
universe_name: Active, 100M+ caps
ticker_count: 3893
start_date: 2025-06-01
end_date: 2026-05-31
max_hold_sessions: 10
strategies:
  backtest-tight-2pct-2to1: {entry: market, stop_pct: 2.0, rr: 2.0, sessions: [regular]}
  backtest-loose-4pct-1.5to1: {entry: market, stop_pct: 4.0, rr: 1.5, sessions: [regular]}
  backtest-pullback-limit-2pct-2to1: {entry: limit, limit_offset_pct: -0.5, stop_pct: 2.0, rr: 2.0, sessions: [regular, pre]}}
generated_at: 2026-06-20T03:07:38Z
harness_issue: "301"
---

> **Note — `pre_market_volume_spike`**: this scanner fires on intraday pre-market minute bars.
> Where those are absent in the replay window the harness uses stored `ScannerEvent` rows only.
> Interpret its row against `trade_count`; a low count indicates limited historical data coverage.

## Expectancy (R)

| Scanner | tight-2pct-2to1 | loose-4pct-1.5to1 | pullback-limit |
|---------|---|---|---|
| trend_pullback | N/A ⚠* | N/A ⚠* | N/A ⚠* |
| oversold_bounce | -1.000 ⚠* | 1.500 ⚠* | N/A ⚠* |
| pocket_pivot | -0.087 | -0.121 | -0.097 |
| pre_market_volume_spike | 0.500 ⚠* | 0.250 ⚠* | N/A ⚠* |
| liquidity_hunt | 0.714 ⚠* | 1.143 ⚠* | 2.000 ⚠* |

## Profit Factor

| Scanner | tight-2pct-2to1 | loose-4pct-1.5to1 | pullback-limit |
|---------|---|---|---|
| trend_pullback | N/A ⚠* | N/A ⚠* | N/A ⚠* |
| oversold_bounce | 0.00 ⚠* | inf ⚠* | N/A ⚠* |
| pocket_pivot | 0.86 | 0.77 | 0.85 |
| pre_market_volume_spike | 2.00 ⚠* | 1.50 ⚠* | N/A ⚠* |
| liquidity_hunt | 2.67 ⚠* | 9.00 ⚠* | inf ⚠* |

## Win Rate (%)

| Scanner | tight-2pct-2to1 | loose-4pct-1.5to1 | pullback-limit |
|---------|---|---|---|
| trend_pullback | N/A ⚠* | N/A ⚠* | N/A ⚠* |
| oversold_bounce | 0.0% ⚠* | 100.0% ⚠* | N/A ⚠* |
| pocket_pivot | 29.6% | 34.8% | 29.1% |
| pre_market_volume_spike | 50.0% ⚠* | 50.0% ⚠* | N/A ⚠* |
| liquidity_hunt | 57.1% ⚠* | 85.7% ⚠* | 100.0% ⚠* |

## Max Drawdown (%)

| Scanner | tight-2pct-2to1 | loose-4pct-1.5to1 | pullback-limit |
|---------|---|---|---|
| trend_pullback | N/A ⚠* | N/A ⚠* | N/A ⚠* |
| oversold_bounce | 1.00 ⚠* | 0.00 ⚠* | N/A ⚠* |
| pocket_pivot | 694.99 | 763.35 | 53.19 |
| pre_market_volume_spike | 1.00 ⚠* | 1.00 ⚠* | N/A ⚠* |
| liquidity_hunt | 2.00 ⚠* | 1.00 ⚠* | 0.00 ⚠* |

## Trade Count

| Scanner | tight-2pct-2to1 | loose-4pct-1.5to1 | pullback-limit |
|---------|---|---|---|
| trend_pullback | 0 ⚠* | 0 ⚠* | 0 ⚠* |
| oversold_bounce | 1 ⚠* | 1 ⚠* | 0 ⚠* |
| pocket_pivot | 5015 | 5015 | 361 |
| pre_market_volume_spike | 2 ⚠* | 2 ⚠* | 0 ⚠* |
| liquidity_hunt | 7 ⚠* | 7 ⚠* | 1 ⚠* |

⚠ Cells with fewer than 20 trades are marked with *.

## Findings

No combos with positive expectancy and ≥ 20 trades.

Best combo: N/A

Scanners negative across all strategies: trend_pullback, pocket_pivot
