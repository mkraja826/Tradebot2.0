# BTCUSD unattended Delta India DEMO — read-only diagnostics

This mode is intentionally independent from the general dashboard FIRE endpoint. It never supports live/production credentials or endpoints.

## Check blockers without AI spend or broker orders

```bash
cd ~/Tradebot2.0
set -a; source ~/.config/tradebot2/keys.env; set +a
PYTHONPATH=src .venv/bin/python -m tradebot.btc_autonomous_readiness --data-dir data
```

The report performs fresh **read-only** authenticated Delta DEMO preflight checks. It does not mutate broker settings, create entries, add audit receipts, call GPT-6, or arm the worker.

The existing `tradebot2-btc-autonomous-demo.service` is **not authorized** by this report. It retains its separate private owner arm file, daily trade budget, durable attempt journal, equity loss ceiling, signed account-wide flatness, model validation, exchange leverage/liquidation rechecks and attached broker protection.

### Known blockers (23 November 2026)

- `owner_autonomous_arm_missing`: owner-operated mode-0600 arm file does not exist. This is an intentional safety gate, not a software failure.
- `previous_fire_requires_operator_review`: latest historical BTC FIRE was `rejected_no_order` with `model_decision_failed`. Its no-order record must be reviewed before any independent unattended session. **Do not rewrite or delete that receipt.**
- One-shot supervised commission was already consumed. That irreversible one-shot marker is **not an unattended worker requirement** and must not be removed.
- GPT-6 model appears in the provider's catalogue and the configured credential is present in active services. This does not prove an actual paid model completion succeeds.
- A previous generic model failure cannot be assigned a precise cause retroactively. New model failures carry a bounded internal request/completion/validation stage to improve diagnostics without storing upstream messages.
- GPT-6 via Top Billing currently does not advertise structured output; do not set `response_format`. The new explicit `max_completion_tokens` cap limits credit consumption without assuming model returns valid JSON.

A report of `eligible_read_only_no_order` **never** authorizes a trade. The autonomous process itself checks fresh evidence again at execution time.

## Operator recovery

1. Diagnose model route (read-only catalogue), input format and bounded errors.
2. Inspect the exact last FIRE receipt: model failure, `orders_submitted=false`, no broker intent, current signed account-wide exposure flatness, and independent watchdog health.
3. Require explicit owner approval for any release from a model-error stop or unattended arming. Do not bypass manual review by directly editing a trade record.
4. Leave all order execution flags off until an authenticated DEMO-only end-to-end readiness review passes.

## Audited recovery of the exact historical no-order model failure

Read evidence without modifying anything:

```bash
cd ~/Tradebot2.0
PYTHONPATH=src .venv/bin/python -m tradebot.btc_auto_review --data-dir data
```

After reviewing the exact model-failure receipt, proving that its
`orders_submitted` value is false and there is **no durable `fire_entries`
intent**, and confirming fresh authenticated signed broker exposure is flat
with the independent protection services working, an authorized operator can
acknowledge that one record:

```bash
set -a; source ~/.config/tradebot2/keys.env; set +a
PYTHONPATH=src .venv/bin/python -m tradebot.btc_auto_review --data-dir data \
  --acknowledge \
  --approval 'REVIEW BTC DEMO MODEL FAILURE WITH NO ORDER'
```

The acknowledgement creates a private mode-0600 `data/btc-auto-reviewed-no-order.json`
marker containing the exact receipt identity and SHA-256 digest, without
rewriting or removing the original FIRE record. It rejects changed receipts,
any durable broker intent, unverified signed DEMO flatness, unknown failures
or mismatched marker permissions.

**This is a review of a proven historical no-order event, not a trade
authorization.** It does not create the separate autonomous arm file, touch
broker settings, restart services, or call GPT. A new failure is not
automatically reviewed. The worker continues to impose its normal halt latch,
daily and per-trade risk limits, and broker protection checks at execution time.

## 30-minute DEMO exploration and confidence-tier sizing

The opt-in autonomous DEMO worker polls every five minutes, but may spend GPT-6
tokens or reserve another FIRE attempt only when at least **30 minutes**
have elapsed since the preceding durable attempted decision. The UTC-day cap
is **48 model attempts**, not a requirement to open 48 positions. It may
run fewer: model WAIT, stale broker data, active orders/positions, unresolved
reconciliation, daily loss limits or a revoked owner arm all block new orders.

When signed broker evidence proves a position or pending order is already
open, the worker emits `skipped_active_trade` **without reserving an
attempt**, and checks again later. An API timeout or incomplete broker
evidence is **not** classified as a known open position and never grants
permission to trade. The independent FIRE watchdog must reconcile a
protected position into a genuinely flat broker status before re-entry.

Only this BTCUSD **Delta India DEMO** worker can use three sizes:

