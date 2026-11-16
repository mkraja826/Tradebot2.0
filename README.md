# Tradebot 2.0 — AI-led BTC derivatives research (demo only)

A Bitcoin-only trading agent project for **Delta Exchange India demo**. Orders are **not running** yet. This repository has no production API host or production account support.

## Rules agreed

- Delta India **demo currency** only. Production endpoints are not configurable.
- **BTC futures and options** only; AI chooses strategies, strike/expiry, whether to hedge or wait, and whether to combine multiple trades.
- Trading only during **NYSE cash-market sessions**, with holidays, US DST and early closures derived from the XNYS exchange calendar.
- New entries stop 15 minutes before the exchange close. Positions and BTC pending orders must be cancelled/closed before session end. The closeout controller continues trying after a missed deadline and escalates if exposure is not verifiably flat.
- Journal all decisions and results. Learning and performance feedback will be built after a realistic simulator and fill/fee ledger.

## Implemented milestones

**M1 (foundation):** Delta India demo-only REST client, BTC contract validation, AI planning interface (requires a model/API key), local JSONL event journal, read-only CLI and offline CI tests.

**M2 (execution prototype):** NYSE calendar (holidays/early close), a BTC-scoped order inspector/canceller, a serial multi-leg market-order executor, unique client order IDs, closed-order fill checks, reduce-only closeout, repeated BTC position + pending-order verification and fake-exchange regression tests.

**Limits / not yet ready:** Not deployed or trading. No demo credentials stored or configured; no daemon, exchange-verified end-to-end tests, production-quality order/fee and P&L reconciliation, working market-data intelligence, option Greeks, learning pipeline or performance dashboard. Multi-leg fills are not atomic, and illiquid or disrupted products can prevent flattening. Closeout exceptions require immediate human intervention; a zero-overnight guarantee cannot be made against exchange outages.

## Install and inspect

Requires Python 3.11+.

```sh
python -m pip install -e .
python -m unittest discover -s tests -v
tradebot status
tradebot catalog   # Public demo market catalog; requires network access
```

## Credentials and order permissions

Use **only** API credentials generated at the Delta India demo site, and store in environment variables (not GitHub). Never paste secrets into chat or commit `.env`. The REST client is initialized with `allow_orders=False` by default and the CLI cannot place orders. An authenticated, supervised demo smoke test is required before enabling the order executor.

See `.env.example` for configuration placeholders. Official docs: https://docs.delta.exchange/

## Upcoming milestone

Build durable clock-driven runtime and decision journal, live demo BTC market snapshot/candles/order book/option chain, account-balance-aware sizing, simulated order/fee accounting, and verifiable end-to-end demo API tests. Add safety alert delivery for unclosed positions before scheduling unattended demo execution.
