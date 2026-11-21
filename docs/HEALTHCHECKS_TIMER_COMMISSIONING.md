# Healthchecks.io free external VM-loss monitor — commissioning

Owner-confirmed setup already completed on production VM:
- Healthchecks.io Simple check configured with 1-minute expected period and
  5-minute grace time (the owner must verify check notification contacts).
- Private Ping URL stored as
  `~/.config/tradebot2/healthchecks.env` with mode 0600.
- A real, manually supervised HTTPS GET to the Healthchecks Ping URL returned
  `200 OK` and `OK` body **only after** both watchdog and independent equity
  collector heartbeats were confirmed healthy.
- Independent Telegram incident relay is enabled separately and confirmed
  active; both BTC and Gold new entry FIRE endpoints remain disabled.

**A one-off ping does not constitute automatic outage monitoring**. This
release adds a separate, source-pinned, no-trade systemd oneshot + minute timer.

## Behavior and false positives

- A timer starts the one-shot service ~20 seconds after activation and schedules
  another run ~60 seconds after the previous run has finished. No cloud queue,
  paid API, Docker, cron editor, exchange credentials, AI calls or open VM port.
- The action reads original `data/fire-monitoring.sqlite` in SQLite read-only
  mode through `operations_health`. It refuses missing, symlinked, future,
  stale or otherwise unhealthy watchdog/collector heartbeats.
- ONLY when both service heartbeats are healthy does it issue one HTTP GET
  to the exact operator-supplied, private, HTTPS `hc-ping.com`/`hchk.io` URL,
  with redirects forbidden and an 8-second timeout.
- Any failure sends NO success ping. A complete VM power/network outage also
  stops pings. Healthchecks.io must separately be configured to alert the
  operator on a late/missing ping; a locally scheduled process cannot do so.
- The Healthchecks signal means **VM + watchdog + collector liveness only**,
  NOT that daily/weekly equity checkpoints, historical price data, protective
  order evidence or risk release gates have passed.
- The check code prints only sanitized status codes; it never prints URLs,
  credentials, broker balances or order details.
- The separate Telegram incident relay continues to report the detailed safety
  codes even while Healthchecks sees the host as alive.
- Do not use Healthchecks success/Telegram delivery to enable FIRE, delete the
  Gold lock, backfill lost UTC openings or reset historical peak equity.

## Source-only stage and offline preflight

Check exact merged main CI first. Safely update original VM checkout without
stopping the dashboard, watchdog, collector or Telegram service. With
`PYTHONPATH="$HOME/Tradebot2.0/src"`:

```bash
.venv/bin/python -m unittest discover -s tests -p 'test_healthchecks_ping.py' -q
bash -n ops/run_healthchecks_ping.sh ops/install_healthchecks_ping_timer.sh
```

To check URL plus local monitoring with **no network or database writes**:

```bash
set +x
set -a
source "$HOME/.config/tradebot2/healthchecks.env"
set +a
PYTHONPATH="$HOME/Tradebot2.0/src" \
  "$HOME/Tradebot2.0/.venv/bin/python" -m tradebot.healthchecks_ping \
  --data-dir "$HOME/Tradebot2.0/data" --check
```

Expected `healthchecks_ready_for_supervised_ping`. The operator already
observed the existing one-off real Healthchecks ping; test success must still
be verified after timer commissioning.

Stage the two systemd units WITHOUT activating either:

```bash
cd "$HOME/Tradebot2.0"
bash ops/install_healthchecks_ping_timer.sh
systemctl cat tradebot2-healthchecks-ping.service
systemctl cat tradebot2-healthchecks-ping.timer
```

The installer refuses inactive protective/Telegram services or any mismatch
between production checkout and protected service WorkingDirectory; it does
not edit SQLite, service unit files for the existing bot, or protected keys.

## Supervised activation and REAL off-host verification

Only after exact source/health/BTC+Gold FIRE-disable checks:

```bash
sudo systemctl enable --now tradebot2-healthchecks-ping.timer
systemctl is-active tradebot2-healthchecks-ping.timer
systemctl list-timers tradebot2-healthchecks-ping.timer --no-pager
```

Observe at least three acknowledged consecutive pings with approximately
one-minute spacing in the **external Healthchecks.io dashboard** and journal
(which must never show the token-bearing URL). The timer itself is active
while the one-shot service is ordinarily inactive between pings.

Confirm a real email or Telegram notification contact in Healthchecks.io,
then test a missing-check-in alarm remotely **without** stopping protective
watchdog or collector. Use the provider's test notification feature or
temporarily stop ONLY the Healthchecks timer while flat and both FIRE disabled:

```bash
sudo systemctl stop tradebot2-healthchecks-ping.timer
# Confirm external check alerts after period+grace, then resume:
sudo systemctl start tradebot2-healthchecks-ping.timer
```

The operator must actually receive and acknowledge the remote alert before
the external outage-monitoring requirement can be called commissioned.
Stopping the timer for this test can trigger a real alert; warn the operator
before conducting it. The user must not stop the VM, watchdog, equity collector
or dashboard for this test, and must not perform it during broker exposure.

## Safe status checks

```bash
systemctl is-active tradebot2-healthchecks-ping.timer
systemctl list-timers tradebot2-healthchecks-ping.timer --no-pager
sudo journalctl -u tradebot2-healthchecks-ping.service -n 12 --no-pager
```

Failure of a one-shot ping doesn't modify FIRE flags or stop the watchdog;
the external receiver will detect missed pings. Disabling the timer means
Healthchecks will eventually mark the check Down.

**Final trading no-go gates remain** genuine UTC daily/Monday opening receipts,
BTC anomalous candles/provenance, finance reconciliation, and actual Delta India
DEMO protective bracket semantics verification. Historical Gold investigation
is deferred, while current Gold exposure is always considered.