| Experimental tier | Contracts | Independent maximum estimated loss |
|---|---:|---:|
| Small exploratory | 1 | 0.25% of verified equity |
| Medium | 2 | 0.35% of verified equity |
| Strong | 3 | 0.50% of verified equity |

The independent capacity screen requires aligned 15-minute and 1-hour EMA
direction and ADX/DI trend before approving medium; strong also requires
ADX at least 25 and at least three confirming MACD/RSI/VWAP/RVOL signals.
GPT-6 must still propose a legitimate LONG/SHORT with executable stop and
target. The deterministic model-size ceiling can **reduce** its quantity,
but never upgrade what the model requested, turn a WAIT into an order, or
change the direction/exit levels. Broker wallet equity, affordability,
fees, liquidation, account-wide exposure, stop-loss and take-profit are
rechecked before any order. Normal dashboard and supervised FIRE remain
one-contract, disabled unless separately authorized.

The fixed **0.5% daily equity-decline halt** remains. A large stopped-out
trade can exhaust the whole daily budget; this is expected and should not be
manually bypassed. Slippage can exceed modeled risk. A 48/day schedule may
increase paid API use substantially, even when GPT-6 returns WAIT. DEMO
performance never predicts real-money profitability.

After a release, the exact private owner arm marker must match the versioned
policy string `DELTA-INDIA-DEMO:BTCUSD:UNATTENDED:30MIN-MAX48-UTC-DAY`.
Replacing the old 2/day arm requires an archived, mode-0600 prior file and a
fresh signed read-only preflight. Never delete attempt history or change
broker settings to force eligibility.


## Directional-only autonomous GPT-6 decisions

For the BTCUSD Delta India DEMO 30-minute autonomous worker, GPT-6 must
return a LONG or SHORT directional candidate and choose a confidence tier
(1, 2, or 3 contracts). On mixed evidence it is asked to choose the
comparatively better-supported side with one exploratory contract; it
must not invent missing market readings or executable exit prices.
The original model WAIT action remains supported in supervised FIRE.

An autonomous GPT-6 response containing WAIT is a protocol error, not an
entry or a substitute order: a bounded reason code, autonomous_invalid_wait,
is stored with no broker POST. The worker halts on that unexpected response
for review instead of retrying invalid model output or placing arbitrary
directional orders.

This does not guarantee a broker entry every 30 minutes. Signed
flatness/account proof, daily equity guard, local 24h history, market
quality, acceptable leverage, broker wallet/margin and risk budget,
real-time tick-size stop/target, liquidation buffers and protective
bracket verification can independently refuse execution. A known open
position/order is skipped without consuming an AI attempt.

The policy may increase the number of directional DEMO trades relative to
a strategy that permits WAIT. This is an experimental risk choice, not
an established statistical trading edge.


## Loss-analysis evidence pipeline (no paid AI)

The existing BTC/XAUT read-only learning watcher now refreshes a local
BTCUSD loss-diagnostics snapshot once per 30-minute UTC bucket, without
changing trades, calling GPT-6/Kimi, or modifying broker accounts:

- data/btc-loss-diagnostics.json (local mode-0600 report)
- Rebuild manually with:
  PYTHONPATH=src .venv/bin/python -m tradebot.btc_loss_diagnostics
  --financial-database data/fire-reconciliation.sqlite
  --fire-database data/fire-ops.sqlite

This analysis requires a FINISHED trade and a complete independent
broker reconciliation: matched entry/exit fills, broker wallet
cashflows, fees, funding and unique ownership IDs. Without it, the
output explicitly reports financial_reconciliation_ledger_missing or
awaiting_broker_reconciled_trades. A position disappearing, an AI
hypothesis or a locally reported flat state is never evidence of
realized profit or loss.

The verified subset is broken down by exploratory-one / medium-two /
strong-three size tier, LONG versus SHORT, wins versus losses,
and net USD expectancy. For each verified loser the report distinguishes
three ACCOUNTING components: negative gross fill-price P&L, fees
overwhelming otherwise nonnegative gross P&L, and funding turning
otherwise nonnegative post-fee P&L into a loss.

**Important:** These are measurable loss contributions, not proven
reasons why the market moved. Questions such as late entry, contradictory
EMA/ADX, range chop, poor stop placement, or excessive spread need
matched pre-entry market context and multiple winners AND losers as
comparison examples. Kimi can later generate candidate hypotheses
only once broker facts exist; its paid reviewer remains OFF by default,
and no hypothesis changes GPT-6 execution instructions automatically.

More DEMO trades are useful for testing, but do not imply that more
losses are desirable or that the strategy has learned. Avoid changing
strategy thresholds after each isolated loss, and validate any proposed
rule on an untouched out-of-sample period.
