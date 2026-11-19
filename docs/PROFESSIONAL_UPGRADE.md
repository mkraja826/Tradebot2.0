# Professional Upgrade — Increment 1

This increment improves market-data integrity without altering the GPT-6,
DeepSeek or Kimi model roles, enabling autonomy, or using any paid AI API.

Historical five-minute candles with extreme departures (more than 60% from
neighboring closing prices) are held in a persistent `candle_quarantine`
table. Original values and reason codes are retained for investigation;
refetching a page cannot automatically release a quarantined timestamp.
Previously stored extremes are independently checked during levels queries.

All day/week/month results include a quality status and quarantine count.
Unverified periods expose no highs/lows. When FIRE has an attached archive,
missing or suspect required periods cause a deterministic rejection BEFORE
calling GPT-6 or sending a Delta Demo order.

This is an anomaly TRIAGE heuristic, not independent source verification.
Unusual legitimate prices may be flagged and require investigated release.
The archive still needs cross-source confirmation, complete gap detection,
deduplication across pages, an authenticated release workflow, and finer
instrument-specific thresholds. No autonomous demo execution is enabled.

Next: enforce a separate equity-at-risk governor and add AI cost accounting.

## Increment 2 — Deterministic per-trade risk (code change)

The broker's configured per-product leverage must now be at most **5x**;
higher settings block FIRE before any paid GPT-6 request. The pre-AI sizing
budget also caps total notional at five times verified equity. After the
model decides, a separate backend risk gate computes loss at the actual
buy/sell quote, including assumed two-way taker commission and a 0.05%
slippage reserve on each side. Default maximum loss is **0.25% of verified
equity** and expected net reward-to-risk must be at least **1.5**.
Compliant fractional contracts are not invented to force execution.

**This does not yet satisfy the portfolio-risk milestone.** Daily and weekly
realized loss, pending risk reservations, funding, multi-symbol exposure and
maximum drawdown require a broker-reconciled accounting ledger and additional
cross-process gates. The current feature is NOT authority to enable unattended
demo execution. A 5x leverage setting is required at the exchange; no
automatic leverage-setting API call was added. Existing VM processes remain
unchanged until the operator deploys the repository and reruns supervised
demo tests.

## Increment 3A — Hard one-contract supervised pilot limit

The original systemd installer advertised `TRADEBOT_FIRE_MAX_CONTRACTS=1`,
but FIRE's backend sizing could still authorize more than one contract.
Backend now caps its verified quantity budget at one contract and the
separate risk gate also rejects any proposal above one contract.
No existing order is modified; deploying code alone does not restart the VM.

## Increment 3B — Lower default DeepSeek billing cadence

The NYSE-only read-only observer still polls once per minute, but its paid
DeepSeek proposal cadence is reduced from 5 minutes to 1 hour. This is a
low-cost interim throttle, not a complete event-triggered scanner. It does
not modify GPT-6 FIRE, Kimi, or the independent protective-order watchdog.
A persistent provider-call quota is planned as a separate hardening layer.

## Increment 3C — Durable DeepSeek request budget

The NYSE-only DeepSeek research runner reserves permission from a private
SQLite quota ledger before making a paid model request. Its default quota is
8 requests per America/New_York day, 160 per month, persisted across process
restarts and shared across runner instances using the same data directory.
A duplicate reservation ID never authorizes another inference. Any database
failure prevents the AI call rather than allowing unmetered spending.
This is a request-count budget, not a measured dollar cost. Broker monitoring
and separate FIRE/Kimi remain independent. Configure provider-side monetary
spend limits as well.

## Increment 4 — GPT-6 may explicitly WAIT

FIRE GPT-6 now has a valid structured `WAIT` decision with zero contracts,
no stop or target, and a mandatory explanatory thesis. WAIT produces a
recorded `gpt6_wait_no_trade` receipt and does not post any exchange orders.
Malformed WAIT payloads still fail closed. This avoids forced entries and
preserves GPT-6 as the only FIRE decision model.

## Increment 5 — Broker evidence integrity and financial-status honesty

The confirmed-fill SQLite ledger now rejects an exchange fill ID if any
economic field conflicts with an existing record or another record in the same
batch. An entire conflicting batch rolls back transactionally; identical
evidence remains idempotent even if extra broker metadata changes.

The trade detail scorecard now explicitly reports:
- `financial_reconciliation_status`: `awaiting_complete_broker_evidence`
  or `provisional_order_level_only`;
- `net_realized_pnl_usd: null` and `is_net_realized_pnl: false` until full
  broker settlement/funding reconciliation is implemented;
- a clearly named `provisional_pnl_after_order_fees_usd` estimate when valid
  entry/exit order evidence exists.

The legacy `pnl_after_fees_usd` estimate is retained solely for compatibility
and MUST NOT be displayed as financially reconciled net profit. No funding
fees, incomplete partial fills, or wallet transfers are fabricated.

## Increment 6 — Cross-FIRE portfolio entry reservation

A shared, private `fire-portfolio.sqlite` file serializes BTCUSD and XAUTUSD
FIRE entry ownership on a single VM. Each worker claims the account with an
immediate SQLite transaction before requesting GPT-6. A second FIRE is
rejected while its owner is pending, protected, reconciling, or unknown.
Admission can move to another FIRE only after a terminal state with
documented no-entry or broker-confirmed flatness evidence. A missing or
unreadable owner receipt fails closed. This also checks legacy outstanding
receipts when the feature is first deployed.

The reservation does **not** inspect all manual/third-party positions,
transactions or external execution services, and is **not** yet a complete
portfolio risk governor. It does not transfer risk limits to Kimi or DeepSeek,
does not run in the broker watchdog, and does not activate demo autonomy.
All FIRE controllers must point to the **same data directory** on the VM.
