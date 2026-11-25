# Signal-driven AI proposal engine

Run `python -m recover_trading.decision_runner` for a no-cost preview, or `--request-ai` to enable billable proposal requests. Configure `TB_API_KEY`, `RECOVER_BTC_MODEL` and `RECOVER_GOLD_MODEL` in the runtime environment. The fixed Top Billing chat completion endpoint follows the prior repo integration; model identifiers are operator configurable and not yet verified. No credentials are committed.

One new valid strategy signal suffices to request a proposal; simultaneous signals are grouped by market per scan. Signal identity is durable across restarts, independent of profit, loss, confidence or equity. Unknown or malformed provider responses are recorded; an identical potentially billed request is not automatically replayed. The model receives public technical context and decides trade or no_trade. No fixed allocation, reward/risk formula or trading cooldown is imposed.

Output includes side, contract quantity, leverage, entry reference, SL, TP and rationale. This is a proposal only: product resolution, account context, broker execution, order type and SL/TP lifecycle remain to be integrated. No paid smoke test or demo order is part of this change.
