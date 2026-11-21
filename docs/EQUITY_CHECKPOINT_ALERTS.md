# UTC equity opening checkpoint health alerts

**Milestone 1 candidate:** collection moves to a dedicated read-only service.
Deploy the collector together with the watchdog changes; see
[recovery, validation and rollback instructions](EQUITY_CHECKPOINT_RECOVERY.md).
The description below records the original PR #2 behavior.

The independent watchdog collects a **signed Delta DEMO wallet equity**
observation roughly once per minute. The FIRE portfolio equity guard requires
an *actual observation in the first 5 minutes* of both the current UTC day and
UTC week. Missing historical anchors cannot be backfilled or inferred.

New diagnostic `checkpoint_health` reads the existing SQLite evidence in
`mode=ro`, makes no broker/AI calls, and never authorizes trades. Statuses:

- `healthy`: daily and weekly checkpoints verified, recent signed observation
- `checkpoint_pending`: currently inside the opening window; not yet recorded
- `checkpoint_missed`: one or both opening windows expired without evidence
- `evidence_stale`: no recent observation, even if opening anchors are valid
- `evidence_unavailable`: risk ledger absent, corrupt or unreadable

A legacy opening observation without its original authenticated-wallet
transport receipt is **not** considered verified. The daily/weekly field
reports `unverified_receipt`; a recent latest observation without that
receipt also uses `observation_status=unverified_receipt`. Both block
`checkpoint_prerequisites_met` and publish the sanitized
`equity_read_receipt_invalid` alert. This is distinct from a missing
opening window and does not cause data repair, backfill or trade execution.

The read-only dashboard `GET /api/risk/checkpoints` exposes the status,
UTC opening-window boundaries, freshness, `blocking_conditions` and
`alert_codes`, but no API credentials or wallet balances.

The watchdog emits a sanitized `equity_checkpoint_health` JSON event
immediately on status transition and then at most every 5 minutes for the
same status. Typical event:

```json
{"event":"equity_checkpoint_health","status":"checkpoint_missed","daily_checkpoint":"missed_window","weekly_checkpoint":"missed_window","alert_codes":["missed_daily_checkpoint","missed_weekly_checkpoint"],"action":"block_new_fire_until_signed_equity_limits_pass"}
```

`checkpoint_prerequisites_met` is only evidence diagnostics; real trade
entry remains independently gated by `PortfolioEquityGuard.require_approved`,
all existing broker risk checks, and operator consent.

Before UTC daily open at 00:00, ensure the watchdog is running and has fresh
authenticated credentials. If an opening window is missed, do not fabricate
equity observations or reset the guard; the missing weekly anchor normally
cannot be replaced until the next Monday 00:00 UTC.

Verification after staging (no orders, no AI):

```bash
python3 - <<'PY'
import json
from urllib.request import urlopen
with urlopen("http://127.0.0.1:8765/api/risk/checkpoints", timeout=5) as r:
    print(json.dumps(json.load(r), indent=2))
PY
```
