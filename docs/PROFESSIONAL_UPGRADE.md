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

## Increment 7 — Signed demo equity decline checkpoints (UTC)

A persistent `fire-equity-risk.sqlite` monitor records *only verified Delta Demo
wallet net equity* and its observation timestamp, without raw wallet/credential
payloads. The independent FIRE watchdog now samples equity once per minute,
without asking any AI and without affecting its protective-order duties.

The entry pipeline requires both daily and weekly opening equity checkpoints
captured in the first five minutes after the UTC boundary. If the observation
history is incomplete (for example, deployment in the middle of a week),
**new FIRE orders are blocked** before GPT-6 rather than inventing baselines.
Once the necessary history exists, a 2% daily equity decline, 5% weekly decline,
or 8% drawdown from the *highest equity recorded since monitoring began*
rejects entry. The gate checks again against a signed wallet reading after the
GPT-6 decision and before the broker POST.

These are **conservative equity-loss proxies including unrealized P&L**, not
realized trade P&L. They can be affected by deposits, withdrawals, funding,
transfers, and incomplete historical peak data. This milestone does not yet
satisfy accurate broker-reconciled daily/weekly realized loss, total lifetime
drawdown, or correlated portfolio risk. The guard only protects the manual
FIRE entry pipeline; it is not yet wired to the legacy separate demo executor.
Do not enable autonomous demo execution.

## Increment 8 — Fill and wallet reconciliation

The next agreed accounting increment is implemented for closed BTCUSD and
XAUTUSD FIRE receipts. Reviewing a trade in the chart desk or ChatGPT plugin
now attempts signed, read-only broker reconciliation, with a 60-second cache.
The standalone command performs a fresh review:

```bash
.venv/bin/python -m tradebot.fire_reconciliation --symbol BTCUSD --fire-id YOUR_FIRE_ID --data-dir data
```

It exits 0 only for a verified result; 2 means evidence is unavailable or does
not satisfy the checks. It never enables orders, calls AI, changes risk
settings, or edits a trade receipt. Existing read-only demo credentials must
already be available in the process environment.

### Evidence required

- Exact broker entry/exit identities and the entry's FIRE client ID; all known
  orders terminal. Per-order quantities must match all individual fills,
  including a cancelled partial entry or multiple partial exits.
- USD-settled vanilla perpetual specifications, matching fill-side product
  metadata and contract multiplier. Prices, quantities and cashflows use
  decimal arithmetic; currencies are never implicitly converted or added.
- Complete paginated product-fill and account-wallet windows from the FIRE
  request through the observation cutoff. Missing pagination metadata,
  repeated cursors, conflicting duplicate IDs, or more than 40 pages fail
  closed. The request window is bounded to 31 days.
- Broker position size after every fill must reproduce an initially flat,
  isolated position ending flat. Intervening manual/unowned fills block
  attribution. Liquidation, ADL, settlement and OTC fills are not supported.
- Wallet cashflow must match fill-derived gross P&L; signed commissions must
  match fill commissions, including negative maker fees. Funding postings
  must match the final fill's broker `new_position.realized_funding` total.
  Missing funding metadata is unknown, never an assumed zero.
- Posting ownership uses exact order/fill references when present. A
  product-only posting may be attributed only inside the proven isolated
  position interval. Delayed unreferenced entries, unscoped wallet debits,
  conflicting references, unknown adjustments/taxes/credits or other
  unsupported financial types prevent verification. Explicit deposits,
  withdrawals and transfers are excluded from trading returns.

The last fill must be at least five minutes before the query cutoff. This is
a local settling buffer, **not** an exchange settlement guarantee. A successful
report is an **as-of-cutoff** reconciliation, not a guarantee against future
broker corrections or late postings. Repeating a read recomputes the result;
an unsuccessful fresh read never falls back to a saved verified outcome.

`data/fire-reconciliation.sqlite` holds normalized immutable fill/posting
facts and append-only reports. Evidence IDs cannot be claimed by two FIRE
receipts. Conflicting evidence rolls back the batch and withholds verification.
Raw responses, wallet balances, IP addresses and credentials are not saved in
this ledger. Prior reports remain historical observations; they must not be
treated as a current performance feed without fresh validation.

The scorecard displays verified net P&L only when both the reconciliation
status and verification flag agree and the amount is present. Otherwise it
keeps the existing provisional estimate and shows the missing-evidence reason.
The old `pnl_after_fees_usd` compatibility field remains provisional even when
a separate verified net field is available.

### Verification and remaining work

Offline coverage includes long/short BTC/gold trades, partial entries/exits,
rebates, funding, duplicates, currency isolation, external activity, delayed
postings, malformed/paginated responses, immutable evidence and scorecard
integration. No paid AI calls or demo/live orders are needed for these tests.

This increment is **not VM-deployed or broker-commissioned**. Delta's
[documented API](https://docs.delta.exchange/) describes fill metadata and
wallet transaction types, but does not guarantee all optional fields or
wallet reference keys. Actual VM responses must satisfy these conservative
checks; unsupported schemas remain unverified. Automatic discovery of manual
or emergency exits with missing IDs, old-history backfill, fee-credit/tax
handling, and complete daily/weekly realized portfolio loss accounting remain
pending. No autonomy is enabled and no claim of profitability is made.

Next: deploy and commission this read-only reconciler against existing demo
receipts, inspect unresolved reason codes, then build validated portfolio
performance metrics before event-triggered opportunity scanning.

## Increment 9 — Verified-only performance statistics (offline)

`python -m tradebot.fire_performance --database data/fire-reconciliation.sqlite`

reads **only existing local immutable reconciliation reports** (no broker
network calls, no orders and no paid GPT-6/Kimi/DeepSeek requests). It provides
separate BTCUSD, XAUTUSD and combined VERIFIED SUBSET statistics: win/loss/
breakeven counts, win rate, fee/funding-adjusted net USD, average net USD per
verified trade, profit factor when defined, and a trade-sequence drawdown
**only over the verified subset**.

Results are explicitly **not complete account profitability, account max
drawdown, ROI, trade expectancy in R, strategy edge, or current broker state**.
Each trade's most recent timestamped reconciliation determines inclusion.
A newer unverified snapshot, contradictory same-time snapshots, missing
timestamp, malformed economics, or duplicate attributed broker facts prevent
that trade from inflating performance. The output reports excluded samples,
their reason codes and original evidence-as-of timestamps.

There is no claim that the reconciliation ledger contains every executed or
closed FIRE; a complete trade inventory and fresh broker evidence must be
commissioned separately. For fewer than 100 verified trades, sample sufficiency
is explicitly flagged; even larger samples require prospective out-of-sample
evaluation. An empty ledger is not treated as zero profitability.

This milestone remains repository-only until the VM can be staged safely.
Do not restart services with open demo positions, elevate broker leverage,
or enable autonomous execution on the strength of these metrics.
