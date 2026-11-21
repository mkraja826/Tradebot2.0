# Off-machine safety alert relay — optional, NOT commissioned

This implementation connects the existing durable `fire-monitoring.sqlite`
`monitor_events` outbox to operator-provided HTTPS receivers. It is strictly
separate from broker access and the protective watchdog. **Installing code does
not mean that any human can receive an alert or that trading is authorized.**

## Two independent external requirements

1. **Incident webhook** — an HTTPS endpoint accepting a JSON POST with only
   `event, environment, id, at_us, code, transition, severity`. The URL may
   contain a private token. Receiver must acknowledge with HTTP 2xx. This
   sender never includes wallet value, trade data, credentials or database
   paths. Events are delivered at-least-once. The receiver must deduplicate
   using the stable `X-Tradebot-Event-ID` header.
2. **External dead-man switch** — a separate HTTPS check-in endpoint which
   actively pages the operator if check-ins STOP. The VM sends a check-in
   approximately once per minute, **only** when the independent watchdog and
   collector heartbeats are fresh and healthy. Configure an external grace
   period (e.g. 3–5 minutes), a real notification contact and escalation.
   An on-VM script cannot detect/notify about its own complete outage.

Do not reuse the same endpoint for both workflows unless the receiver
explicitly supports both POST incident delivery and GET check-in semantics.
Common webhook providers have different JSON schemas, so verify their actual
receiver API before connecting. HTTP 2xx only confirms the receiver accepted a
message, not that a human read or acknowledged the notification.

## Configuration on the production VM

After choosing and configuring the two external services, securely create:

```bash
mkdir -p "$HOME/.config/tradebot2"
chmod 700 "$HOME/.config/tradebot2"
umask 077
# Use your own secret receiver URLs; do not paste them into chat or logs.
# Create ~/.config/tradebot2/alerts.env with your editor, containing:
# TRADEBOT_ALERT_WEBHOOK_URL='https://YOUR-HTTPS-INCIDENT-RECEIVER'
# TRADEBOT_EXTERNAL_HEARTBEAT_URL='https://YOUR-HTTPS-DEADMAN-CHECK-IN'
chmod 600 "$HOME/.config/tradebot2/alerts.env"
```

The two URLs are not provided by Tradebot. The operator must obtain them;
never substitute guessed URLs. Configure external alert routing, email/push
delivery and escalation in the providers' own dashboards.

Run **read-only setup verification** under the protected config:

```bash
set +x
set -a
source "$HOME/.config/tradebot2/alerts.env"
set +a
PYTHONPATH="$HOME/Tradebot2.0/src" \
  "$HOME/Tradebot2.0/.venv/bin/python" -m tradebot.offhost_alerts \
  --data-dir "$HOME/Tradebot2.0/data" --check
```

This uses no network and creates no SQLite cursor file. It returns
`outbound_alerts_configured_not_commissioned`; this is **not** a successful
delivery test. Run the offline `tests/test_offhost_alerts.py` first.

The installer `bash ops/install_offhost_alerts_service.sh` only stages the
systemd unit (it does NOT enable, start or restart any service). It requires
a healthy existing deployment and protected `alerts.env` with 0600 permissions.
A separate operator-supervised step can perform:

```bash
sudo systemctl enable --now tradebot2-offhost-alerts.service
```

This optional service is outbound only; no public VM port or tunnel is needed.

## Commissioning acceptance (must be real, not mocks)

- [ ] Operator confirms test `opened`/reminder/`resolved` notifications
  arrive at an actual off-machine device, with correct severity, no secrets,
  and successful deduplication of repeat event IDs.
- [ ] Operator confirms a genuine external **missing check-in** alarm by
  interrupting check-ins on the remote receiver **without interrupting the
  protective watchdog or equity collector**, then restores/acknowledges it.
  Never disconnect the VM while holding an unprotected open position.
- [ ] Verify the receiver delivery log shows the expected event IDs and
  acknowledgement; confirm persistent delivery cursor in separate
  `fire-alert-delivery.sqlite` and no modification to historical equity rows
  or loss watermark.
- [ ] Ensure no forwarded wallet/account data, webhook secrets, API keys or
  financial details appear in the service journal.
- [ ] Verify callback errors/restarts preserve backlog and produce alerts;
  outgoing timeouts are bounded, responses fail closed, and a stale watchdog
  or collector suppresses external healthy check-ins.
- [ ] Dashboard, independent watchdog and equity collector remain active,
  both BTC/Gold FIRE switches disabled until *all* trading release gates pass.

## Explicit safety limitations

The relay never contacts Delta, creates orders, opens risk-ledger files for
writing or calls an AI model. It reads immutable monitor event rows and owns
only a separate private cursor database for remote delivery acknowledgements.
A successful 2xx event relay or alive check-in is **not** proof of broker SL/TP,
equity checkpoint provenance or market-data validity.

Remote outbound receiver availability, HTTPS endpoint legitimacy, notification
routing and human acknowledgements remain operator responsibilities.
`--check` and the offline fixture suite do not prove a real external
notification worked. Without the two real URLs, the service must remain
unconfigured/not installed.

Complete trading prerequisites remain separate: genuine UTC opening receipts,
BTC history validity, account-wide finance reconciliation and broker-side
protection verification. Historic Gold investigations remain deferred, while
current Gold exposure still counts for admission.
