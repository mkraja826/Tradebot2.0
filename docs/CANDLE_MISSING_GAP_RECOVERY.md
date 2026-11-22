# Bounded recovery of gaps in scanned Delta DEMO candle history

## Why this matters
Previously, a completed historical cursor could leave interior 5-minute bars
missing forever: `CandleArchive.sync_page` revisited only the newest
forward page or an old backward page, then returned when its cursors met.
That leaves affected periods `incomplete`, even if a later authenticated
public broker GET would return the missing bar. Gold's previously observed
previous-month 8925/8928 count is a motivating example; source code alone
cannot prove that Delta will return the three missing candles.

## New behavior
After the initial forward and backward scans are complete, a collector may
request **one genuine missing, previously scanned 5-minute timestamp** per
`sync_page` iteration. The request is a public Delta India DEMO candle GET
and uses the same existing timestamp/OHLCV validation and conflict-quarantine
logic. It cannot insert guessed/interpolated OHLCV data.

- Scans at most the previous **75 days**.
- Skips every timestamp already present or intentionally quarantined.
- Records an attempted missing timestamp in a durable SQLite
  `candle_gap_attempts` table before fetching, so even failed GETs cannot
  hammer the broker across restarts.
- Retries an unavailable bar no more often than once per **24 hours**.
- Caps all recovery probes across markets to **four per rolling hour**.
- Preserves the original candles and never clears quarantine for conflicting
  broker revisions. Existing rejected periods continue to have unavailable
  highs/lows until actual complete non-quarantined evidence exists.
- No leverage, equity, wallet, FIRE, orders, AI or service settings change.

The small additional table is an additive archive-only schema change.
It does not alter financial/equity ledgers or historical brokerage receipts.

## Validation and rollout
CI covers a successful broker re-fetch, broker repeatedly withholding a
missing bar, protection against quarantine bypass, and sustained rate limits.

**VM deployment and broker recovery are not performed by the GitHub merge.**
Before deploying the collector, retain a SQLite-consistent backup of
`history.sqlite` including its WAL state and check exposure and independent
watchdog continuity. After a reviewed restart, compare month/previous-month
`bars` vs `expected`, `quality_status` and `quarantined_bars` using the
unchanged read-only dashboard. Do not interpret `scanned_to_launch` as proof
of complete candles or independent price integrity.

An old BTC `suspicious_extreme` period still needs trusted source
investigation, not gap recovery. Missing broker records after retry remain
`incomplete`; do not edit, assume zero-volume bars or override the FIRE
history-quality gate to force an order.
