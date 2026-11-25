# Autonomous demo service

The service uses independent BTCUSD and XAUTUSD workers and per-market SQLite files.
The default command is public-data preview; no credentials, paid AI or exchange orders.

    python -m recover_trading.service --once
    python -m recover_trading.service --interval 60

To explicitly enable the demo execution path, configure these variables in the
runtime secret environment (never commit them):

- TB_API_KEY
- RECOVER_BTC_MODEL, RECOVER_GOLD_MODEL
- RECOVER_BTC_DEMO_KEY, RECOVER_BTC_DEMO_SECRET
- RECOVER_GOLD_DEMO_KEY, RECOVER_GOLD_DEMO_SECRET

After authenticated testnet integration and position-management verification, the
execution command is:

    python -m recover_trading.service --execute-demo --interval 60

Use --symbol BTCUSD or --symbol XAUTUSD for a single market. Distinct API keys are
required for two-market mode; different keys alone do not prove distinct exchange
accounts. Operator must configure the intended demo accounts. Only the fixed India
testnet endpoint is used. Default scan target is 60 seconds, not a trade cooldown.
A long scan can take longer than the target interval. Per-market scan exceptions
are logged and subsequent cycles continue. SIGINT/SIGTERM stop after in-flight calls.
AI is called only for fresh signals, with the existing durable deduplication.
Order uncertainty is reconciled by client ID, never blindly resubmitted.
A crash between proposal persistence and order reservation can leave an unexecuted
proposal; a failed AI request or failed preparation is not automatically replayed.
No equity or loss admission rule is added. The service does not yet track complete
fill/exit lifecycles, verify bracket activation, reconcile actual margin, or provide
external process supervision. Not deployed or authenticated-tested in this increment.
