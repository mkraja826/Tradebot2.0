# M09 — Delta India DEMO wallet UUID reconciliation adapter

## Original failing evidence (22 Nov 2026)

Operator performed a sequence of signed, **GET-only** diagnostics without
writing the original FIRE/risk/financial SQLite databases.

- M09 probe: product identity passed, parent/SL/TP GET-by-ID passed,
  normalized BTC fills passed, but `wallet_postings` was blocked.
- Sanitized exception: `DeltaError: Missing account history ID`.
- Same-request wallet page schema: 6 dict records, **all 6 missing `id`**,
  **all 6 having a non-null string `uuid`**, metadata `after=None`.
- Fields observed (names only): amount, asset_id, asset_symbol, balance,
  created_at, fund_id, meta_data, product_id, transaction_type, user_id,
  uuid. No raw UUID values, wallet figures, API credentials or transaction
  records were shared with the assistant.
- Delta Exchange published docs for GET /v2/wallet/transactions show an
  example numeric `id`, while the actual DEMO wallet schema provided
  `uuid` instead. This is a *documented-example vs observed-demo*
  response mismatch, not proof of missing broker transactions.
  Source: https://docs.delta.exchange/ Wallet -> Get Wallet transactions.

## Strict minimal fix

Only within `DeltaDemo._account_history`, and **only** when the path is
`/v2/wallet/transactions` and `id` is absent:
- Require the broker-provided `uuid` as a **string** representing a valid
  32-hex or canonical 36-character UUID (with actual correct dashes).
- Parse it using Python stdlib `uuid.UUID`. Derive `id` from the canonical
  representation **of that same exchange-provided UUID**, without generating
  a random ID, hashing row data or using timestamps as substitutes.
- Reject missing/malformed UUIDs; preserve the existing IDs if already
  supplied by the broker.
- Retain original raw `uuid`, strict per-page and cross-page consistency,
  cursor validation, pagination completeness checks, request auth and
  `allow_orders=False`. Duplicate identical pages de-duplicate; duplicate
  UUIDs with inconsistent contents hard-fail, never arbitrarily choose a row.
- Explicitly do **not** relax `/v2/fills` identifier requirements or
  expand trading permissions.
- Existing `normalize_posting` and append-only financial evidence reader
  then consume the broker-stable canonical ID and keep broker evidence
  attribution checks intact.

If the actual VM UUID strings do not match valid standard UUID syntax,
the adapter **still fails closed**, and a further sanitized schema audit
must be done. Merely having `uuid` in six rows is not proof each value
is unique, valid or durable. This implementation does not claim those live
properties have been verified yet.

## Offline tests and VM rollout

New `tests/test_wallet_transaction_identity.py` covers exact authenticated
GET-only wallet rows with UUID, undashed string canonicalization, legacy
numeric id, missing/null/invalid UUID, collisions/conflicting transactions,
duplicate-page IDs, pagination and malformed cursors, unchanged fill strictness,
and downstream posting normalization. The existing offline `test_delta.py`,
`test_fire_reconciliation.py` and `test_fire_reconciliation_phase_probe.py`
also must pass.

This is a **source-only** fix. PR merge does not update the production VM
processes, change FIRE, rotate keys or write live ledgers.

After GitHub merged-main CI success, use guarded operator SSH:
1. Verify current source SHA, clean tracked tree, all 5 protective+alert services
   active and both BTC/Gold FIRE endpoints disabled.
2. Source-only fetch/switch to the exact new merged SHA, with no restarts.
3. Run offline targeted tests using `PYTHONPATH=$PWD/src`.
4. Source private mode-0600 DEMO credentials, force `allow_orders=False`
   and disabled FIRE flags, and run
   `python -m tradebot.fire_reconciliation_phase_probe --data-dir data`.
5. Result `stage=wallet_normalization` or `stage=financial_analysis` narrows
   the *next* independently verified gap; results must remain sanitized.
6. Confirm no unchanged original database or broker mutating actions occurred.

**Milestone M09 is NOT completed by a successful wallet parser.** All 32
locally-flat historical receipts still lack durable broker-backed financial
reviews. Only future signed full fill/order/wallet evidence, genuine accounting,
append-only reconciliation after backups and verified agreement can close M09.
M07 weekly equity anchor, M08 quarantined BTC candle anomalies, M10 continuous
protection and M11 account risk also remain mandatory before a separately
approved first supervised BTC DEMO trade. Historical Gold one-shot lock is
preserved, Gold trading disabled.
