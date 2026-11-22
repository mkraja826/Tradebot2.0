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
