# Gold recovery evidence and operator review

This is the source implementation for **Milestone 2A: recovery planning**. It
does not complete execution commissioning. It supports only the latest Gold
request that was explicitly `rejected_no_order`, has `orders_submitted=false`,
and has no durable entry intent or broker order references. Any ambiguity or
broker fill requires a separate full order/fill reconciliation procedure.

The existing `gold-demo-commission-attempt.lock` is permanent throughout this
workflow. Neither command clears, recreates, rewrites or bypasses it. No code
consumes a review record to enable execution. A new DEMO attempt still requires
a separately approved recovery procedure, fresh risk checks, explicit operator
authorization and independent supervision. Live-money execution is prohibited.

## What the packet establishes

The capture command uses the existing mutation-disabled Delta India DEMO client:

1. Read the existing Gold receipt database using SQLite `mode=ro` and `query_only`,
   check database integrity, and identify the exact latest request.
2. Bind the receipt digest to the consumed lock's digest, metadata and creation
   timing. A lock outside the narrow attempt window is unresolved evidence.
   Hash the whole Gold request/entry inventory to detect concurrent changes to
   other receipts, and reject requests tied for the latest timestamp.
3. Run the existing two-sample, account-wide positions/open-orders/receipt gate,
   isolated-margin and leverage readbacks, disabled FIRE endpoint checks, and
   dashboard/watchdog health checks. No leverage is changed.
4. Require fresh collector/watchdog evidence and genuine UTC daily/weekly
   checkpoints. Evaluate a fresh authenticated wallet response against existing
   daily, weekly and peak limits, using the same deterministic calculation as
   FIRE. This read-only check never creates an observation, changes the peak or
   recovers a missed checkpoint. FIRE independently rechecks before submission.
5. Wait at least five minutes after the recorded prior attempt's update time
   before querying its complete paginated Gold fill window (one second before
   request creation through sixty seconds after its recorded final update).
   Missing pagination metadata, timeouts and inconsistent pages fail closed.
   Even a manual Gold fill in that window blocks this restricted workflow.
6. Recheck that the receipt and lock are unchanged, then sign the report.
   Capture duration is bounded at 120 seconds using wall and monotonic clocks.

The packet includes sanitized preflight results, receipt/lock hashes, the fill
window/count/digest and explicit blocking conditions. Original receipts remain
in their original database. The packet is not a replacement backup of those
receipts or a complete financial accounting export.

**Signature scope:** Ed25519 signatures are local attestations of authenticated
HTTPS broker reads, not signatures issued by Delta. The wallet timing receipt
does not prove the broker's internal valuation timestamp. Empty paginated
history is evidence of what the API returned for that bounded interval; it
does not prove there can never be delayed fills or later manual activity.
The lock timing correlation is a consistency check, not proof of causation.

## Key custody and trust

Operators must provision a dedicated Ed25519 capture key and a different
Ed25519 operator key through their approved key-custody procedure. This code
does not generate or register operational identities. It accepts PEM files;
private keys must be restricted to the owner (mode `0600`), outside the repository
and dashboard paths. Keep the operator private key separate from the capture
service and pin both public-key fingerprints out of band. Different keys alone
do not establish that two independent people reviewed the evidence.

The `--trusted-capture-key` argument must point to the independently pinned
public key, never a key taken from the packet being verified. Protect that file
and its parent directory from untrusted writes. Audit the resulting review
against the separately pinned operator public key. Retain a protected archival
copy of both signed records and their trusted-key provenance. A key change or
compromise requires manual incident handling and new evidence; there is no
automatic trust rotation or expired-record renewal.

## Read-only commands

Run only in a reviewed staging environment, with the existing DEMO credentials
supplied through the established private environment. Use the actual rejected
FIRE ID and independently provisioned keys; the placeholders below are not
operational identities. The output directory must already exist, be private,
and be outside application data and web-served directories.

```bash
python -m tradebot.commissioning_review capture \
  --data-dir /approved/tradebot/data \
  --fire-id PRIOR_REJECTED_FIRE_ID \
  --capture-key /approved/private/capture.pem \
  --output /approved/private/review/unique-capture.json
```

