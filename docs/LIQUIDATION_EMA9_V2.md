# Liquidation V2: matched six-timeframe exit research

Offline-only. Reuse a V1 JSON report, frozen entries and brackets; reproduce the
original fixed and 15m V8 outcomes before any new comparison. If any entry or
price path differs, stop and report the mismatch rather than silently change the
cohort. 48 variants (six frames, eight buffers/activation combinations). 0/2/5
bps additional exit slip. Per-frame eligible IDs, excluded IDs, common subset
across nonempty frames, and reversal/continuation/development/holdout splits.
No candidate is automatically promoted. No independent holdout remains after
inspection. No live execution changes or MCP registration changes.

```sh
python -m recover_trading.liquidation_ema9_multiframe --market-root /var/lib/recover-trading/demo/BTCUSD --v1-report ~/liquidation_ema9_results.json
```

Outputs JSON to stdout. Actual historical candles and original report required.
Do not run on Gold or infer missing liquidation events.
