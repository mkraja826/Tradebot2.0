# Three-department connection (staging)
- Entry: existing scanner and direction engine, AI planning and durable journal.
- Position: existing optional --manage-demo path; current position identity and bracket checks remain unchanged. This branch does not enable that mode.
- Learning: optional --learning-journal reads the outcome journal in SQLite read-only mode, same market and strictly prior to the current scan. Bounded typed observations only, no Kimi narrative, no forward windows, no claimed validated lessons. Both existing entry and management contexts receive the same evidence packet when enabled. Existing defaults remain unchanged.
- No new provider call, no new order path, no automatic weight changes or model retraining. A missing journal cannot veto a trade.
- Historical facts are not validated policy. Before activation compare prospective shadow plans with baseline, account for fees/funding, and test isolated demo management actions and reconciliation. No production rollout authorized by this branch.
- Tests cover cross-market isolation, temporal cutoff, malformed rows, missing journal, and shared context contract. Full integration and broker validation remain required.

## Offline integration checks
CLI default and opt-in startup, BTC/Gold routing for flat/open/unknown positions, unavailable journal fallback, one management dispatch without a simultaneous entry dispatch. These are mocked routing tests, not exchange validation or proof of performance. No deployment or activation in this PR.
