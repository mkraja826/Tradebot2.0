# Tradebot 2.0 — Autonomous BTC derivatives research (Delta India demo only)

A Bitcoin-only AI futures and options bot project for the **Delta Exchange India testnet/demo account**. The repository has **no live-account support**. Trading is not running or deployed. All executable CLI commands are **read-only**, and no keys are stored in this repository.

## User requirements

- Bitcoin futures and options only; the AI chooses its strategy, hedges, strike, expiry, number of legs, or WAIT without a strategy whitelist.
- US stock-market session (NYSE cash hours) on trading days, not a fixed IST clock. Use DST, holidays and early closes.
- Entries stop 15 minutes before NYSE close. All BTC positions and pending orders must be cancelled/flattened before the session ends. If this fails, the system must alert and keep trying; exchange outages can still prevent guaranteed flatness.
- Use demo capital, log decisions, evaluate realized results and improve decision quality only after testing.

## Implemented milestones

### M1 — Foundation

- Locked Delta India demo REST host: `https://cdn-ind.testnet.deltaex.org`.
- Python package, BTC contract validation, signed REST requests, research-only OpenAI planner, JSONL decision journal, GitHub Actions unit tests.
- Non-GET requests blocked unless the exchange client is explicitly initialized with trading permission. The CLI *never* enables that permission.

### M2 — Execution prototype

- Holiday-, daylight-saving- and early-close-aware NYSE clock.
- An isolated BTC-only multi-leg market-order executor, client IDs, per-leg fill verification, failed-entry unwind attempt, repeated closeout and final position/order checks.
- Fake-exchange tests for failed legs, stuck positions, time windows and partial fills.
- **Not battle-tested on Delta demo**: complex multi-leg fills are not atomic; error recovery, rate limiting, broker positions and cancel/close API behavior require authenticated integration tests.

### M3 — BTC market intelligence and read-only AI previews

- Public BTC product catalog and futures/option tickers; quote spread and age; option chain with IV and Greeks where supplied.
- BTCUSD 5-minute candle history and 20-level order book; reject stale core quotes, crossed/locked bids and asks, missing candles, irregular 5-minute intervals and invalid OHLCV.
- 1-hour BTC return and realized-volatility features.
- Optional **signed read-only** Delta demo wallet observations. Balances remain labeled by asset; they are not implicitly added together.
- AI preview context selects a diverse sample of recent, usable option quotes across calls, puts and expiries (default 128). This is a context-length limit, not a strategy whitelist.
- The `preview` CLI produces an AI recommendation and saves it to the journal, but **does not submit orders or verify strategy margin**.
- All these components have offline deterministic tests; public demo and authenticated demo endpoints have *not* been verified live.

## Setup

Python 3.11+, install with:

```bash
python -m pip install -e .
python -m unittest discover -s tests -v
```

### Market data, no keys required

```bash
tradebot status
tradebot catalog
tradebot snapshot --output data/btc-market.json
```

### Demo balances and optional AI preview

Generate **demo-only** API credentials from the Delta Exchange India testnet, put them in a local environment or secret manager (never in Git). The AI preview also needs an OpenAI API key and a chat model that supports JSON responses.

```bash
export DELTA_DEMO_API_KEY="your-demo-only-key"
export DELTA_DEMO_API_SECRET="your-demo-only-secret"
tradebot balances
tradebot snapshot --include-balances --output data/btc-with-demo-funds.json

export OPENAI_API_KEY="your-openai-key"
export OPENAI_MODEL="your-json-capable-model"
tradebot preview --max-options 128 --output data/ai-proposal.json
```

The `preview` command calls an OpenAI model, potentially incurring API charges; it requires demo wallet access for balance awareness. **No actual trading is performed by these commands.** Do not commit `.env`, preview artifacts, balance exports or journal data. The `data/` directory is ignored by Git.

## Status and next work

**M1 and M2:** Offline-tested framework. **M3:** Market snapshot and AI proposal code, offline tests. **Not running, not deployed, not connected to a funded demo account.**

Before allowing unattended simulated orders, implement a reliable clock-driven daemon, market-data sampling/history, hard fresh-quote and broker-margin validation immediately before entry, exchange-specific order/position reconciliation, fees/realized P&L accounting, closeout alerts and verified demo API integration tests. Add evaluation and controlled model retraining using realistic trading outcomes.

Read the official exchange specs at https://docs.delta.exchange/. Never enter live-trading secrets in this project.
