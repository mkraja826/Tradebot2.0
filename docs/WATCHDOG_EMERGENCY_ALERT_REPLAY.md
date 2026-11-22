# Durable watchdog emergency-closeout alert (DEMO only)

## Release blocker
Previously, a protective watchdog that detected a missing/incorrect BTC or
Gold stop-loss or take-profit could make a successful *reduce-only emergency
closeout*, update its FIRE receipt to `flat_verified`, and immediately begin
advertising a normal `healthy` heartbeat. The equity collector polls about
once per minute while the watchdog normally cycles every 15 seconds. As a
result the off-host and Telegram notifier might never receive a critical
incident, even though the protective orders had failed.

## Fix
- Adds the allowlisted, fixed critical event code
  `watchdog_emergency_flat_verified` to the existing monitoring outbox.
- If the watchdog persisted a bracket/protection failure and later finds
  the account flat **after a crash before writing its final exit receipt**,
  the resulting event uses `watchdog_protection_failure_flat_verified`.
  This is a confirmed protection failure plus subsequently observed flatness,
  **not proof** that the watchdog's reduce-only order actually caused the exit.
  It is still a durable critical alert rather than a silently normal exit.
- Both fixed event categories are tightly allowlisted. No broker economics,
  individual order IDs or the original private FIRE press enter notifications.
- The **verified broker-flat FIRE receipt** remains the primary evidence.
  Its existing durable `reason_code` must match
  `watchdog_emergency_flat_verified`; other voluntary or normal flat exits
  are not emergency events.
- After both markets' protective checks, the watchdog reads its two local
  FIRE receipt databases with SQLite **`mode=ro`**. It identifies all
  bounded historical emergency-closeout receipts, including those obscured
  by a newer terminal/request receipt.
- Each distinct FIRE press causes **one** atomic critical outbox insertion,
  keyed by a private press ID in a new additive monitoring-only table.
  Replayed reads, concurrent watcher processes or restarts do not duplicate
  the event.
- If a process dies after broker-confirmed closeout and FIRE receipt update
  but before recording the alert, the next watchdog cycle recovers the
  unrecorded incident. Missing/corrupt receipt or monitor evidence fails to
  report a verified healthy cycle; **protection checks keep running**.
- `MonitorStore.publish()` in the equity collector does not delete or
  resolve these one-off historical incidents. Off-host HTTPS and Telegram
  notification already consume `monitor_events` with independent
  at-least-once delivery cursors and accept this fixed alert code.
- No account amounts, order IDs, FIRE press IDs, authenticated headers,
  balances, bearer tokens, full receipts or raw broker response bodies are
  published in the event or terminal log.

**Important scope:** A durable local outbox event is not proof an external
notification was actually received. Test the operator-configured webhook,
Telegram delivery and independent VM-loss check, then review a real or
controlled mock incident. Never deliberately remove real protective orders to
test the emergency closeout.

## Version and deployment

The runtime marker changes to `watchdog-telemetry-v3-20261122` in both the
daemon and its execution shell, preventing an old running Python import from
pretending to be the new version.

The source merge **does not deploy or restart** an already running VM
watchdog. Before a supervised rollout:
1. Confirm the account is broker-flat through both signed independent
   account-wide sweeps; any exposed position must remain under its current
   protective watcher with no interruption.
2. Preserve consistent backups of the existing monitoring and FIRE SQLite
   databases with WAL continuity; inspect and approve schema addition.
3. Stage and install the reviewed source, verify systemd process identity
   and startup marker in the running watchdog journal.
4. Confirm the event outbox, independent heartbeat freshness and real off-host
   delivery from a safe offline synthetic fixture, not a naked exchange
   position. Verify alert retries without re-opening an actual trade.
5. Leave FIRE disabled pending complete market, M09 financial, equity and
   final independent release signoff.

No new entry orders, leverage edits, strategy model calls, capital transfers,
manual account order cancellations, wallet writes or loss-limit changes are
introduced by this PR.
