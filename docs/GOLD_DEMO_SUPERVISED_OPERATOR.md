# Supervised Gold Delta DEMO commissioning: operator-controlled single shot

The `tradebot.fire_supervised_commission` module defaults to **read-only**.
It first runs the two-sample account-wide broker gate and verifies that
BTC and Gold dashboard FIRE endpoints are disabled and both services healthy.
It also requires current collector/watchdog telemetry, authentic daily/weekly
equity checkpoints and a fresh signed-wallet loss assessment before consuming
the one-shot marker. A missing opening cannot be reconstructed by this command.

```bash
# Read-only readiness; never submits an order.
PYTHONPATH="$PWD/src" "$HOME/Tradebot2.0/.venv/bin/python" \
  -m tradebot.fire_supervised_commission --data-dir "$HOME/Tradebot2.0/data"
```

**NO execution is authorized by running the read-only command.**

A separate `--execute-one-gold-demo` option requires an interactive operator
terminal and the exact typed confirmation `EXECUTE ONE GOLD DEMO FIRE`.
Do **not** use that option until operator explicitly approves a supervised
Delta India DEMO XAUTUSD attempt and an active human responder is present.

The one-shot entry point uses the **existing** GPT-6 FIRE controller,
the `fire-xaut.sqlite` durable receipts, account-wide flatness checks,
the one-contract backend pilot limit, and the independent watchdog. GPT-6
may choose `WAIT` and no order. It never enables dashboard FIRE.

An exclusive `gold-demo-commission-attempt.lock` in the active data
directory is created BEFORE invoking the FIRE controller. Its existence
blocks all further commissioning invocations, even after a GPT-6 WAIT,
timeout, terminal disconnect or execution failure. Never remove it without
manual broker reconciliation and signed evidence. It is not an order ID.
The read-only summary reports a consumed marker as a blocker, including a
broken symlink. Marker creation fsyncs the file and its directory before the
controller starts; a sync failure preserves the marker and prevents the call.

For the existing rejected Gold attempt, first use the separate
[signed recovery-planning review](GOLD_RECOVERY_REVIEW.md). It never clears this
lock or authorizes a new attempt. An accepted planning review still requires a
separately approved recovery procedure and explicit execution authorization.

During the supervised trial, the operator must independently confirm
the exact broker entry fill ID, two active protective child orders, selected
leverage, isolated account margin mode and real liquidation price at least
1% of entry beyond SL. Missing/unsafe evidence invokes fail-closed
emergency closeout, and ambiguous closeout requires human attention.
Do not assume a terminal local FIRE receipt proves a broker fill cause.

Live trading and autonomous FIRE remain prohibited at this stage.
