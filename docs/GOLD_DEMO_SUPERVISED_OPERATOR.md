# Supervised Gold Delta DEMO commissioning: operator-controlled single shot

The `tradebot.fire_supervised_commission` module defaults to **read-only**.
It first runs the two-sample account-wide broker gate and verifies that
BTC and Gold dashboard FIRE endpoints are disabled and both services healthy.

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

During the supervised trial, the operator must independently confirm
the exact broker entry fill ID, two active protective child orders, selected
leverage, isolated account margin mode and real liquidation price at least
1% of entry beyond SL. Missing/unsafe evidence invokes fail-closed
emergency closeout, and ambiguous closeout requires human attention.
Do not assume a terminal local FIRE receipt proves a broker fill cause.

Live trading and autonomous FIRE remain prohibited at this stage.
