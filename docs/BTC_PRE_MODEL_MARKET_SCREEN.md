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