A successful capture creates a private, exclusive file and fsyncs both the file
and directory. An existing output is never overwritten. A blocked capture is
also signed for investigation, with `ready_for_recovery_planning=false` and exit
code 2. Parsing, signing and file errors produce a sanitized failure, not raw
broker exceptions, keys or prompts. No signing or broker retries occur.

The operator reads the full packet, verifies the pinned capture identity,
compares the prior FIRE ID/receipt and lock, checks all blockers and confirms
the scope before deciding:

```bash
python -m tradebot.commissioning_review review \
  --data-dir /approved/tradebot/data \
  --packet /approved/private/review/unique-capture.json \
  --trusted-capture-key /approved/trust/capture.pub \
  --operator-key /approved/private/operator.pem \
  --decision accept_for_recovery_planning \
  --output /approved/private/review/unique-review.json
```

Acceptance requires an unblocked, internally consistent packet no older than
120 seconds from capture start and an unchanged local receipt and lock.
Use `--decision reject` to record rejection, including for an expired packet.
Review makes no broker calls and does not assert continuing broker flatness.
If the window expires while the operator reviews, capture a fresh packet after
reviewing the old one; never edit timestamps. Both identities sign separate
records linked by packet digest. Repeated reviews are identifiable by that
digest, never interpreted as multiple trading approvals.

Every capture and review has `trade_authorized=false` and `lock_released=false`.
The CLI has no execute, unlock, reset, retry-order or leverage-setting option.

## Validation and staged acceptance

Offline tests use temporary databases, synthetic broker replies and ephemeral
fixture keys only. They cover the real paginated broker-read helper, preflight
and equity integration, daily/weekly/peak losses, stale clocks/heartbeats,
missing checkpoints, corrupt databases, in-flight and subsequent receipt/lock
changes, partial history, manual fills, unknown submission, durable intents,
key separation/trust, signature tampering, TTL boundaries, private permissions,
exclusive concurrent writers, partial-file crash recovery, and sanitized CLI
errors. No database migration is introduced: schema/dumps remain unchanged.

```bash
python -m unittest discover -s tests -v
python -O -m unittest discover -s tests -p 'test_fire*commission*.py' -v
python -O -m unittest discover -s tests -p 'test_commissioning*.py' -v
```

Production checks must not use Python `assert`; optimized-mode tests verify
that risk rejection still works with assertions removed. The isolated capture
and review test batch includes a concurrency/latency smoke check via a bounded
number of requests and subsecond local processing; it is not a VM load test.
No dashboard assets change in this increment; the prior mobile-browser suite
remains the UI regression baseline.

Before commissioning this workflow, independently verify the real DEMO API
history pagination and window coverage, current account-wide exposure, keys,
clock, service health, fresh signed wallet transport metadata and authentic
opening checkpoints. Confirm that protected backups restore the same receipt
and lock without altering the active files. Reboot and connectivity recovery
must be tested in an approved isolated environment before any trade trial.

Acceptance of recovery planning is not acceptance of Milestone 2. That milestone
still needs a separately authorized maximum one-contract DEMO lifecycle with
broker entry/exit fill IDs, actual average prices, protective child IDs, signed
liquidation readback, continuous independent supervision and final account-wide
flatness. Partial fills, missing protection, ambiguity and failed emergency
closeout require the existing execution controls and separate commissioning
evidence. No such attempt is authorized or performed by this source change.

## Rollback and interrupted writes

This increment adds read-only commands, tightens commissioning preflight and
refactors the unchanged loss calculation. It adds no service, migration or
scheduled job and changes no execution defaults. Staging it requires no
trading-service restart. Stop invoking the new commands to withdraw the review
workflow; preserve every packet, review, database and consumed lock.

Do not roll back to an older commissioning entry point to bypass the new equity
gate. If reverting source is necessary, disable operator commissioning by the
approved deployment procedure and keep FIRE disabled and the Gold lock intact.
Use the pinned previous revision only within that restriction, after review.
Never restart any exposure-bearing process without approved protection and
rollback. The data needs no reverse migration; tests verify read-only operation
and compatibility with the existing schemas.

If power fails during file creation, preserve the partial file for investigation;
it cannot be accepted as a signed packet or overwritten by a retry. Choose a new
output name, verify the unchanged source evidence, and perform a new capture.
Do not infer success from a file's presence or a previous process exit alone.
