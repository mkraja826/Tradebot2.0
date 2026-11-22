# Read-only candle anomaly evidence inventory — BTC and Gold

## What this actually proves
Existing `delta-demo-candles.sqlite` can be complete, have missing historical
timestamps, retain quarantined original prices, or contain suspicious
neighbor-dislocated extremes. This tool identifies the **exact UTC five-minute
timestamps** to investigate. It is not an independent exchange attestation
and **never authorizes FIRE**.

```bash
.venv/bin/python -m tradebot.candle_anomaly_inventory --data-dir data
```

This reads SQLite via URI `mode=ro` and `PRAGMA query_only=ON` under a
single consistent transaction, checks integrity/schema, and reports for BTCUSD
and XAUTUSD current/previous UTC months:
- expected/retained bar counts
- genuinely missing timestamps (not counting deliberate quarantine)
- quarantined timestamps and count
- suspected extreme timestamps and count from adjacent archive candles
- up to eight examples of each category and explicit truncation flags
- issue codes and `safe_to_enable_fire=false`

The output has **no wallet balances, API credentials, trade identifiers,
broker orders, AI requests, report persistence or ledger changes**.

You can also obtain the same summary from the existing
`ops/run_btc_demo_release_audit.sh` after its source update.

## How to research suspicious BTC bars
For an exact aligned UTC time emitted by this tool, call the existing
`tradebot.independent_spot_triage --at 2026-11-01T00:00:00+00:00` in
a private read-only environment. It compares Delta traded 5m / 1m / mark
candles and publicly available Coinbase BTC-USD spot at the identical UTC
bucket. Replace the example time with a **real emitted timestamp**; the example
is not a known suspect.

Coinbase spot is a different product from Delta BTCUSD perpetual, so a match or
mismatch alone cannot prove a Delta print is accurate or allow automatic
replacement of archived prices. Preserve original local and API evidence for
independent review. Do not remove quarantine or replace missing bars with
synthetic candles. If the broker never supplies a missing Gold bar, its
monthly period remains unavailable.

## Release status
A clean inventory **is not sufficient**: M09 full account broker-wallet
reconciliation, actual verified equity checkpoints, current leverage/isolated
margin and full-account flatness, deployment continuity, independent
protective-order test, and independent release review must also pass.
