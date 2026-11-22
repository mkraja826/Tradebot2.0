# BTC supervised DEMO — deterministic pre-GPT market screen

This additional conservative screen applies **only** to
`SupervisedBTCController`, not the normal six-period FIRE controller.

After authenticated account, equity and recent local 24h history checks,
but **before a billable GPT-6 request**, the controller rejects:
- invalid, negative, crossed or nonfinite BTC bid/ask/mark prices
- bid/ask spread above 10 basis points of midpoint
- mark price dislocation above 50 basis points from midpoint
- five-minute ATR above 500 basis points of midpoint
- spread above 25% of the five-minute ATR
- missing/invalid EMA20 values, closing prices, trends or ATR
- malformed VWAP if supplied (VWAP may be unavailable)

The model snapshot carries only a sanitized `local_market_screen` pass
record with spread, mark deviation and ATR in basis points; no additional
API, AI request, order call or ledger mutation is made by the screen.

This is **not** independent perpetual-price verification. It does not
certify portfolio margin, wallet history, completeness of financial
reconciliation, SL/TP correctness or a profitable signal.

The existing recent24h input is 288 contiguous local 5-minute candles.
It does **not** require previous/current UTC week or month highs/lows.
Last-24-hour high/low remain optional useful context only when local
candle quality is valid. Corrupt historical month rows remain preserved
for independent forensic review; no archive values are overwritten.

The full normal FIRE route remains unchanged and disabled pending
its independent commissioning. The new screen cannot approve or submit
a trade. No new order is authorized by this code change.

## Independent-venue price sanity (public spot only)

The supervised BTC controller now performs a single read-only, keyless,
bounded HTTPS GET to the hardcoded Coinbase Exchange BTC-USD spot ticker,
after the local screen but before a paid GPT-6 decision.

Fail closed on a missing/unreachable/oversized/malformed response, redirects,
a stale or future-dated ticker (over 30 seconds old or >5 seconds future),
a crossed or >20-basis-point-wide Coinbase spot quote, or Delta DEMO BTC
mark diverging by >150 basis points from the current Coinbase spot midpoint.
These are conservative **operational thresholds**, not researched strategy
parameters or guarantees that cross-venue basis stays within a fixed band.

The model input contains a sanitized pass record and measured difference,
and explicitly states:
- `independent_perpetual_trade_print_verified=false`
- `trade_authorized=false`

Coinbase's BTC-USD spot instrument is not Delta's BTCUSD perpetual contract.
A matching spot quote does not authenticate individual Delta trades, fills,
order books, historical wicks, monthly candle values, or broker position
liquidation data. Original suspect candles stay quarantined/unverified.

The extra public GET is made only on the separately supervised BTC candidate
path. Normal FIRE, Gold and account protection controls remain unchanged.
The public reference is requested only when that candidate has already
passed earlier account/equity/local-history checks.
