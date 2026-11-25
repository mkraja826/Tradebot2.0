# Recover Trading

Clean demo-only replacement for Tradebot2.0. This branch is independent of the legacy strategy and runtime.

## Principles
- Delta India demo endpoint only. No production host configuration.
- No equity, loss, drawdown, confidence, session, cooldown, frequency, or strategy-based admission gates.
- Exchange requirements and request schema validation are not strategy restrictions.
- Strategy chooses whether, when and how to trade. The original BTCUSD/XAUTUSD Strategy V2 detectors are preserved and awaiting execution integration.
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

## Preserved BTC and Gold strategy research
The original ten Strategy V2 detectors, technical indicators, AI-routing contract, context builder, observation journal and four associated test modules are copied byte-for-byte from main commit `8d2bb5eea3777b14b31371433ca1deab8f07d2d2`. Their original package name is retained to preserve imports. See `tradebot/multi_strategy_signals.py`. The historical design document is kept for reference; it is not the new execution policy. The original shadow pipeline and order/risk workers are not restored. The existing routing thresholds are part of strategy research, not global execution admission gates. No detector calibration or trading profitability is claimed. These modules are not yet connected to the new Engine.
