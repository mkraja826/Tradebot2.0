# V5 market structure / liquidation confluence research

Five matched policies on the V3 continuation-retest cohort: unfiltered
control, confirmed 15m EMA9/21 alignment, 2R room to nearest confirmed
60-minute swing obstacle, target distance at least twice assumed 22bps
round-trip cost, and all three conditions. These are illustrative hypotheses,
not fitted thresholds. Context uses the confirmation close (before the entry
open); original V3 brackets and fixed-stop exit stay unchanged. No observed
obstacle is unknown, not unlimited room. Unknown and no-trade counts separate.
All available and common-known results at 0/2/5bps exit slippage.

```sh
python -m recover_trading.liquidation_structure_v5 --market-root /var/lib/recover-trading/demo/BTCUSD --hypotheses-db /var/lib/recover-trading/liquidation-research/hypotheses.sqlite --start 1795601700 --split 1795644000 --end 1795683420
```

The previous period is exploratory only. Freeze V5 and gather later
opportunities; avoid repeatedly optimizing against the original four trades.
No live execution, account, broker or deployment changes.
