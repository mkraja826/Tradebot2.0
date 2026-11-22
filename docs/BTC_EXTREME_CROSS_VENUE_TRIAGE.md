# BTC previous/current month extreme cross-venue investigation

The release checklist shows BTCUSD monthly and previous-month historical
periods as `suspicious_extreme`, with highs/lows withheld from FIRE. PR #18
already added public Delta 5m/1m/mark + free Coinbase BTC-USD spot comparisons,
but required the operator to manually type a suspicious time. This safe
read-only workflow *selects up to four real suspicious extrema from the
existing original local candle archive* and runs that comparison automatically.

## Operator read-only command (after approved code/VM deployment)

```bash
cd ~/Tradebot2.0
export PYTHONPATH="$PWD/src"
.venv/bin/python -m tradebot.candle_extreme_crosscheck --data-dir "$PWD/data"
```

No credentials or cost-bearing AI are required. The diagnostic reads
`data/delta-demo-candles.sqlite` via SQLite URI `mode=ro` and
`PRAGMA query_only=ON` in a consistent transaction. It takes at most four
candidate timestamps across the previous and current UTC month, including
only complete five-minute buckets. It selects the highest/lowest archived
candles and applies the same neighboring-candle anomaly heuristic as
`market_integrity.archive_extreme_suspicious`.

For each selected timestamp it uses only public HTTP GETs: Delta DEMO 5m
traded, five 1m traded, Delta DEMO mark-price 5m, and Coinbase Exchange
BTC-USD 5m spot. The existing reader rejects malformed or missing candles,
cross-resolution inconsistency and extreme differences. The output records
exact UTC times and public comparison outcomes.

**Source agreement is NOT proof that the Delta BTCUSD perpetual traded print
was valid.** Coinbase is spot, not perpetual; Delta's 1m/5m can share the
same underlying source; mark prices are not trade prints. Broker data
revisions can be genuine or anomalous. Human/independent evidence review
remains essential before any quarantine or data-quality clearance.

Important restrictions:

- No archive repair, deletes, migrations, prices invented, quarantine
  releases, manual edits, historical receipt changes or broker order calls.
- No live-money endpoint; authenticated broker account calls are absent.
- The CLI *always exits 2*, even if every comparison returned context.
  `trade_authorized`, `safe_to_enable_fire`,
  `independent_perpetual_price_proven`, and
  `quarantine_release_authorized` are always false.
- Existing previous/current month quality-status flags remain blocked.
- A failure to find candidates is NOT evidence of market validity; unusual
  non-extreme or missing market data may still exist, and the scan only
  investigates bounded extrema.
- For operational sequencing, also run the signed wallet M09 checks, real
  equity checkpoints, leverage/isolated margin and account-wide flatness,
  watchdog/alert recovery and independent release review.

The existing one-command `ops/run_btc_demo_release_audit.sh` now invokes this
read-only cross-venue context check as one of its permanently nonauthorizing
stages, avoiding repeated manual time selection.
