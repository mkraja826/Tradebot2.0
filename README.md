# Tradebot 2.0 — Autonomous BTC derivatives research (Delta India demo only)

A Bitcoin-only AI futures and options bot project for the **Delta Exchange India testnet/demo account**. The repository has **no live-account support**. Trading is not running or deployed. The CLI defaults to read-only, with an **explicitly gated testnet-only order mode**. No keys are stored in this repository.

## User requirements

- Bitcoin futures and options only; the AI chooses its strategy, hedges, strike, expiry, number of legs, or WAIT without a strategy whitelist.
- US stock-market session (NYSE cash hours) on trading days, not a fixed IST clock. Use DST, holidays and early closes.
- Entries stop 15 minutes before NYSE close. All BTC positions and pending orders must be cancelled/flattened before the session ends. If this fails, the system must alert and keep trying; exchange outages can still prevent guaranteed flatness.
- Use demo capital, log decisions, evaluate realized results and improve decision quality only after testing.

## Implemented milestones

### M1 — Foundation

- Locked Delta India demo REST host: `https://cdn-ind.testnet.deltaex.org`.
- Python package, BTC contract validation, signed REST requests, research-only AI planner (now routed through Top Billing), JSONL decision journal, GitHub Actions unit tests.
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

### M4 — Autonomous session runner and confirmed-fill accounting (offline-tested)

- `tradebot run --mode observe`: long-running, **read-only** observer; only requests proposals during NYSE entry hours. If positions remain after close, it logs an exposure alert without touching the account.
- `tradebot run --mode demo --demo-execute`: **explicit testnet-only order mode**. It also requires `ENABLE_DEMO_ORDERS=true` and Delta India demo API credentials; the client host cannot be changed to production. **This mode is implemented but not yet exchange-verified or deployed. Do not run unattended until the integration tests and emergency notifications are complete.**
- During demo runs, new entries must pass a fresh quote check for every contract, a read-only balance/equity sanity check, a pending-order check and a real-time NYSE entry-window check. **These do not constitute a precomputed margin approval**: the exchange alone approves initial/maintenance margin, particularly for multi-leg options.
- AI chooses futures, options, spread legs, hedges and whether to WAIT. Failure on an order causes a BTC-only closeout attempt and a halt on new entries for that runner lifetime. Orders have unique client IDs.
- Outside the entry window, the testnet runner repeatedly attempts BTC order cancellation and closeout, then checks the remote positions and pending orders. SIGTERM / Ctrl+C initiates a graceful closeout attempt; an exchange outage or hard crash still needs a separate watchdog and alerts.
- A local file lock prevents two runner processes sharing the same journal path on one Linux host. **Not a distributed lock**.
- `tradebot reconcile`: fetches all paginated BTC fills in the requested lookback window and inserts them into an idempotent SQLite ledger with unique exchange fill IDs. `tradebot ledger`: reports confirmed fill counts and fees grouped by settlement currency.
- **The ledger does NOT yet calculate realized P&L, win rate, funding-adjusted returns or learning performance.** Net-equity observations are stored separately, never presented as realized strategy profits. The AI strategy-updating and independent trading outcome benchmarks remain upcoming milestones.

### M5 — Cost-conscious Top Billing AI integration (gateway authenticated, synthetic smoke-tested)

- **One AI model only:** `tb-deepseek-v4-1-flash` via `https://api.topbilling.in/v1/chat/completions`. No higher-priced model, no fallback requests or automatic second opinions.
- Credentials are read from `TB_API_KEY` **only at runtime**. A live API key must never be stored in source control, pasted into GitHub issues, written to test fixtures, or printed in logs.
- `tradebot ai-check` only fetches `/v1/models`; it does not request a billable completion. The token-generating commands are `preview` and `run`.
- The selected model does not support provider-enforced structured output according to Top Billing's conformance tests. The planner requests a plain JSON object as text and validates it locally; malformed responses stop the decision.
- Model calls cap `max_completion_tokens` to 2,048; AI request IDs and billed token counts (if returned) are journaled for cost evaluation. Configure **per-key spend caps** in Top Billing as a second control, since prompt tokens and retries can vary.
- `TB_API_KEY` is securely configured as a GitHub Actions repository secret and was verified through a read-only model-catalog request; no plaintext credential is committed. The secret is **not** automatically available on a VPS or JioPC.
- **Synthetic paid smoke test passed (2026-11-18):** DeepSeek V4.1 Flash returned a valid locally-validated JSON strategy, selected **WAIT** with 0 legs when given no live market evidence, using 357 prompt tokens and 151 completion tokens (508 total). Exactly **one** billed completion was submitted; no Delta API calls or orders were made.
- GitHub workflow `.github/workflows/smoke-topbilling.yml` is manually rerunnable, but each run spends provider credits. It also triggers when that workflow file itself changes. No paid AI completions are part of ordinary unit tests.

