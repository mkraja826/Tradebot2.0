# Recover Trading market scanner

Run `python -m recover_trading.scanner` for a public-data scan of BTCUSD and XAUTUSD. Use `--symbol BTCUSD` or `--symbol XAUTUSD` to select a market; `--interval 60` repeats the scan after a sixty-second delay.

The original 95 implemented rules are evaluated without modifying their formulas. Reports list actual evaluable rules, unavailable inputs, directional signals, and five deferred rules. Unavailable market inputs are reported, never synthesized. The collector uses the recovered SQLite market store, eight candle timeframes, public demo ticker, depth, trade sample, BTC derivative history and an indicative XAU reference. Historical macroeconomic series, event surprises, and some positioning data are not yet connected. A rule requiring missing inputs cannot be evaluated; this is not an account or loss-based execution gate.

This is intentionally read-only and independent of the execution engine. There are no model calls or orders. Full-history refresh is a first implementation; incremental fetching and live feed integration tests remain pending.
