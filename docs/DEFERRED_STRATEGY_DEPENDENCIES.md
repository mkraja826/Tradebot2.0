# Deferred strategy dependencies — 2026-11-25
Five candidates are deferred in the recovered registries. Their full mathematical trigger predicates are not specified by the deferred entries; do not invent or claim to restore exact formulas.

| ID | Exact registry requirement | Candidate source | Remaining work |
| --- | --- | --- | --- |
| B17 short_squeeze | validated funding units and liquidation/positioning evidence | Delta raw funding history; Bybit public BTCUSDT liquidation, funding history and open interest | Verify unit, sign, interval, product and timestamp; collect distinct reference-venue observations; calibrate a new hypothesis separately |
| B18 long_liquidation | independent liquidation-flow feed | Bybit all-liquidation stream | Validate position side semantics, size units, duplicates, heartbeat, reconnect gaps and coverage; missing interval is unknown not zero |
| G20 inflation_release_reaction | actual CPI and consensus forecast | BLS release/calendar + licensed point-in-time survey consensus | Archive matching reference month, release vintage, measure, units, forecast before release and actual after release |
| G21 employment_release_reaction | actual NFP and consensus forecast | BLS Employment Situation + licensed point-in-time survey consensus | Match first published headline payroll change in thousands and pre-release forecast; distinguish revisions |
| G25 weekend_reference_reopen | verified reference-market trading calendar and fresh gold reference | Selected actual reference venue, its official schedule, trade timestamps | Confirm product/session calendar including exceptions, DST, weekend schedule and first post-reopen actual trade; indicative spot update is insufficient |

Source documentation:
- https://docs.delta.exchange/
- https://bybit-exchange.github.io/docs/v5/websocket/public/all-liquidation
- https://bybit-exchange.github.io/docs/v5/market/history-fund-rate
- https://bybit-exchange.github.io/docs/v5/market/open-interest
- https://www.bls.gov/schedule/2026/
- https://www.bls.gov/news.release/empsit.htm
- https://tradingeconomics.com/calendar/api
- https://www.cmegroup.com/markets/metals/precious/gold/specs
- https://www.cmegroup.com/trading-hours.html

Observed runtime: BTC 48 implemented, 47 evaluable, 1 unavailable (funding z scores); 170 raw hourly funding samples, not proof of validated units. Gold 47 implemented, 42 evaluable, 5 unavailable (daily macro/stress inputs); 232 indicative reference samples, exchange_trade_timestamp_verified false and executable_spread_available false. These are a snapshot, not permanent status.

Next: public reference liquidation collector in research-only mode, separate from Delta demo execution, followed by feed coverage and funding-unit audit. No venue-wide liquidation completeness beyond the named reference venue is implied. Do not conflate futures calendars with spot reference or a 24/7 product. Consensus access, cost and VM connectivity not verified. No paid subscription, orders or new trading strategy enabled by this audit.