### M6 — Delta India demo API connectivity (public verified; account pending)

- The India demo-only API host is fixed to `https://cdn-ind.testnet.deltaex.org`; no production exchange endpoint is configurable.
- New `python -m tradebot.delta_probe` validates the real BTCUSD ticker, L2 order book timestamp, and 5-minute OHLC candles without placing or cancelling orders.
- `python -m tradebot.delta_probe --full-snapshot` verifies live BTC futures/options catalog, quotes, option Greeks where provided, order book, 5-minute candles and analysis features.
- **Verified on GitHub Actions 2026-11-18:** public demo check passed, returning 36 five-minute candles. Full market snapshot passed with **303 BTC derivatives, including 1 future and 302 options**. These are point-in-time demo testnet observations, not counts guaranteed for subsequent sessions.
- **Authenticated demo checks are not yet verified** because `DELTA_DEMO_API_KEY` and `DELTA_DEMO_API_SECRET` are not set as Actions repository secrets. The test uses only signed GET methods when configured, and produces sanitized status information (no account values or IDs).
- The workflow `.github/workflows/verify-delta-demo.yml` runs public checks on workflow changes and via manual `workflow_dispatch`; if both demo credentials exist, it additionally validates wallet, active-order and real-time BTC position response schemas. No Delta order mutations are performed by this workflow.

#### Configure Delta India **demo** credentials

1. Open the **demo account**, not the production Delta India account: https://testnet.delta.exchange/
2. Create a **testnet-only API key** for the bot with **read permission** first. Keep the key and secret private.
3. In GitHub repository `Settings → Secrets and variables → Actions`, create two repository secrets named `DELTA_DEMO_API_KEY` and `DELTA_DEMO_API_SECRET`.
4. From the GitHub Actions tab, manually run **Delta India DEMO read-only integration**. It verifies read-only wallet, order and position shapes without placing orders.
5. Only after verifying the authenticated response schema, order fills, and independent closeout alerting should trading permissions ever be considered. The demo order feature remains disabled unless separately authorized.

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

Generate **demo-only** API credentials from the Delta Exchange India testnet, put them in a local environment or secret manager (never in Git). The AI preview requires a Top Billing key with chat permissions; we currently allow only one cost-effective DeepSeek model.

```bash
export DELTA_DEMO_API_KEY="your-demo-only-key"
export DELTA_DEMO_API_SECRET="your-demo-only-secret"
tradebot balances
tradebot snapshot --include-balances --output data/btc-with-demo-funds.json

# Set the NEW Top Billing key in your local secret environment.
# Never copy the key into this README or the repository.
export TB_API_KEY="your-rotated-topbilling-key"
export TB_MODEL=tb-deepseek-v4-1-flash
tradebot ai-check  # GET /v1/models, no paid inference
tradebot preview --max-options 64 --output data/ai-proposal.json
```

### Runner and confirmed-fill reconciliation

```bash
# Requires TB_API_KEY and Delta demo read credentials
tradebot run --mode observe --poll-seconds 15 --ai-interval-seconds 300

# Optional demo-only order mode, AFTER supervised exchange integration testing:
# export ENABLE_DEMO_ORDERS=true
# tradebot run --mode demo --demo-execute

# Read-only historical accounting; never submits orders
tradebot reconcile --lookback-hours 24
tradebot ledger
```

**Start with observe mode.** The dry-run planner incurs Top Billing prepaid API charges. All order execution depends on broker fills and may be subject to rejected margin requests, option-leg slippage, liquidation and outages. An alert printed to stderr is not a reliable off-machine emergency notification. Supervised smoke tests, an independent watchdog, verified exchange positions, real-time expiry/fee handling and remote alert delivery are required before leaving demo execution unattended.

Do not commit `.env`, preview artifacts, balance exports, JSONL logs or SQLite ledgers. The `data/` directory is ignored by Git.

## Status and next work

**M1–M6 market-data and AI integration implemented with passing GitHub tests; Delta public demo API and full options pipeline verified in GitHub Actions.** Top Billing gateway access passed one paid AI smoke test. No hosting deployment or continuous trading has begun; **Delta demo account authentication, order execution and closeout remain unverified**. The Top Billing key exists only in the GitHub Actions secret store, not in repository source; credentials must be injected separately into any VPS or JioPC runtime.

Before unattended testnet trading, verify all endpoint payloads and exchange order/fill states with a supervised demo-only API smoke test; add independent heartbeat/paging/closeout monitoring, accurate realized P&L (including fees, funding and position changes), strategy evaluation on held-out periods, a supervised model-update process and resilient reconciliation after network timeouts. Do not describe the bot as profitable or self-learning until it has verified outcomes and a model-improvement pipeline.

Read the official exchange specs at https://docs.delta.exchange/. Never enter live-trading secrets in this project.
