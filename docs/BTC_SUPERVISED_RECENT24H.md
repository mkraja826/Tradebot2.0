# BTC pilot — explicitly scoped recent 24-hour market context (source-only)

The normal GPT-6 FIRE decision requires verified current/previous UTC day,
week and month highs/lows. The original Delta DEMO archive still contains
historical BTC monthly extreme anomalies; it would be unsafe to supply
those month-derived highs/lows to GPT-6 without independent corroboration.

This separate **non-authorizing** module checks only the 288 completed
BTCUSD 5-minute bars immediately preceding the evaluation time against the
original archive in SQLite `mode=ro`. It requires:
- Original archive present, schema and `quick_check` valid
- BTC coverage cursor at or beyond the latest completed 5m boundary
- Exactly 288 contiguous, correctly aligned original bars
- No quarantined bars within the recent 24-hour interval
- Valid finite OHLCV and no suspect extreme neighbor dislocations

The result `recent24h_local_candidate_only` is a **development lead** for
a **separate supervised GPT-6 pilot strategy** with a restricted model prompt
that does not request month-derived extremes. It does **not** certify
independent BTC perpetual market authenticity; same-venue candle data is
insufficient evidence of real trade prints. Historical monthly anomalies are
left untouched in the original DB and remain blocked in the normal FIRE
execution engine.

After merging, stage reviewed source in the separate checkout:

```bash
ROOT="$HOME/Tradebot2.0"
STAGE="$HOME/Tradebot2.0-release-stage"
PYTHONPATH="$STAGE/src" PYTHONDONTWRITEBYTECODE=1 \
"$ROOT/.venv/bin/python" -m tradebot.btc_supervised_recent24h \
--data-dir "$ROOT/data"
```

No credentials, paid AI, broker GET/POST, database edits, leverage changes,
service restarts or new FIRE orders. CLI always exits 2. A future
one-attempt controller must still implement a separate validated strategy,
fresh signed DEMO account margin-mode and account-wide exposure checks,
session equity rechecks, per-trade loss/reward limits, broker-side SL/TP,
durable closeout and independent operator signoff. No automatic deployment.
