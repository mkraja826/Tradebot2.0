# Direction engine v1 (demo research)
All existing rules still run against the original full snapshot. 48 BTC and
47 gold rules are implemented; 2 BTC and 3 gold candidates remain deferred.
Each distinct triggered strategy contributes at most one directional vote,
regardless of timeframe count. Conflicting directions within a rule abstain.
More long votes than short votes selects LONG; the reverse selects SHORT.
A single unopposed signal qualifies. Ties and no active signals are NEUTRAL
and do not dispatch a paid AI request. Missing data never contributes a vote.
Equal votes are an uncalibrated engineering default, not a probability or
proven edge. The AI may choose no_trade when it cannot construct a valid
proposal, but it cannot reverse a selected direction. Existing order checks,
demo endpoints, position management and signal deduplication remain intact.
Journal retains full original evidence; provider receives compact current
indicator context, actual account information and strategy votes. This is
not a backtest and no real-world profitability has been demonstrated.
