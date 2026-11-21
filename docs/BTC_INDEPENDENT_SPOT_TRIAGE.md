# M08 — independent-venue BTC spot context for quarantined DEMO candles

**Stage: source-only diagnostic, not archive repair or FIRE release.**

The production Delta India DEMO 5-minute BTCUSD history contains suspicious
historical high/low values; one previously observed 2026-11-04 13:15 UTC
perpetual 5-minute candle reported a low of **0.1**. Repeating Delta's
public 5m, 1m and mark-price queries corroborates only the SAME provider's
data; it does not verify that a perpetual contract traded at that level.

## What is added

The new `tradebot.independent_spot_triage` diagnostic performs the existing
three public, no-auth **Delta India DEMO** GET checks for each specified UTC
5-minute bar and **one independent Coinbase Exchange public BTC-USD SPOT
historical candle GET** at the *same* start time.

Coinbase public Exchange historic candles are accessible without a paid
subscription or API key at
`GET https://api.exchange.coinbase.com/products/BTC-USD/candles`,
with `start`, `end`, and `granularity=300`; response rows follow
`[time,low,high,open,close,volume]`. We request only the one aligned 5m
bar, require a strict numeric/UTC/schema match, refuse duplicate/stale
or malformed responses, forbid redirects and time out after eight seconds.
No secrets are logged; the Coinbase public JSON response is represented by
a SHA-256 digest and numeric prices only. The remote response is not signed,
and a digest alone does not establish source authenticity.

- **A Coinbase spot candle is a distinct venue and instrument.** It is
  useful as independent *broader market context*, but is NOT a trade record
  for the Delta BTCUSD perpetual. Even agreement cannot release Delta's
  archive quarantine or authenticate a particular Delta perpetual fill.
- A Delta perpetual low below **40% of the Coinbase spot low**, or Delta
  high above **160% of the Coinbase spot high**, is flagged as
  `extreme_cross_venue_dislocation` for investigation. This is a broad
  severe-dislocation threshold, not a market microstructure model or a
  statistical test. The existing 60% neighbor-dislocation quarantine
  and all source/cross-timeframe gates remain unchanged.
- Missing public spot data, blocked Coinbase access, response schema issues,
  incomplete Delta minute bars and mismatched 5m/1m OHLC all remain explicit
  diagnostic blockers. Missing data is NEVER replaced with synthetic bars.
- `trade_authorized=false`, `safe_to_enable_fire=false`,
  `independent_price_validation=false`,
  `perpetual_trade_print_verified=false`, and
  `quarantine_release_authorized=false` are true invariants of the tool.
  No local archive, original SQLite, risk state or Gold one-shot lock is
  read or written. The only operations are public GETs and sanitized output.

## Offline tests

```bash
cd ~/Tradebot2.0
export PYTHONPATH="$PWD/src"
.venv/bin/python -m unittest discover -s tests \
  -p 'test_independent_spot_triage.py' -q
.venv/bin/python -m unittest discover -s tests \
  -p 'test_candle_source_diagnostic.py' -q
```

The fixtures use fake Delta/Coinbase GETs, never network or paid models.

## Read-only VM evidence collection (after source merged + verified)

Never update the original production checkout during active exposure. Once
the usual operator source-only preflight passes, run:

```bash
cd ~/Tradebot2.0
PYTHONPATH="$PWD/src" .venv/bin/python \
  -m tradebot.independent_spot_triage \
  --at '2026-11-04T13:15:00+00:00' \
  --at '2026-11-04T13:00:00+00:00' \
  --at '2026-10-23T08:40:00+00:00' \
  --at '2026-10-23T08:10:00+00:00'
```

- Exit 0: all public GETs and comparisons completed, **manual review still
  required**; does not mean prices, broker protection or trading are safe.
- Exit 2: source requests or an extreme cross-venue discrepancy incomplete/
  blocked. Maintain existing quarantine and FIRE disabled.
- The report shows spot vs perpetual extrema ratios, separate Delta source
  checks, exact UTC candles, a public-response SHA-256 and reason codes.
  It never prints credentials, wallet balances, order IDs, raw provider error
  bodies or trading instructions.

If Coinbase is blocked/unavailable on the VM, report the fixed code and
consider another reviewed, independent public source; do not substitute
untrusted paid or private sources or silently assume spot corroboration.

## Remaining M08 exit criteria

1. Preserve and independently hash the original affected Delta 5m OHLCV and
   quarantine records, with complete source timestamps and requests.
2. Cross-check the Coinbase spot result and another independent public market
   source if available, but retain clear instrument differences.
3. Inspect authentic Delta perpetual trade prints/exchange order history, or
   establish documented evidence from the provider that the print was invalid;
   do NOT assume a 0.1 traded price merely because Delta candles repeat it.
4. Obtain genuinely complete, historically correct perpetual 5m bars for the
   affected UTC periods, with explicit reviewed restoration provenance.
5. Test proposed archive remediation on a disposable SQLite copy, preserve
   originals and check all six period completeness/quality rules. Only an
   independently approved controlled release could mutate production data.
6. Re-run the FIRE admission gate read-only; no flag may be forced green.
   BTC DEMO must remain disabled until the other equity/accounting/protection
   prerequisites also pass.

This diagnostic achieves **new independent-venue context** but does not yet
complete M08. The operator's original risk ledgers and current FIRE locks are
untouched.
