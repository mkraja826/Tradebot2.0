# Local dashboard

Run: python -m recover_trading.dashboard --data-dir data/recover-service

Open http://127.0.0.1:8765 locally, or forward the port over SSH. The server
binds loopback only and is read-only; do not expose it publicly without an
authenticated HTTPS reverse proxy. No API keys, raw decision context or order
mutation endpoints are served. Preview and demo worker heartbeat files update
atomically. The UI refreshes every 10 seconds; stale observations are labeled.
Price charts use stored 5-minute closes; wallet charts use a single observed
asset, not cross-currency totals or equity. Wallet balance and margin are
recorded by lifecycle refresh. Actual P&L attribution and win rate remain
unavailable, rather than being invented from order counts or cumulative fills.
No new trading admission restrictions or strategy changes. No deployment.
