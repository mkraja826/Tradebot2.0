# Equity checkpoint integrity — Milestone 1 candidate

This release is source implementation with offline verification. It is **not
VM deployment, broker commissioning, recovery of missed openings or permission
to trade**. BTC and Gold FIRE must remain disabled; the consumed Gold
commissioning lock must remain intact. No historical checkpoints are created.

## What changes

- A dedicated read-only `tradebot.equity_monitor` process records one
  authenticated Delta India DEMO wallet read approximately every 60 seconds.
  Collection runs independently of the protective watchdog. A corrupt equity
  DB, wallet timeout or clock failure cannot stop watchdog SL/TP checks.
- UTC daily and Monday weekly openings still require genuine observations
  inside the existing 300-second window (the exact 00:05:00 boundary remains
  inclusive). Daily 00:00–00:05 UTC is **05:30–05:35 IST**; Monday UTC opening
  is Monday at the same IST times. No timezone-dependent local-midnight anchor.
- New reads retain a sanitized receipt: request/receive times, monotonic
  duration, HTTP Date/Age, response digest and the observed equity scalar.
  Missing time evidence, cached responses, clock jumps, reads taking over
  10 seconds and receipts older than 30 seconds are rejected. Reads spanning
  midnight are ambiguous and must wait for the next genuine sample.
- The collector requires the OS to report `NTPSynchronized=yes`. It does not
  change the clock. FIRE checks the fresh receipt independently before GPT-6,
  after its decision, and again against the final pre-entry wallet read.
- The existing 2% daily / 5% weekly / 8% observed-peak limits are unchanged.
  A missing watermark is an integrity error, never a reason to reset the peak.
  Every risk write and read-only health check compares that watermark with all
  immutable equity history using exact decimal values. A lowered historical
  peak fails closed without repair, including after a new UTC opening or a
  process restart. A higher stored peak is never reduced by this validation.
- Runtime collection and FIRE open only an existing, nonempty risk ledger with
  its original watermark. A missing file, empty replacement or missing schema
  blocks risk approval; it is never recreated from the current wallet. Runtime
  connections use SQLite `mode=rw`, bind the file identity and reject deletion
  or replacement. Dashboard initialization defers risk-ledger access so its
  diagnostic endpoint remains available when that ledger is broken.
- `equity_read_receipts` is an **additive** immutable table. Existing evidence
  and opening checkpoints are preserved, without inventing transport receipts
  for legacy rows. Duplicate identical readings do not duplicate evidence;
  conflicting / out-of-order observations fail closed.
- **Pre-commissioning legacy schema diagnosis:** running the staged
  `python -m tradebot.equity_monitor --check --data-dir /original/VM/data`
  only reads the original SQLite ledger. On older VMs without
  `equity_read_receipts`, it reports
  `legacy_receipt_schema_uncommissioned`, the blocker
  `equity_receipt_schema_missing`, and a nonzero exit. This is a missing
  migration prerequisite, **not evidence that SQLite is corrupted**. The
  probe never creates that table, replaces a missed opening or launches
  the collector. Actual additive migration is reserved for the independently
  reviewed supervised deployment; the old opening rows still lack genuine
  transport receipts afterward.
- The read-only checkpoint health endpoint now checks the stored original
  transport receipt for the **first daily/weekly opening observation** and
  the **latest observation**. It validates the saved timestamp and equity
  value against the corresponding row at its original observation time,
  never using a current wallet reading to attest old history. Missing or
  malformed historical receipts produce `unverified_receipt` status and
  an `equity_read_receipt_invalid` alert, not a green opening/observation.
  This preserves older SQLite rows and diagnoses their missing provenance
  without backfilling or repairing them. An origin label alone is insufficient.
