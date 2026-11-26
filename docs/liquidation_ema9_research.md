# Liquidation entry + adaptive EMA9 research
Research-only BTC module; does not change any worker, account or order. Reuses the
existing Bybit BTCUSDT liquidation hypothesis journal and Delta BTCUSD candle
archive. Requires actual archived observations with receipt timestamps; candles
alone cannot identify liquidations. XAUTUSD is not supported until a verified
market-specific event feed is available.

Run on a machine with the archives:
```sh
python -m recover_trading.liquidation_ema9 --market-root /path/to/BTCUSD --hypotheses-db /path/to/hypotheses.sqlite --start START_EPOCH --split SPLIT_EPOCH --end END_EPOCH
```
Use UTC epoch seconds, up to 31 historical days. JSON to stdout; both DBs read-only.
The experimental burst threshold is >=2 observed same-side events totaling >=1 BTC,
20 bps same-direction price move and >=0.1% OI decline. First completed minute
closing outside the last pre-observation candle range in the next five minutes
determines reversal vs continuation; entry at following open. Reserve each
position window for 60 minutes for a matched comparison. Entry slippage 2 bps,
hypothetical round-trip fees 15 bps, exit slip 0/2/5 bps. Structural stop and fixed
2R target are research proxies, not AI decisions. Compare fixed bracket vs
15m V8 (EMA9 -/+ 1 ATR; activate after costs). No lookahead into unfinished candles,
no split-crossing trades. Fixed equal unit notional, reported bps, not actual P&L.
No existing-strategy benchmark, live collector deployment, Gold feed, AI integration
or trading changes in this phase. Validate archive coverage, run CI and compare
with the current entry baseline before any promotion.
