# Recover Trading

Clean demo-only replacement for Tradebot2.0. This branch is independent of the legacy strategy and runtime.

## Principles
- Delta India demo endpoint only. No production host configuration.
- No equity, loss, drawdown, confidence, session, cooldown, frequency, or strategy-based admission gates.
- Exchange requirements and request schema validation are not strategy restrictions.
- Strategy chooses whether, when and how to trade; no strategy is selected in this foundation.
- An ambiguous submission is recorded, never automatically replayed.
- Logs record decisions and broker receipts for analysis, not risk gating.

## Run locally
Python 3.11+; no third-party dependencies.
```sh
python -m unittest discover -s tests -v
python -m recover_trading BTCUSD
```
The command reads a public demo ticker only. An eventual strategy will implement the Strategy protocol and pass it to Engine with a demo broker and journal. The foundation does not start a live or autonomous order process.

## Next
Define the markets, strategy/AI decision contract, market context, order types and position management. Then implement a strategy, broker integration tests, dashboard and deployment. No authenticated broker test or order has been performed for this increment.
