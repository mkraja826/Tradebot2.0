# BTC demo — additional completed-candle indicators

The dedicated BTC 24h strategy now computes five additional features using
the **original 288 contiguous, locally validated Delta India DEMO five-minute
OHLCV candles**. No monthly/weekly highs or paid data services are required.

- RSI(14): Wilder-smoothed positive/negative completed-close changes; a
  completely unchanged series is neutral RSI=50.
- ADX(14): Wilder true range and directional movement, including +DI and -DI.
- RVOL(20): most recently completed five-minute volume divided by the
  arithmetic mean of the preceding **20 completed** five-minute volumes.
  If prior mean volume is zero, RVOL is marked unavailable, not fabricated.
- MACD(12,26,9): SMA-seeded exponential price averages, MACD line, 9-period
  EMA signal and histogram.
- Bollinger Bands(20,2): 20-close mean and +/- two population standard
  deviations, bandwidth in basis points and percentage-B when width >0.

The new `technical_5m` field is part of the BTC supervised/autonomous
strategy context. The GPT-6 prompt treats the features as potentially
conflicting observations; no indicator alone triggers an order. A missing
relative-volume baseline does not silently become a bullish/bearish signal.

This implementation performs no direct exchange API call, database mutation,
trade authorization, or AI call. All features are derived from **completed
candles only**, excluding the current incomplete bar. Existing local
quarantine and extreme-price checks remain mandatory.

The code is intended for further independent backtesting and walk-forward
validation before any claims about trading performance.
