# Free Telegram safety alert commissioning — Delta DEMO

The owner has already created a Telegram bot, allowed bot messages to the
private chat, saved the token and Chat ID privately on the Google Cloud VM at
`$HOME/.config/tradebot2/telegram.env`, and confirmed a real test message
arrived on the phone. This does **not** mean automatic incident delivery is
commissioned: existing incident messages are still only in the local SQLite
outbox until the relay process is running.

This source is separate from the pending generic offhost webhook/Healthchecks
implementation. **No Pipedream or paid notification subscription is required.**
Telegram delivery of incidents is free for ordinary bot usage, but is not a
substitute for independent outage monitoring (the VM cannot report its own
power loss). A free independent dead-man/check-in monitor still needs setup.

## Privacy and security

- No token, Chat ID or secret URL in GitHub, SSH history, screenshots, logs
  or assistant messages. Token and chat ID stay in private `telegram.env`
  with mode 0600, sourced only by the independent relay service.
- No Delta credentials, GPT model API, order placement or risk evidence writes.
- Every message contains only enumerated safety event codes, transitions and
  severity — no wallet, positions, API keys, order IDs or financial details.
- Each digest groups at most 40 previously recorded events into **one**
  Telegram message per minute. It advances its private cursor only after
  Telegram acknowledges the intended Chat ID; ambiguous timeouts retry.
- The original `fire-monitoring.sqlite` is read-only to this relay. The
  relay may create only `fire-telegram-delivery.sqlite` to track its
  explicitly initialized progress.
- The relay does not allow entering new FIRE orders, resetting equity,
  touching the Gold lock or installing new broker services.

## Guarded staging

After exact main CI passes, update source on the original VM **without**
restarting dashboard, watchdog or collector. Run:

```bash
.venv/bin/python -m unittest discover -s tests -p 'test_telegram_alerts.py' -q
bash -n ops/run_telegram_alerts.sh ops/install_telegram_alerts_service.sh
```

Read-only check (no network or cursor creation):

```bash
set -a
source "$HOME/.config/tradebot2/telegram.env"
set +a
export PYTHONPATH="$HOME/Tradebot2.0/src"
"$HOME/Tradebot2.0/.venv/bin/python" -m tradebot.telegram_alerts \
  --data-dir "$HOME/Tradebot2.0/data" --check
```

## Explicit one-time baseline (operator supervised)

The existing monitor outbox has historical recurring incidents. A new bot
must not send hundreds of stale alerts. The operator explicitly establishes
a private delivery cursor at the latest recorded event ID:

```bash
"$HOME/Tradebot2.0/.venv/bin/python" -m tradebot.telegram_alerts \
  --data-dir "$HOME/Tradebot2.0/data" --baseline
```

This sends NO Telegram messages and intentionally **skips events recorded
before commissioning**. It reports the total number skipped and a count of
currently active incident codes. Read active incidents separately; they are
not resolved or hidden by the baseline. Future new reminders/recoveries will
be delivered. Do not run baseline again after starting; it refuses
overwrites. If a recovery problem exists, investigate it before enabling
trades; do not treat baseline as evidence repair.

## Real relay test and service staging

Send a relay-specific test message from the actual VM without editing any
monitor or risk database:

```bash
"$HOME/Tradebot2.0/.venv/bin/python" -m tradebot.telegram_alerts \
  --data-dir "$HOME/Tradebot2.0/data" --test
```

The owner must confirm this second message arrived. Then stage the unit:

```bash
bash ops/install_telegram_alerts_service.sh
```

The installer deliberately does NOT start, enable or restart any process.
In a separate supervised commissioning step after checking all protective
services and FIRE-disabled endpoints, the operator may activate:

```bash
sudo systemctl enable --now tradebot2-telegram-alerts.service
```

Confirm it is active, sends newly generated synthetic test data **only in an
isolated test SQLite file** (never inject fake incidents into the original
monitor DB), and forwards genuine new events from the live outbox when they
occur. A real `--test` message verifies Telegram connectivity, not yet
continuous incident detection or message delivery during faults.

## Remaining blockers for unattended trading

An on-VM Telegram relay cannot send messages when the entire VM is down.
Commission a separate, free off-machine missing-check-in provider to alert
the operator when VM pings stop. Also verify genuine UTC daily and Monday
weekly first-five-minute equity opening observations; clear BTC suspicious
candles and financial reconciliation; validate Delta DEMO protective bracket
orders before the first supervised BTC test trade. FIRE remains disabled.

Historical Gold deep-dive investigation remains deferred; current broker
Gold exposure must be counted in any new trade admission.
