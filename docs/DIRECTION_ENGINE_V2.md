# Decision Engine v2 — market-adaptive demo research
Preserves all 100 candidate IDs and original scanner rules (95 implemented,
5 deferred). Every candidate has one primary manually assigned strategy
family. Uses 1h/4h EMA50/EMA200 and ADX (25 trending, below 20 ranging);
disagreement/missing observations are mixed/unknown. Separately flags high
volatility when ready 5m/15m ATR percentile is >=80. All values are research
heuristics, not calibrated thresholds.

Each distinct strategy votes once; conflicting frames abstain. Family
weights depend on regime, with modest volatility adjustments. The first
same-family same-direction vote contributes full weight, next two add 25%
each, and the rest add no marginal score. This is a family proxy for
correlation, not empirical correlation measurement. The higher weighted
score selects direction; ties are neutral. No new confidence/equity/loss
thresholds or exchange policy changes. AI still controls plan construction.

Every scan with a valid fresh mark quote records unique signal/frame/side/
candle observations, even without an AI request. First observed mark at
15m, 1h and 4h within five minutes of maturity is scored as signed gross
mark-price return in basis points. Missed windows are reported, not filled
with invented values. Overlapping samples are not independent. These are
not actual trade P&L, do not include fees, spread, funding, or actual
entry/exit execution. Existing order journal and lifecycle are unchanged.
Dashboard provides direction, scores, regime and research aggregates.

Automatic learned weights are intentionally not enabled. Next steps:
walk-forward historical replay without lookahead, net-cost simulation,
empirical correlation estimation and per-regime out-of-sample calibration
before learning changes execution weights. Actual trade P&L attribution
remains a separate pending task.