- **Runtime FIRE equity admission independently validates historical
  provenance inside the equity write transaction.** The first opening
  observations of the current UTC day/week and the latest prior observation
  must have stored transport receipts matching their original values and
  microsecond timestamps; a receiptless origin label cannot satisfy the risk
  gate even if a stale monitor response incorrectly reports healthy. The
  incoming genuine signed wallet read may establish the current opening only
  within its real first-five-minute window, not after a missed boundary.
  Invalid historical evidence fails *before* a new observation/watermark write.
  The independent read-only collector may still record diagnostic readings;
  only the trade-admission method enforces these stricter historical gates.
  The former `require_approved(equity, at=...)` unsigned shortcut now denies
  approval; legacy callers must provide a fresh transport receipt.
- Operational heartbeats, start history and a durable incident outbox live in
  a separate private `fire-monitoring.sqlite`. Active alerts are recorded on
  transition and reminded no more than once per five minutes. Alert state and
  deduplication survive process restart. Three starts in ten minutes flag a
  restart loop. The collector detects stale watchdog heartbeats (>90 seconds);
  dashboard diagnostics also flag stale collector heartbeats (>180 seconds).
- `/api/risk/checkpoints` remains read-only. It adds precise observation age,
  integrity status, next opening windows and monitoring health. Browser checks
  reject stale or contradictory healthy responses. Healthy evidence never
  enables a FIRE button.

## FIRE protective-order exclusivity

The FIRE controller and independent watchdog treat a signed broker response
containing *any* unexpected open order for the selected FIRE product as
**unverified bracket protection**. Even when the expected SL/TP pair has the
correct triggers, unique order IDs and full filled contract size, an
additional same-product order with a different trigger, missing or malformed
metadata, wrong side, cancelled state, or ordinary/non-bracket type blocks a
protected state and invokes the existing bounded emergency-closeout path.
The verifier only scopes this rule to the selected product; account-wide
pending orders require the separate account-exposure gate. Offline broker
mocks do not establish the exact response semantics for Delta DEMO: operator
verification is required before commissioning. No automated release or
permission is granted by the audit.

## Evidence limits and commissioning prerequisites

Delta's [wallet schema](https://docs.delta.exchange/#get-wallet-balances) does
not supply a documented internal net-equity valuation timestamp. Request HMAC
authentication and HTTPS establish the source; HTTP Date/Age are **transport
freshness evidence**, not a broker-signed valuation timestamp. The response
digest is a fingerprint, not a digital signature. A fresh transport response
cannot prove that the broker's internal valuation is current. Preserve this
limitation when reviewing commissioning evidence.

Actual DEMO response headers, clock synchronization, restart behavior and
real UTC openings must be verified on the VM. Unsupported or missing Date
headers fail closed; do not weaken the policy to obtain a passing result.
This is an upgrade of an existing account: missing original history requires
an approved restore/reconciliation procedure, not initial provisioning. There
is no runtime bootstrap command. Do not copy test fixtures, create an empty
ledger, or treat a current wallet read as a new historical peak.
Notifications currently persist in SQLite and the system journal. Off-machine
pager delivery, acknowledgement and an external VM-loss alarm are **not
commissioned**. A VM cannot alert about its own complete loss of connectivity.

## Staging and activation procedure (operator supervised)

1. Keep the current protective watchdog running. Verify current account-wide
   signed positions/orders and both FIRE disable overrides. Preserve the Gold
   commissioning lock; do not rename/delete it or issue a new FIRE request.
2. Run the existing `tradebot.fire_release_gate` using the existing protected
   DEMO environment and original data directory. A passing gate is evidence
   for review, not restart permission. No service restart during exposure.
3. Back up the existing databases using SQLite's online backup API under the
   approved release procedure. Do not copy only the main file while WAL writes
   are active. Retain receipts, checkpoints, peak watermark and commissioning
   lock. Verify integrity on backup copies. Keep credentials out of artifacts.
4. Stage the tested branch in an isolated worktree/venv and run the offline
   tests. Use copied evidence for migration/rollback checks; never seed the
   live data directory with test fixtures or use a later balance as an opening.
