# M09 — Read-only wallet attribution triage (DEMO)

The single-trade phase probe diagnoses why verified broker financial reconciliation is blocked.
It is not the official immutable ledger report, and cannot authorize trades. **FIRE must remain
disabled** until *all* separate deployment, equity, risk and execution release gates pass.

## Safe use on the already configured VM

After code review/merge and source update (without restarting the active protective services):

```bash
cd ~/Tradebot2.0
git pull --ff-only
source .venv/bin/activate
python -m pip install -e .
python -m unittest discover -s tests -p 'test_fire_reconciliation*.py'
set -a
source ~/.config/tradebot2/keys.env
set +a
export PYTHONPATH="$PWD/src"
export TRADEBOT_FIRE_DEMO_EXECUTION=false
export TRADEBOT_GOLD_FIRE_DEMO_EXECUTION=false
.venv/bin/python -m tradebot.fire_reconciliation_phase_probe --data-dir "$PWD/data"
```

For the original previously completed BTC request, use the exact ID from the
local receipt instead of relying on a rolling seven-day selection:

```bash
.venv/bin/python -m tradebot.fire_reconciliation_phase_probe \
  --data-dir "$PWD/data" \
  --fire-id b7f242b10c584d6eacc831f9f713eaf8
```

The explicit ID path accepts only an existing locally verified, completed BTC
receipt less than 60 days old. Even if invoked 30 days after the trade, the
requested broker history is capped at **seven days from its original
creation**. Late postings outside that cutoff remain unknown; no receipt
is fabricated or reassigned. This CLI remains read-only and never authorizes
trades. If the broker cannot provide complete pages within the requested
window, the existing fail-closed reason still blocks reconciliation.

Exit status 2 is the expected fail-closed result when financial evidence is still blocked.
Do not post any API keys, full broker responses, signed headers, raw wallet history,
transaction IDs, or account balances into chats or GitHub issues.

## New read-only field

On `reason=unattributed_wallet_posting`, the optional
`unattributed_wallet_posting_diagnostic` shows:

- `count`: how many normalized economic postings fit the ambiguous category;
- up to five `examples`, reduced to fixed vocabulary: product scope
  (`same_product` or `account_unscoped`), time bucket, presence/absence of
  order and fill references, and posting kind (`cashflow`, `commission`,
  `funding`, or `other`);
- `examples_truncated`: whether more than five classifications were found.

- `amount_consistency_clues`: at most five type-scoped exact arithmetic
  comparisons against selected trade fills: total cashflow, total commissions,
  one individual fill commission, last-fill funding (if broker supplied), or
  an observed non-owned fill commission from the same product. True means
  numbers happen to match; false means they do not; null means not applicable.
  **An exact match is never transaction ownership evidence.**
- `unowned_same_product_fills_after_last_fill`: count of non-owned BTC fills
  observed after the selected exit within the same broker history window.
- `other_product_fill_history_checked=false`: Gold and other products were
  not searched by the product-specific fill reader.
- `amount_matches_prove_broker_attribution=false`: immutable statement that
  arithmetic cannot replace verifiable wallet provenance.


The diagnostic deliberately excludes raw identifiers, timestamps, cash amounts,
wallet balances, credentials, and broker payloads. A null field means that
the specific ambiguous-posting diagnosis was not obtained.

**Interpretation:** this field only tells the operator which external evidence
to investigate in the broker account. Do not silently discard delayed postings,
treat them as zero funding, amend historical immutable reports, or relax
`trade_authorized=false`, `safe_to_enable_fire=false`, or the FIRE kill switch.
Conclusive attribution requires verified signed broker evidence and a separately
reviewed code change with regression tests. The first supervised BTC testnet
trade remains separately release-gated; production account trading is unsupported.
