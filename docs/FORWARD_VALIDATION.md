# Prospective reference validation protocol
Freeze the enrollment start on first run; do not enroll prior shadow packets.
Use the earliest recorded planner packet per UTC two-hour bucket, including
neutral packets. Retain nonoverlap for each horizon. Entry is the next
aligned five-minute open plus one five-minute interval; exit is 15m, 1h
or 4h later, evaluated only after its candle closes. Public production
candles are read without authentication, separately from demo execution.
Assume 15 bps round-trip cost. Record missing reference outcomes explicitly;
a public-feed request failure leaves pending outcomes for retry. The
250-bar lookback limits recovery after long outages. Retain packet contents
and hash; no fitting or changing the protocol retrospectively. Actual
demo fill counts are observed separately; no attributed P&L or win rate
is claimed. This measures the existing direction, not an AI planner
alternative; no model calls, trading settings or order actions.
