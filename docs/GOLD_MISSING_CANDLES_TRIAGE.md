# Gold historical 3-bar gap — exact public-provider probe

The original approved VM's read-only 22 Nov 2026 audit found **3** missing
XAUTUSD previous-month UTC 5-minute archive candles (2026-10-29 22:10,
22:15, 22:20 UTC). We must not fill the original archive with guesses,
copy from BTC, or assume a valid latest quote repairs historical coverage.

After staging a reviewed merged revision separately from the active watchdog,
run once on the approved VM (no API keys, no paid AI):

```bash
ROOT="$HOME/Tradebot2.0"
STAGE="$HOME/Tradebot2.0-release-stage"
PYTHONPATH="$STAGE/src" PYTHONDONTWRITEBYTECODE=1 \
  "$ROOT/.venv/bin/python" -m tradebot.candle_gold_gap_probe \
  --data-dir "$ROOT/data"
```

This checks the **actual exact missing timestamp inventory** in the original
`delta-demo-candles.sqlite` with read-only SQLite, then performs two
public Delta India DEMO GETs per timestamp: one 5-minute traded bar and five
1-minute traded bars. Bounded to at most 8 source timestamps from the *previous
UTC month*; refuses truncated or malformed inventory. The output includes
only UTC timestamps and bounded source-presence / 1m-vs-5m agreement flags,
**not** prices, volumes, credentials or account data. No financial or candle
database writes, service restarts, provider credentials or broker POST calls.

If the signed-off public source returns matching complete historical
records, that is a **lead for a future separately reviewed collector repair**,
not a fix: original broker archive remains missing until the rate-limited
collector performs a protected post-backup refetch in a controlled deployment.
If public 5m bars are absent, invalid or inconsistent with 1m, leave the
period blocked and seek original broker evidence. Matching same-provider
resolutions are not independent market/price authenticity proof.

This diagnostic intentionally exits code 2 and never enables FIRE. Gold's
historic anomalies, BTC suspicious extremes, authentic equity openings,
wallet reconciliation, signed isolated-margin evidence, and real off-host
notification acknowledgements remain independent gates.
