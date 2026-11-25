# Reference research data
Demo fills and candles may be distorted by simulated liquidity. The original demo
dataset is retained for provenance. Production-market candles are obtained only
through the public unauthenticated GET endpoint, in a separate reference database.
No credentials, exchange order routes, or live bot configuration are used.
Validate each exact window and database coverage. Anomaly thresholds are descriptive
flags, not automatic deletions. Compare price levels and extreme movements with
independent references before fitting weights. Outcome correlations are conditional
on identical decision timestamps and are not activation correlations. Do not fit
or deploy weights from anomalous data or reuse inspected holdout outcomes as a
new independent validation set.
