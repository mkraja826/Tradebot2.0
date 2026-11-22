# BTCUSD unattended DEMO readiness and operating limits

**Scope:** Delta India DEMO, BTCUSD only. Not a live-money service.
The separate dashboard BTC FIRE and XAUTUSD FIRE routes remain disabled.

## Current software configuration

`tradebot.btc_autonomous_demo` is the bounded autonomous worker. It checks
the existing *read-only* BTC commissioning preflight before each attempt:
fresh original 24-hour candle quality, live account-wide flatness, signed
wallet equity, watchdog/collector status, manually declared Main/Isolated
mode, and a disabled normal FIRE dashboard.

The local five-minute screen and Coinbase spot sanity check run before any
paid GPT-6 decision. New RSI/ADX/RVOL/MACD/Bollinger features are advisory.

- One contract maximum, enforced in both model scope and execution code.
- At most two attempts per UTC day, at least four hours apart; reservations
  persist **before** contacting the AI or broker and are not refunded.
- The broker-read wallet equity has an additional persistent UTC-day 0.5%
  decline threshold. The 15-minute authenticated session guard remains.
- Broker-side SL/TP, liquidation clearance, order reconciliation and
  emergency closeout remain mandatory, with an independent active watchdog.
- If the model fails, execution becomes ambiguous, a stop is unverified, or
  historical FIRE receipts are unresolved, subsequent attempts are halted.
- A private owner-owned `0600` arming file must contain the exact
  DEMO-only mode string; production API endpoints are unsupported.
- The service can be installed **disarmed** for observation without making
  a broker mutation or paid model request.

## Confirmed unresolved commissioning questions

1. A BTC demo FIRE attempt on 2026-11-22 ended
   `rejected_no_order / model_decision_failed`; no order was submitted.
   Its stored full-model decision error is not sufficiently diagnostic.
   A small GPT-6 JSON ping and the model catalogue were reachable, which
   do not prove complete strategy-schema reliability.
2. The newest historical FIRE receipt currently has a failed model decision.
   The autonomous receipt-recovery gate must remain closed until the
   underlying reason is understood and a reviewed resolution is recorded.
   Deleting the receipt to clear the gate is not an acceptable fix.
3. Reliable, repeatable BTC demo SL/TP, liquidation and restart recovery
   must be proven during controlled commissioning, with an actual protected
   broker-order lifecycle; unit tests alone cannot prove this.
4. The weekly equity checkpoint is missed, with next valid Monday opening
   at 2026-11-23 00:00–00:05 UTC (05:30–05:35 IST). The **supervised**
   session guard permits a genuine short-session alternative; normal FIRE
   still requires its original weekly evidence.
5. The historical commission/wallet reference remains unattributed and
   historical net P&L cannot be declared verified. Signed equity receipts
   provide a separate risk baseline, not an accounting reconciliation.
6. The new technical signals have not yet demonstrated out-of-sample edge.
   Backtest and walk-forward outcomes must be evaluated before scaling.

No trading authorization can be inferred from a manual setting, a passed
backtest, a healthy model catalogue or clean unit tests. Monitoring and
commissioning must always differentiate DEMO from real-money operations.
