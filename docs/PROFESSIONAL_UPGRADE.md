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
