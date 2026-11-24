# BTC and Gold isolated-demo trade collection

This is a **read-only, operator-led** export. There is no fixed collection
deadline and no algorithmic good/bad classification. The owner decides when
enough trades exist and which behaviors to allow or restrict.

## Export any time

From the VM project directory:

```bash
cd /home/support/Tradebot2.0
PYTHONPATH=src .venv/bin/python -m tradebot.isolated_trade_export \
  --data-dir data \
  --output "data/isolated-review-$(date -u +%Y%m%dT%H%M%SZ).csv"
```

`--symbol BTCUSD` or `--symbol XAUTUSD` filters to exactly one
isolated child account; `BOTH` is the default. No shared main-account receipts
are accessed. The export includes every saved attempt, even rejected orders
and unresolved positions. Files are mode 0600 and **never overwritten**,
protecting manual annotations.

The dataset contains identifiers, saved market context and indicator values,
model thesis, proposed quantity/SL/TP, entry fill when known, signed receipt
status, rejection reason, and (when present) the difference between model-time
and signed broker-time entry prices and stop/target reward-to-risk. **A `flat_verified` receipt is not proof of
profitability.** Net P&L and manual review fields are deliberately blank
until reliable reconciliation and the owner's own labels are available.

Exporting never trades, calls an AI model, changes risk controls, clears
worker halts, or alters either ledger. Monitor BTC/Gold autonomous worker
health separately; a running process does not prove orders are executing.

Tests: `PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -p 'test_isolated_trade_export.py' -q`
