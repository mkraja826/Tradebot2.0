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

## Safe staged order of operations (on the VM, under supervision)

1. Inspect the **broker itself** for every open position and stop/target
   order, and verify `tradebot2-fire-watchdog` is active. Do not rely on
   cached dashboard screenshots as authoritative execution evidence.
2. Disable NEW FIRE entry permission via the operator's existing
   `ops/disable_fire_demo.sh` procedure, with the watchdog still running.
   This script restarts the dashboard, so coordinate it with active positions
   and verify the independent watchdog first. Do not stop the watchdog.
3. **After broker-confirmed flatness**, back up the private `data/` SQLite
   files (including WAL/SHM consistency) and the existing VM code/config.
   Do not copy credentials to GitHub, logs or chat.
4. Install the latest tested repository commit in a staging worktree/venv
   while leaving existing services untouched. Run offline tests.
5. Load the VM's *existing private* demo API environment and run:
   `python -m tradebot.demo_upgrade_preflight --data-dir data`
   The preflight uses account-wide GET /v2/positions/margined plus
   per-product filtered GET /v2/positions; unfiltered GET /v2/positions
   returns HTTP 400 on Delta India Demo. Margined positions may lag up to
   10 seconds; repeat the GET-only preflight after at least 10 seconds and
   keep new entries disabled throughout the deployment window.
   The preflight only makes signed/demo GET requests and opens existing
   receipt databases in read-only mode. Exit code 2 means **DO NOT RESTART**.
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
