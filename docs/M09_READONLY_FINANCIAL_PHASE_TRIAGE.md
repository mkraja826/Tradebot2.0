# M09 — diagnose one BTC financial reconciliation by read-only broker phase

## Why this tool exists

The operator's live 22 Nov 2026 09:10 IST single-trade, temporary-ledger
financial audit returned:

```
Recent eligible BTC receipts: 17
financial_reconciliation_status: awaiting_complete_broker_evidence
reconciliation_reason: broker_evidence_or_ledger_unavailable
is_net_realized_pnl: False
funding_reconciled: False
```

The existing `reconcile_fire` method deliberately catches unexpected errors
without printing raw private broker information. That generic reason alone
cannot distinguish product lookup, order by ID, paginated fills, wallet
history, normalization, accounting or temporary SQLite storage.

`tradebot.fire_reconciliation_phase_probe` is a **separate fail-closed
read-only probe**. It selects one original locally-flat BTC receipt with complete
saved bracket fields and no existing local financial report, no older than
seven days and at least ten minutes old. It uses the same hardcoded Delta
India DEMO endpoint as the normal code, always `allow_orders=False`.

The phases, in order:

1. Validate original read-only FIRE inventory, verify one original local
   receipt and saved parent/SL/TP order IDs; skip unresolved/old records.
2. GET DEMO product identity and contract.
3. Authenticated GET parent + SL + TP by the saved decimal order ID.
4. Authenticated paginated GET complete BTC product fills.
5. Normalize fill schemas in memory, without storing PII.
6. Authenticated paginated GET all account-wallet transactions.
7. Normalize posting schemas in memory.
8. Perform the existing `analyse` accounting consistency checks in memory.
9. Re-fingerprint the original FIRE receipt database; refuse changed evidence.

The diagnostic stops on the FIRST unavailable/unverified phase. It reports
`stage`, sanitized `reason`, phase names passed, aggregate counts, and
the same explicit no-trade/no-database-write flags on all outcomes.
Raw broker responses, HTTP exception descriptions, API credentials,
wallet amounts, receipt/order/fill IDs and financial values are never printed.

**No originals are written at all**, unlike the normal reconciliation runner,
which writes immutable normalized facts and reports to
`data/fire-reconciliation.sqlite`. This diagnostic also does not create
a temporary reconciliation database. It never submits an order, changes
broker settings, calls GPT-6/Kimi/DeepSeek or affects the watchdog.
It does not verify uninterrupted historical bracket protection, independent
flatness, trading edge or portfolio release.

Even if in-memory accounting matches, output is
`provisional_read_only_financial_analysis_complete` with
`is_net_realized_pnl=false` and `trade_authorized=false`. This is NOT a
durable financial review or readiness/permission to enable BTC FIRE.

## Offline tests

```bash
cd ~/Tradebot2.0
export PYTHONPATH="$PWD/src"
.venv/bin/python -m unittest discover -s tests \
  -p 'test_fire_reconciliation_phase_probe.py' -q
.venv/bin/python -m unittest discover -s tests \
  -p 'test_fire_reconciliation.py' -q
```

They use only synthetic broker/account fixtures (no outside network or
original production ledger).

## Supervised production read-only diagnostic

Prerequisite: source merged into `main` with green CI and applied
**source-only**, after verifying correct old/new SHA, protected services
active, both BTC and Gold FIRE disabled and the original working tree clean.

```bash
cd ~/Tradebot2.0
set +x
test -f "$HOME/.config/tradebot2/keys.env"
test ! -L "$HOME/.config/tradebot2/keys.env"
test "$(stat -c %a "$HOME/.config/tradebot2/keys.env")" = 600
set -a
source "$HOME/.config/tradebot2/keys.env"
set +a
unset PYTHONHOME PYTHONUSERBASE
export PYTHONPATH="$PWD/src"
export PYTHONNOUSERSITE=1
export PYTHONSAFEPATH=1
export PYTHONDONTWRITEBYTECODE=1
export ENABLE_DEMO_ORDERS=false
export TRADEBOT_FIRE_DEMO_EXECUTION=false
export TRADEBOT_GOLD_FIRE_DEMO_EXECUTION=false

.venv/bin/python -m tradebot.fire_reconciliation_phase_probe \
  --data-dir "$PWD/data"
```

Exit 0 means only in-memory accounting evidence matched in this diagnostic.
Exit 2 means a particular phase was blocked; review the sanitized
`stage` and `reason`, without pasting broker IDs or keys.

Check original ledgers and protective services unchanged after the run.
Do not run source from an unmerged branch on original VM.

## Further M09 release work

Once the first failing stage is identified, fix it with offline fixture
coverage and independently corroborated provider schema. Only after
backups and evidence review should signed fills/wallet postings be
reconciled durably through the existing append-only financial ledger;
original transaction evidence must not be fabricated. One selected
trade passing does not reconcile the other 31 locally-flat no-report
receipts nor the one anomalous Gold local FIRE receipt.

M07 authentic weekly opening, M08 perpetual candle provenance, M10 continuous
bracket protection and M11 current broker risk policy still block M12.
