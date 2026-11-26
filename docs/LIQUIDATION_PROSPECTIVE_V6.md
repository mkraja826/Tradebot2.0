# Frozen V6 forward-validation protocol

Enrollment: 26 November 2026 14:47 IST (1795684620 UTC epoch seconds),
strictly after the previous exploratory dataset. First 100 observed qualifying
non-overlapping BTC liquidation opportunities, or 30-day enrollment end.
71-minute fixed reservation; no replacement for losses, skips or unknowns.
Matured opportunity must have its full reserved horizon elapsed. No execution.

Primary: V3 continuation retest with fixed initial stop and 2R target.
Reference: V3 direct breakout fixed. Secondary: matched retest immediate
1m/3m EMA9, 1R delayed 1m/3m EMA9, and V5 trend/fee/all confluence.
Use the existing fee and slippage scenarios; separate unknown and no-trade.
Report overall and descriptive regime breakdown, opportunity and trade metrics.
Do not tune on this sample, promote automatically, or claim profitability
from an incomplete sample. Save each report externally and compare enrolled
IDs for historical revisions. Observed archive completeness unverified.

```sh
python -m recover_trading.liquidation_prospective_v6 --market-root /var/lib/recover-trading/demo/BTCUSD --hypotheses-db /var/lib/recover-trading/liquidation-research/hypotheses.sqlite
```

No change to demo engine, services, collectors or MCP registration.
