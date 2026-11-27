# Gold V2 public source registry

All integrations are for read-only research. No orders, credentials or paid API keys.
Free access does not guarantee uptime, unchanged terms or permission for redistribution.

| Source | Endpoint/documentation | Use |
|---|---|---|
| Delta India demo | Existing public candle adapter | XAUTUSD OHLCV |
| Gold-API | https://gold-api.com/docs | Indicative XAU/USD and XAG/USD |
| XAUS | https://xaus.com/api/ | Indicative gold; annual supply/reserve stats |
| Binance | https://developers.binance.com/en/docs/products/spot/rest-api | PAXGUSDT/XAUTUSDT aggregate trades; availability to verify |
| FRED / ALFRED | https://fred.stlouisfed.org/ and https://alfred.stlouisfed.org/ | DTWEXBGS, DGS10, DFII10, DFF, T10YIE, VIXCLS, DCOILWTICO |
| CFTC | https://publicreporting.cftc.gov/Commitments-of-Traders/Disaggregated-Futures-Only/72hh-3qpy | Gold 088691 weekly managed-money net and open interest |
| Federal Reserve | https://www.federalreserve.gov/feeds/press_monetary.xml | FOMC statement metadata |
| BLS | https://www.bls.gov/feed/cpi.rss and https://www.bls.gov/feed/empsit.rss | Published CPI/employment feed metadata, not consensus surprises |

Run:
    python3 -m unittest discover -s tests -p 'test_gold_v2*.py' -v
    python3 -m recover_trading.gold_v2_scan --once --fundamentals --public-feeds

The second command makes public network requests. The feeds are observation-only.
No provider has been live-smoke-tested from the target VM in this increment.
Cache is per-process (30/60 seconds for prices, six hours for weekly/daily data);
a persistent worker must reuse a PublicFeeds instance. No persistent rate-limit
coordination or raw-feed archival is implemented yet.
Unknown/stale/future data is not substituted. Crossed 5-minute candle boundaries
during collection invalidate candidates. CFTC report date is not release time;
record first observed timestamp before prospective use. Revised FRED data is not
historical point-in-time evidence. Broad dollar index is not intraday DXY.
XAUS may share upstream with Gold-API; do not count those as independent votes.
Tokenized gold in USDT is neither USD spot nor COMEX futures.
Annual central-bank reserve stats are not current purchase flows.
BLS feed timestamp is not verified release time or economic surprise.
Macro bias thresholds are provisional hypotheses, not validated entry rules.

## Further candidates / limitations
- U.S. Treasury official XML: https://home.treasury.gov/treasury-daily-interest-rate-xml-feed
- BLS public API v1 (keyless limited rate): https://www.bls.gov/developers/
- World Gold Council ETF flows/reserves downloads: https://www.gold.org/goldhub/data
  Verify automated-use terms and stable download schema before adding.
- LBMA benchmark: https://www.lbma.org.uk/prices-and-data/lbma-precious-metal-prices
  Licensed benchmark, not a free unrestricted trading API.
- CME COMEX live/delayed machine data: https://www.cmegroup.com/market-data/real-time-and-historical-data.html
  No unrestricted keyless trading feed verified; CFTC weekly positioning is not COMEX pricing.
- Intraday DXY, geopolitical news, live ETF flows and consensus forecasts remain pending.

No paid subscriptions created, no server deployment or BTC modifications.
