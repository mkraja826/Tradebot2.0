# Remote approval contract

Development specification only; no live permission changes.

## Approval
An independently authenticated operator approves a canonical request digest containing request ID, action, arguments, target, expected current revision, expiry and nonce. Chat text alone is not an authentication credential. The approval authority must be independent of the MCP process; its signing key must not be readable by MCP. Verify signature, audience, expiry, exact digest and single-use nonce. Fail closed on missing or invalid approval.

## Execution
Root-owned executor configuration defines fixed action handlers and permitted services. Never execute arbitrary shell or user-supplied executable paths. Begin with non-trading test operations. Deployments require exact tested revision, explicit target, verified rollback and fresh exposure reconciliation. Preserve account isolation. Do not enable trading service restarts until reconciliation is independently verified. Keep credentials out of requests, logs and responses.

## Audit
Record request digest, approval identity, timestamps, execution result and verification outcome in executor-owned storage. Atomically consume approval before execution; reject replay. Distinguish pending, approved, running, succeeded, failed and unknown outcome. Do not automatically retry unknown mutations.

## Acceptance tests
Reject forged, expired, replayed, modified, wrong-target and unauthorized requests. Verify concurrent execution exclusion, rollback and crash recovery. Verify that MCP cannot forge approval or alter executor policy. Existing local approval remains required until independent authentication and deployment are verified.
