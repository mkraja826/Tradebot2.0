# Delta India Demo — staged VM upgrade safety procedure

**PR #1 / reconciliation release:** This is an operator procedure, NOT
an automatic deployment. No new entries, manual risk bypasses, demo orders,
or autonomous execution are authorized by this document.

## Current blocker (read-only ChatGPT plugin observation, 2026-11-20)

The connected VM continued to use old 100x broker leverage with BTCUSD and
XAUTUSD positions. At the last check, XAUTUSD had been emergency-flattened
by its separate FIRE watchdog, while BTCUSD still had a 30-contract short.
**Do not restart the dashboard or watchdog as an unattended upgrade while
any broker exposure/order remains.** Keep protective monitoring active.
Investigate why the gold watchdog reported missing/changed bracket protection;
a `flat_verified` receipt is NOT net-P&L verification.

## Watchdog installer hardening (22 November 2026)

**Important:** `ops/install_fire_watchdog_service.sh` previously ran
`sudo systemctl restart tradebot2-fire-watchdog.service` unconditionally
after writing the live unit file. That is unsafe while positions are exposed:
the trading bot's protective watcher must not be interrupted by installing
or testing a software update.

The installer now **stages only one private systemd unit candidate** under
`$HOME/.config/tradebot2/staged-units/` (directory 0700, candidate file
0600), without installing, enabling, reloading, restarting, or stopping any
running unit. It does not create/chmod the original `data/` directory,
alter any immutable FIRE ledger, or change trading permissions. It refuses
to stage when the existing BTC/Gold/monitoring SQLite ledgers and private
DEMO environment are absent or linked to another path.

Execute this staging step only after the reviewed code has been brought
onto the VM under a *separate* protected change procedure:

```bash
bash ops/install_fire_watchdog_service.sh
```

The result is **a candidate for review, not an installed service**.
A human operator must separately verify zero account-wide position/order
exposure, at least two signed broker snapshots, critical incident backups
(including SQLite WAL continuity), IP-whitelisted authenticated DEMO access,
and a protection-preserving change window before manually promoting the
candidate and restarting any service. Never use an automatic installer to
restart an active watchdog merely because source CI passed.

## Safe staged order of operations (on the VM, under supervision)

1. Inspect the **broker itself** for every open position and stop/target
   order, and verify `tradebot2-fire-watchdog` is active. Do not rely on
   cached dashboard screenshots as authoritative execution evidence.
2. Disable NEW FIRE entry permission via the operator's existing
   `ops/disable_fire_demo.sh` procedure, with the watchdog still running.
   This script restarts the dashboard, so coordinate it with active positions
   and verify the independent watchdog first. Do not stop the watchdog.
3. Preserve the private original `data/` files using the SQLite online
   backup tool in `docs/VM_WAL_BACKUP_PROTECTED_ROLLOUT.md` (never a plain
   `cp *.sqlite` while WAL is active). Backups can be taken safely before
   broker flatness as preservation-only evidence, **not** deployment
   permission. A stronger signed two-sweep broker-flatness check is required
   for any subsequent protected deployment. Do not copy private backups,
   credentials or logs to GitHub or chat.
4. Install the latest tested repository commit in a staging worktree/venv
   while leaving existing services untouched. Run offline tests.
5. Load the VM's *existing private* demo API environment in the isolated
   staging worktree and run:
   `python -m tradebot.fire_release_gate --data-dir data`
   This read-only two-sample gate waits **11 seconds** between signed checks
   to reduce stale-margin false-flat signals. It requires account-wide
   GET /v2/positions/margined, both filtered real-time GET /v2/positions
   (unfiltered returns HTTP 400 on Delta India Demo), an isolated-margin
   **signed current-account identity matched to its subaccount**
   (never deprecated `/v2/profile`), all account orders, and terminal
   SQLite FIRE receipts. The two observations must be separated by a
   verified **monotonic elapsed** interval of at least 11 seconds.
   Exit code 2 means **DO NOT RESTART**. Exit 0 is at most a
   read-only, point-in-time account-flat observation; the gate deliberately
   **does not authorize any service restart**. Independently verify new
   FIRE permission is disabled, the protective watchdog is active, current
   positions/orders are still zero, and the backups have been restored in
   a supervised offline test before any manual promotion. Do not run this check on a live
   service code path or print any API credentials.
6. A zero exit code means **only** that no currently open broker
   positions/orders or unresolved local FIRE requests were found. It does
   not authorize re-enabling FIRE and is not a full security/reconciliation
   or market-data quality certification.
7. After supervised deployment of the **read-only** reconciling dashboard
   with entry permission disabled, test a prior closed receipt:
   `python -m tradebot.fire_reconciliation --symbol BTCUSD --fire-id <EXISTING_CLOSED_FIRE_ID> --data-dir data`
   Use existing read-only Delta demo credentials. Exit 2 denotes unknown
   evidence, not zero P&L. Do not trigger a new FIRE to create test data.
8. Confirm the new read-only reconciliation report, broker positions and
   watchdog health. Check snapshot freshness and the verified vs provisional
   financial labels. Roll back service code safely if needed **without
   reverting the private receipt database** or disabling protection.
9. For the staged dynamic-leverage PR, do not enable FIRE unless each
   selected broker leverage is at most **20x**, and GPT-6 selection (1–20x),
   the independent 0.25% per-trade equity-risk limit, margin readback,
   isolated-margin liquidation clearance and the independent watchdog have
   been exchange-commissioned. Historical candle integrity, signed equity
   opening checkpoints, combined portfolio exposure and loss limits, and
   manual broker supervision remain required. The 20x cap is not a target.
   **Autonomy remains DISABLED.**

**The preflight does not change leverage or broker settings.** It cannot
verify protectiveness of stop orders, account-wide holdings omitted by the
broker, historical completeness, or funding-adjusted net P&L. Avoid claims
that a successful preflight guarantees profitable or safe execution.
