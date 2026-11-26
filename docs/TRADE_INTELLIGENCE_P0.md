# P0: complete trade intelligence (read-only)
Run from a separately staged checkout with access to the existing demo journals:
```sh
python3 -m recover_trading.trade_intelligence --symbol BTCUSD
python3 -m recover_trading.trade_intelligence --symbol XAUTUSD
```
No restart, AI API request, order submission or trading-policy change. The audit uses the existing reconciled performance, decision review, excursion and learning records. It adds original model/reason, estimated fill notional and margin, planned stop/target monetary exposure, cost reconciliation, and bounded management candidates. The 1000-bps excursion flag is a descriptive data-review flag only; it is not a trading threshold. Management time-and-direction matches cannot prove the position episode identity; proposal-to-attempt identity is checked separately. Existing journals are not altered. The initial reporting window is the last 50 account episodes; the coverage count discloses truncation. Actual margin, execution-level AI charges, exact management attribution and causal exit reasoning require further evidence. Keep this as an offline report until validated with actual VM journal data. Do not activate changes to entry, sizing or position management in P0.
