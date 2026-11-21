# BTCUSD suspicious historic candles — source cross-check (diagnostic-only)

The active VM's public BTCUSD 5m Delta India DEMO feed exactly reproduced
four flagged monthly OHLCV samples on 21 Nov 2026, including the extreme
2026-11-04 13:15 UTC low **0.1**. This establishes **same-source repeatability**,
NOT authenticity of the price, a trade print, or permission to use it.

The existing `CandleArchive.levels` marks affected months
`suspicious_extreme` and suppresses usable high/low. The FIRE controller
requires `provisionally_valid` for *all* six periods and rejects an entry
before AI/model request if any period fails. **Do not bypass that gate**.

## Read-only supplementary diagnostic

Delta's documented historical candle endpoint supports `1m`, `5m`,
and `MARK:BTCUSD` market data. This module uses only unauthenticated GETs
to compare an exact anomalous 5m traded candle against an aggregation of
five 1m traded candles and the same-time 5m **mark-price** candle.
All sources are from the **same** Delta DEMO provider: agreement is neither
independent corroboration nor trade/fill evidence. Mark prices are a
different series and **must not replace** traded OHLC.

Review the branch/source/tests before running on the VM. Run in the isolated
venv; no credentials, data directory, or runtime services are required:

```bash
cd ~/Tradebot2.0-review
.venv/bin/python -m tradebot.candle_source_diagnostic \
  --at '2026-11-04T13:00:00+00:00' \
  --at '2026-11-04T13:15:00+00:00' \
  --at '2026-10-23T08:40:00+00:00' \
  --at '2026-10-23T08:10:00+00:00'
```

It returns sanitized JSON with traded high/low, 1m-aggregated high/low,
mark high/low, OHLC and volume equality, fixed blocker codes, and
`trade_authorized=false` regardless of output. It does not read/edit any
SQLite archive, create recovery tables, write snapshots, call AI, load
credentials, change leverage, or place/cancel orders.

- Exit **0**: comparison completed (NOT independent validation, no correction,
  no trading authorization).
- Exit **2**: incomplete, malformed, inconsistent, or failed market reads.
  Don't relax the time-alignment, missing-minute, or schema gates.

**Recovery requires separate review:** preserve original rows including
quarantine, capture immutable hashed source request/response evidence off
the service, compare truly independent trade/price sources and actual
exchange transaction or trade prints, establish approved replacement
provenance, verify on a disposable database copy, and only then consider
a supervised archive repair. Restoring a valid monthly period requires
*complete and trustworthy 5m bars* (not just deleting the extremes). No
backfill or synthetic price interpolation should be used to force a green
FIRE decision. Do not touch the Gold recovery lock or the active VM.
