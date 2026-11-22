# Historical candle revision integrity — fail closed

## Problem
Delta India DEMO's 5-minute archive previously used `INSERT OR REPLACE` for
already-seen candles. A second broker GET changing the high, low or any other
stored economic field could silently replace the first historical observation.
A changed source price is evidence of uncertainty, not permission to overwrite
or release historical trading levels.

## Source hardening
- Existing closed candles remain unchanged on identical refetches.
- A conflicting refetch is moved to `candle_quarantine` with reason
  `conflicting_historical_refetch`, preserving the first previously stored row.
- Conflicting duplicate candles within one broker response are also quarantined.
- Nearby already-stored page-edge bars are consulted when detecting new
  extreme dislocations. Quarantined bars are never silently reintroduced.
- Any period missing a quarantined candle reports quality
  `quarantined`, null high/low, and is rejected by the existing FIRE
  archive-quality gate.

## Deployment and release constraints
This change deliberately does **not** alter existing old extremes, repair the
archive, replace prices using Coinbase spot, or authorize BTC execution. It
does **not** delete or rewrite existing historical quarantines, wallet ledgers,
receipt histories or risk checkpoints. Verify the new code and tests in CI.
Before updating the active archive collector, verify a restorable SQLite
backup plus WAL continuity and confirm no active positions or pending
order-supervision interventions; otherwise defer its deployment.

Old BTC month / previous-month data remain blocked until independent source
investigation and an explicitly reviewed operator recovery procedure. Legitimate
market anomalies may require approved release based on actual broker evidence;
a historical spike cannot be assumed to be a bad print.
