# Liquidation entry V3 research

Five policies: V1 breakout control, relative-intensity breakout, reversal
retest, relative-intensity reversal retest, continuation retest. Each shares
the original qualifying V1 burst universe and a fixed 71-minute reservation
independent of outcomes. Thus the control is not the earlier eight trades.
Retest requires a close outside the last five completed pre-observation
minutes, then a separate candle touching the level and closing beyond it
within ten minutes. Price recovery is an exhaustion proxy, not verified
liquidation cessation. Relative flow >=2 times median of at least six positive
same-side prior observations in two hours, spaced at least eight minutes;
missing reference is unknown, never zero. These thresholds are illustrative.

Compare fixed stop, immediate 1m V4 and immediate 3m V2 with same initial
structural stop, fixed 2R research target, 60-minute hold, 15 bps round-trip
fees, 2 bps entry and 0/2/5 bps exit slippage. Report per-trade and per-known
opportunity results, including missed entries and unknown coverage separately.
Also compare all policies on common-known opportunity IDs. No automatic selection.

Run read-only on VM:
```sh
python -m recover_trading.liquidation_entry_v3 --market-root /var/lib/recover-trading/demo/BTCUSD --hypotheses-db /var/lib/recover-trading/liquidation-research/hypotheses.sqlite --start 1795601700 --split 1795644000 --end 1795683420
```

Previously inspected period is exploratory only. Collect a new prospective
sample before choosing a strategy. No trading engine, plugin registration,
Gold or live activation changes.
