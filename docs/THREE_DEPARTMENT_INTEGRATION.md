# Three-department connection (staging)
- Entry: existing scanner and direction engine, AI planning and durable journal.
- Position: existing optional --manage-demo path; current position identity and bracket checks remain unchanged. This branch does not enable that mode.
- Learning: optional --learning-journal reads the outcome journal in SQLite read-only mode, same market and strictly prior to the current scan. Bounded typed observations only, no Kimi narrative, no forward windows, no claimed validated lessons. Both existing entry and management contexts receive the same evidence packet when enabled. Existing defaults remain unchanged.
- No new provider call, no new order path, no automatic weight changes or model retraining. A missing journal cannot veto a trade.
- Historical facts are not validated policy. Before activation compare prospective shadow plans with baseline, account for fees/funding, and test isolated demo management actions and reconciliation. No production rollout authorized by this branch.
- Tests cover cross-market isolation, temporal cutoff, malformed rows, missing journal, and shared context contract. Full integration and broker validation remain required.

## Offline integration checks
CLI default and opt-in startup, BTC/Gold routing for flat/open/unknown positions, unavailable journal fallback, one management dispatch without a simultaneous entry dispatch. These are mocked routing tests, not exchange validation or proof of performance. No deployment or activation in this PR.

## Position scenario coverage
Synthetic BTC/Gold LONG/SHORT fixtures exercise exit geometry, persisted management proposals and lifecycle plans for stop-only profit retention, reduction/full close in a losing scenario, target-only extension, maintain, and rejection of invalid dual-leg amendments or oversize reductions. Mock responses intentionally select actions; tests do not establish that GPT would choose the correct action, actual fill prices, profitability, or exchange mutation compatibility. No production or demo broker is contacted.

## Shared DeepSeek position manager
When explicit demo management mode is enabled, both workers default to TopBilling `tb-deepseek-v4-pro` for their separate position-management proposals. Existing market entry model settings remain independent and unchanged. `RECOVER_MANAGEMENT_MODEL` or `--management-model` can override this shared model. Status events record entry and active management model names separately; disabled management has null active model. Existing five-minute sampling, journal reservation, current position verification and demo-only executor remain unchanged. No new calls in default mode. No additional model provider or autonomous Kimi/Opus calls added. This does not disable existing deployed Kimi timers. The management request is synchronous within its market worker; it can delay that worker's next scan, though not the other worker. Offline tests use mocks; paid provider response and isolated demo execution validation are outstanding.
