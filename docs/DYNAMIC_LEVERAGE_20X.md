# GPT-6 dynamic demo leverage: 1x–20x (staged release)

**Status: proposed on feature branch only. Not approved for VM deployment or autonomous execution.**

GPT-6 proposes an integer `leverage` from 1 through 20 on LONG/SHORT decisions.
WAIT has `leverage: null`. The maximum 20x is a hard ceiling, not a target.
The independent risk engine retains a 0.25% equity-at-risk allowance, fee and
slippage reserve, and minimum 1.5x net reward-to-risk. The initial supervised
pilot **continues to permit at most one contract** per manual FIRE.

## Broker integration

- A legacy broker setting above 20x fails before any billable GPT-6 call.
  The operator must reduce such settings while flat. No automatic 100x
  downshift is performed.
- When GPT-6 selects a different leverage, the code checks that the selected
  market is flat with zero open orders, sends exactly one signed demo-only
  POST to `/v2/products/{product_id}/orders/leverage` and requires a
  subsequent signed GET to match. No mutation retry on ambiguous outcomes.
- Risk and margin are checked against the *selected* leverage before the
  mutation, then recalculated with signed broker leverage and equity after it.
- After an entry fill, both SL and TP must be confirmed. The **signed**
  `/v2/positions/margined` response must also confirm isolated margin,
  matching signed position quantity and a liquidation price with at least
  1% of entry-price buffer *beyond* the SL. Missing/stale margin evidence
  causes fail-closed emergency closeout; it is not proof of a safe entry.
- The watchdog rechecks broker liquidation evidence, never calls GPT-6 or
  changes leverage, and attempts emergency closeout on failed protection.

A theoretical 3.5%-of-price cushion is also reserved before an entry; this
is **not** a broker liquidation estimate. Broker-dependent maintenance
margin and slippage can still cause liquidation, even with verified stops.

## Release gates

1. Confirm the broker directly reports both BTCUSD and XAUTUSD flat and
   their entry/stop orders absent. Never restart watchdog/dashboard during
   existing exposure.
2. Check latest existing VM code and back up private SQLite receipts before
   staging any update; do not migrate or discard unknown order intents.
3. Run all offline tests, then perform explicit manual demo commissioning of
   leverage mutation, readback, position liquidation evidence, SL/TP and
   watchdog behavior for both contracts.
4. Verify broker margin mode is isolated and does not silently switch to
   portfolio/cross. A missing field is not automatically assumed safe.
5. Keep real-money orders, automatic FIRE and autonomous trading disabled.

References: https://docs.delta.exchange/ (Change/Get Order Leverage,
Get position vs. Get margined positions).
