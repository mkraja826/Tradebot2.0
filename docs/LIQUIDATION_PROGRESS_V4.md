# V4 progress-sensitive exit research

Freeze V3 continuation retest entries and initial brackets. Reproduce all
three V3 exit controls before comparing 13 new policies: fee-only break-even,
and both 1m/3m trailing with fee, 0.5R or 1R activation, with/without early
fee break-even. Only prior completed minute closes qualify; stop cannot widen.
Fee break-even solves modeled round-trip fee and 2bps exit slip, not a guarantee
against price gaps. Evaluate at 0/2/5 bps exit slippage, same fixed target and
60-minute reserved horizon. Full-horizon, pre-exit and post-exit excursions
are hypothetical bounds; exclude ambiguous exit candle in pre/post metrics.
No candidate selection, no live changes.

```sh
python -m recover_trading.liquidation_progress_v4 --market-root /var/lib/recover-trading/demo/BTCUSD --v3-report ~/liquidation_v3_results.json
```
