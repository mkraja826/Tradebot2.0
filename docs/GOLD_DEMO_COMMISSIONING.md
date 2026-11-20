# Gold demo commissioning: controlled readiness and evidence

**Status:** read-only readiness gate implemented; no commissioning order authorized.

Run from the **checked-out safety candidate** on the Delta India demo VM:

```bash
cd ~/Tradebot2-safety-20x
set -a
source "$HOME/.config/tradebot2/keys.env"
set +a
PYTHONPATH="$PWD/src" "$HOME/Tradebot2.0/.venv/bin/python" \
  -m tradebot.fire_commission_preflight --data-dir "$HOME/Tradebot2.0/data"
```

The command performs a two-pass account-wide signed broker release gate,
checks both dashboard FIRE endpoints explicitly disabled, requires dashboard
and independent watchdog processes active, and verifies Gold product/ticker
tick size and signed leverage in 1..20. It uses `allow_orders=False` and makes
no database mutations, AI calls, or broker write requests.

A passing `ready_for_supervised_operator_review` is **not** a trade permit.
`trade_authorized` and `broker_liquidation_price_verified` remain `false`.
Liquidation evidence is impossible to verify while Gold is flat.

## Required before any active demo position

1. Implement and test a dedicated operator-authorized, single-use commissioning
   transaction integrated with both the durable FIRE receipt and the watchdog.
   A manual Delta UI trade is **not** covered by FIRE's receipt-linked watchdog.
2. Require explicit manual approval for **one** demo XAUTUSD contract, never
   a production API, and require signed flat account evidence immediately
   before the broker's order mutation.
3. Validate exact tick-aligned attached mark-price SL/TP, intended leverage,
   equity risk, net reward/risk, max drawdown and whole-account reservation.
   The current 20x leverage is only a ceiling; do not force an entry.
4. Ensure durable intent is committed before the **single** non-idempotent
   parent POST; no blind POST retry after an ambiguous response.
5. Confirm signed fill, both distinct bracket children, and live position
   size/entry. Then poll signed margin-aware position data for a **bounded**
   interval (Delta documents that the endpoint can lag fills by up to 10 s).
   Require isolated mode and liquidation at least 1% of entry beyond stop.
6. On missing/mismatched/unsafe protection, use a tracked reduce-only exit,
   preserving existing bracket children until **signed flatness** is verified.
   If closeout is ambiguous, halt and require operator reconciliation.
7. Collect broker order/fill IDs, risk and liquidation evidence, timestamps,
   watchdog reactions and subsequent two-pass signed flatness evidence.
   Review outcome before approving any second trial or enabling FIRE.

**Do not enable autonomous trading or remove the FIRE disable systemd
override during this readiness stage.** The existing dashboard and watchdog
must remain operational and must not be restarted during exposure.
