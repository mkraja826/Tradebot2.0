# Supervised BTC pilot — unified GET-only admission preflight

This consolidates the existing read-only supervised session candidate (PR #50),
signed account-scoped isolated margin, full-account exposure and the original
BTC six required local archive periods into one bounded source-only report.

It is an **operator diagnostic, not a one-shot trading controller**. It always
exits code 2 and never places an order, sends a paid-model request, edits
historical prices, changes leverage, creates/overwrites a ledger, turns on
FIRE, or restarts the independently running protective watchdog.

On the previously approved VM, after staging the merged source in the
**separate** `~/Tradebot2.0-release-stage` checkout:

```bash
set +x
set -a
source "$HOME/.config/tradebot2/keys.env"
set +a
PYTHONPATH="$HOME/Tradebot2.0-release-stage/src" PYTHONDONTWRITEBYTECODE=1 \
"$HOME/Tradebot2.0/.venv/bin/python" \
-m tradebot.btc_supervised_pilot_gates \
--data-dir "$HOME/Tradebot2.0/data"
```

The output intentionally reveals only categorical evidence and no equity,
account ID, API key, order ID, wallet records, ticker price, or historical
OHLCV. Market quality is read using the existing exact six-period check
against the original SQLite DB in **mode=ro**. Gold historical candle
completeness is *not* an unrelated BTC trading-data prerequisite; Gold
positions, outstanding account orders and signed margin remain account-wide
gates.

A complete six-period local historical status is **not** independently
authenticated perpetual trade-price provenance. The report therefore has
`independent_btc_trade_price_verification:false` even when all six locally
provisional periods pass.

If every category passes, the report says
`candidate_checks_passed_not_release_authority`, yet STILL requires a
durable one-attempt controller, independent signed protection/liquidation
evidence, session rechecks at every broker mutation, independent review and
an explicit operator signoff for supervised DEMO execution.

Current original-VM evidence: session equity checks agreed at 0% drawdown
in two fresh authenticated reads, but Main-account isolated margin returned
`signed_account_identity_not_unique` and BTC historic months were
suspicious. The preflight must not convert either into success. The ordinary
week-anchored FIRE controller remains untouched and explicitly disabled.
