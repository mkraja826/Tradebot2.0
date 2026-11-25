# Controlled position management verification

## Completed offline
Use the latest archived demo snapshot and acknowledged entry receipts. Distinct leg IDs and matching prices/quantities are evidence of a bracket, not a verified parent-order relationship. Run synthetic partial/full closure cases, stale/resized bracket quantities, residual orders, ambiguous acknowledgments, duplicate fills and inconsistent position changes with no exchange mutations.

## Outstanding exchange test
Use a dedicated, isolated demo test account without an existing position or active strategy worker. Record product, position and bracket identities before and after each separately authorized test. Confirm which amendment target is accepted with Delta support/documentation before attempting an amendment. A success-only amendment response requires subsequent observation. For partial/full closure, reconcile terminal order, fills, position quantity and residual bracket orders; do not infer auto-adjustment. Do not retry unknown submissions or cancel existing protections as a workaround. Do not run against the two currently occupied strategy accounts simply to test the API.

Reference: https://docs.delta.exchange/ (Edit Bracket order, Order schema, Place order). This file is a test protocol, not an executable trading workflow.
