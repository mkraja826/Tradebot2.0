# One-read Delta India DEMO wallet transport preflight

This is a **diagnostic, not a deployment, collector, financial reconciliation
or trade authorization**. It makes a single authenticated GET request using
the existing `DeltaDemo(allow_orders=False)` client, validates the transport
receipt in memory, then exits without writing any local SQLite, journal,
wallet value, or exchange order.

On an independently reviewed isolated staging checkout, prepare protected
Delta India DEMO credentials using the VM operator's existing approved
environment-loading procedure and keep FIRE disabled. Never paste a
key, balance, request signature or secret to a chat, screenshot or GitHub.

```bash
cd ~/Tradebot2.0-review
.venv/bin/python -m unittest discover \
  -s tests -p 'test_demo_wallet_transport_probe.py' -v
.venv/bin/python -m tradebot.demo_wallet_transport_probe
```

Success: `transport_receipt_verified=true` with exit code **0**.
Failure: `status=unverified` and an allowlisted diagnostic reason with
exit code **2**. The tool prints no net-equity amount and no full receipt
or raw broker exception. Transport checks include original Date/Age headers,
request/receive time, response hash, time delta, cache age, clock boundary,
and scalar equality using the existing `validate_receipt` logic.

**What a pass does NOT prove:** a broker-internal equity valuation timestamp;
authentic opening checkpoint (UTC 00:00–00:05); historical transport
receipts; P&L/funding reconciliation; current entire account flatness;
run-time equity monitor heartbeats; source approval; or permission to FIRE.
All reports permanently include `trade_authorized=false`,
`safe_to_enable_fire=false`, and
`broker_valuation_timestamp_verified=false`. The original six SQLite
databases and the consumed historical Gold lock are never touched.

This is not a migration of the original legacy
`fire-equity-risk.sqlite` database. Do not run the live equity collector
against the old receipts schema or attempt to backdate historical opening
observations. Any additive schema migration, persistent collector service,
restart and live account change still require independent approval,
original-backup verification and an explicit supervised rollout.
