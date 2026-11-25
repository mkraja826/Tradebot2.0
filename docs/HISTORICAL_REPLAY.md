# Offline historical replay v1
Run only on historical.sqlite or a separate read-only copy of the market
database. The replay uses the exact recovered strategy scanner and regime
engine on data available at each historical decision timestamp. It does
not reconstruct unavailable real-time feeds or macro releases.
An entry is simulated at the open of the candle one full five-minute bar
after the decision. Exit is simulated at the open 15m, 1h or 4h after
entry. All intermediate candle timestamps must exist and validate.
Round-trip cost defaults to an illustrative 15 basis points of notional,
not a verified exchange fee schedule. No leverage, funding, liquidation,
AI calls, portfolio compounding or SL/TP simulation. Per-rule observations
are deduplicated by signal candle and non-overlapping per horizon.
The equal-vote and adaptive ensembles are compared as periodic directional
hypotheses, not as exact replicas of the live order scheduler.
Development/holdout split is chronological 70/30, purging any outcomes
whose final candle crosses a boundary. Holdout results are not used to
fit or deploy weights. Output contains coverage for all implemented IDs,
deferred IDs, counts, per-rule/per-regime summaries and individual events.
Small samples are descriptive only.

Backfill uses only public demo candle endpoints, validates each complete
window, and records unavailable/conflicting windows; no fabricated bars.
It cannot supply historical book/flow/macro data. Example:
python -m recover_trading.backfill --database /tmp/historical.sqlite --symbol BTCUSD --start 1795305600 --end 1795564800 --frames 5m 15m 1h 4h 1d
python -m recover_trading.backtest --database /tmp/historical.sqlite --symbol BTCUSD --start 1795305600 --end 1795564800 --output /tmp/btc-replay.json