5. Check `timedatectl show --property=NTPSynchronized --value`. Review
   the new collector installer `ops/install_equity_monitor_service.sh`
   **without executing it in the staging worktree**. When independently
   approved code has actually been deployed to the existing active project
   directory, the installer requires that its physical project root exactly
   match **both** the running dashboard and watchdog systemd
   `WorkingDirectory` values, and that the original
   `data/fire-equity-risk.sqlite` file exists without symlinks. This rejects
   accidental use of `~/Tradebot2.0-review/data` as a new risk baseline.
   The installer **does not itself approve migration**, and stages a service
   unit only; it never starts or restarts services. Inspect the intended
   unit/targets, obtain independent approval, and preserve the original
   persistent database and service protection before staging it.
6. After the release/protection procedure is approved and flatness verified,
   enable/start `tradebot2-equity-monitor.service` under supervision, then
   upgrade/restart the watchdog and dashboard using that procedure. **Do not
   deploy the new watchdog alone**: checkpoint collection has moved to the
   dedicated service. Confirm automatic start on boot for both services.
7. Verify one-minute observation cadence and receipt persistence, plus fresh
   watchdog/collector heartbeats. Use the read-only diagnostic:

   ```bash
   .venv/bin/python -m tradebot.equity_monitor --check --data-dir data
   ```

   Exit 2 means prerequisites are incomplete; exit 0 still does not authorize
   a trade. After a missed weekly window, wait for a genuine Monday observation.
   For the historical 20 Nov 2026 missed-week case, the next weekly opportunity
   is **23 Nov 2026 00:00 UTC / 05:30 IST**, assuming the collector is operational.
8. Simulate connectivity loss, auth failure and restart using an isolated
   broker fixture first. On the flat VM, confirm supervised service recovery
   and monitor alerts. Test independent off-machine alert delivery before
   describing the system as operationally ready.

## Rollback

Keep FIRE disabled and the Gold lock unchanged. Obtain fresh account-wide
reconciliation before any service replacement. During exposure, maintain the
existing protector and use the separately approved protection procedure.

Roll back **code and service configuration only** to the reviewed baseline
`9ae06299bba588a247a7434eec6195f0c2a7d416`; do not roll back/delete databases,
receipts, watermark, or incident history. The old guard ignores the added
receipt table and can still read the original evidence table. Start/verify the
old watchdog's equity sampling before stopping the new collector, avoiding a
gap in observation coverage. Then verify fresh authenticated observations,
preserved opening values and SL/TP supervision. Keep the newer ledger intact
for investigation. This rollback restores the old timing-validation behavior
and automatic ledger-creation behavior; it is not approval for trading. If the
ledger is missing or its provenance is uncertain, stop equity ingestion and
keep FIRE disabled during rollback. Restore original evidence only under the
approved recovery procedure; never start the older collector against an absent
ledger. No rollback test or source merge authorizes a service restart.

## Offline validation

```bash
.venv/bin/python -m unittest discover -s tests -v
node --check src/tradebot/dashboard_static/app.js
bash -n ops/run_equity_monitor.sh ops/install_equity_monitor_service.sh
python tests/equity_checkpoint_browser.py
```

The tests simulate authenticated response headers, auth failures/timeouts,
stale/cached/ambiguous reads, UTC/IST and month/year/Monday boundaries, precise
freshness edges, corruption, missing watermark, duplicate/concurrent writes,
legacy schema migration, independent loss limits, reboot/reconnect recovery,
durable alert throttling and failed telemetry during watchdog protection.
Browser checks cover 375/768/1440 px, stale successes, contradictions and
connection failures. Tests use no exchange orders and no paid AI calls.

The [release review](RELEASE_REVIEW_PR3.md) records the reproduced ledger-reset
defect and the existing-only runtime correction, including recovery/race tests.
