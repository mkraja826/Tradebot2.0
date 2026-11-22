# Equity opening checkpoint — exact UTC window boundary

## Safety defect fixed in source

The bot's existing risk guard and read-only checkpoint health diagnostic used
an inclusive end comparison. That could count a signed wallet observation
at **exactly 00:05:00 UTC** as an opening checkpoint, even though the specified
first-five-minute window ends at that instant.

This change makes the interval **half-open**:
- Eligible: `00:00:00.000000 UTC` through `00:04:59.999999 UTC`
- Not eligible: `00:05:00.000000 UTC` or any later timestamp

For a Monday weekly opening in India, that means `05:30:00` through
`05:34:59.999999 IST`. At **05:35:00 IST**, a missing opening is already
a missed checkpoint.

Four source checks are updated together:
1. `PortfolioEquityGuard._opening` cannot use a boundary reading to
   authorize its daily/weekly loss-budget baseline.
2. `require_receipt_backed_history` cannot admit an entry at the boundary
   as a newly acquired opening (and rejects a prior stored sample at exactly
   the boundary as the opening).
3. `checkpoint_health` reports `missed_window`, not `pending_window`,
   and refuses to verify a boundary-only observation as a valid opening.
4. `commissioning_equity._require_signed_anchor_receipts` independently
   rejects an authenticated 00:05-only ledger as missing an opening anchor,
   even when the surrounding health result is assumed previously green.

A valid authenticated wallet read at 00:05 can still be preserved in the
original immutable ledger as an ordinary observation, but never
retroactively backdated as the earlier period opening.

## Validation

Offline regression tests cover:
- Exactly 00:05:00 with no opening: both daily and weekly missed.
- Exactly 00:05:00 with a genuine receipt: receipt is authentic, but
  opening checkpoints remain missed.
- The last microsecond before end remains eligible if genuinely observed.
- Order-admission `require_verified_read` rejects a boundary-only anchor
  before accepting any new risk baseline.

This is a source safety correction only. It does NOT create any historical
opening receipt, repair missed Monday evidence, restart a VM service, alter
risk limits, or authorize an order. Deploy only with the existing protected
VM upgrade/backup protocol and independent release review.
