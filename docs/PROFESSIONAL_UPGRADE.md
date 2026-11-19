# Professional Upgrade — Increment 1

This increment improves market-data integrity without altering the GPT-6,
DeepSeek or Kimi model roles, enabling autonomy, or using any paid AI API.

Historical five-minute candles with extreme departures (more than 60% from
neighboring closing prices) are held in a persistent `candle_quarantine`
table. Original values and reason codes are retained for investigation;
refetching a page cannot automatically release a quarantined timestamp.
Previously stored extremes are independently checked during levels queries.

All day/week/month results include a quality status and quarantine count.
Unverified periods expose no highs/lows. When FIRE has an attached archive,
missing or suspect required periods cause a deterministic rejection BEFORE
calling GPT-6 or sending a Delta Demo order.

This is an anomaly TRIAGE heuristic, not independent source verification.
Unusual legitimate prices may be flagged and require investigated release.
The archive still needs cross-source confirmation, complete gap detection,
deduplication across pages, an authenticated release workflow, and finer
instrument-specific thresholds. No autonomous demo execution is enabled.

Next: enforce a separate equity-at-risk governor and add AI cost accounting.
