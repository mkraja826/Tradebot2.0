"""Free Telegram delivery of sanitized, already-recorded safety incidents.

Uses the existing fire-monitoring.sqlite monitor_events outbox, but stores its
own acknowledgement cursor in fire-telegram-delivery.sqlite. A successful
Telegram sendMessage acknowledgement advances the cursor; failures retry.
Never imports broker credentials, submits orders, or edits equity evidence.

The operator MUST explicitly initialize a baseline to avoid flooding a newly
created bot with historical reminders. The baseline skips historical events,
not current or future safety monitoring; existing active alerts are reported
as a count and can subsequently generate new reminders.
"""
import argparse
from contextlib import closing
import json
import os
from pathlib import Path
import re
import sqlite3
import time
from urllib import error, parse, request

from tradebot.equity_monitor import ALERTS
from tradebot.offhost_alerts import (
    AlertRelayError, _NoRedirects, _cursor_connection, _read_alert_batch,
    EVENT_DB,
)

TELEGRAM_CURSOR_DB = "fire-telegram-delivery.sqlite"
TOKEN_PATTERN = re.compile(r"\d+:[A-Za-z0-9_-]{20,}")
CHAT_PATTERN = re.compile(r"-?\d+")


def valid_credentials(token, chat_id):
    if not isinstance(token, str) or not TOKEN_PATTERN.fullmatch(token):
        raise AlertRelayError("telegram_token_unavailable")
    if not isinstance(chat_id, str) or not CHAT_PATTERN.fullmatch(chat_id):
        raise AlertRelayError("telegram_chat_unavailable")


def _existing_outbox(directory):
    directory = Path(directory)
    path = directory / EVENT_DB
    if not directory.is_dir() or directory.is_symlink():
        raise AlertRelayError("monitor_data_unavailable")
    if not path.is_file() or path.is_symlink():
        raise AlertRelayError("monitor_outbox_unavailable")
    return path


def inspect_outbox(data_dir):
    """Read-only. No network, risk-ledger modification or cursor creation."""
    path = _existing_outbox(data_dir)
    try:
        with closing(sqlite3.connect(
                path.resolve().as_uri() + "?mode=ro", uri=True,
                timeout=2)) as db:
            db.execute("PRAGMA query_only=ON")
            if db.execute("PRAGMA quick_check(1)").fetchone() != ("ok",):
                raise AlertRelayError("monitor_outbox_integrity_failed")
            max_id = db.execute(
                "SELECT COALESCE(MAX(id),0) FROM monitor_events"
            ).fetchone()[0]
            active = db.execute(
                "SELECT code FROM monitor_alert_state WHERE active=1"
            ).fetchall()
            if (type(max_id) is not int or max_id < 0 or
                    any(code not in ALERTS for (code,) in active)):
                raise AlertRelayError("monitor_evidence_unverified")
    except (sqlite3.Error, OSError, TypeError):
        raise AlertRelayError("monitor_outbox_unavailable") from None
    return max_id, len(active)


def telegram_send(token, chat_id, message):
    """One bounded Telegram API call. Never print URL/token/errors upstream."""
    valid_credentials(token, chat_id)
    if not isinstance(message, str) or not 0 < len(message) <= 3500:
        raise AlertRelayError("telegram_message_invalid")
    data = parse.urlencode({"chat_id": chat_id, "text": message,
                            "disable_web_page_preview": "true"}).encode("utf-8")
    uri = "https://api.telegram.org/bot" + token + "/sendMessage"
    req = request.Request(
        uri, data=data, headers={"Content-Type":
                                 "application/x-www-form-urlencoded"},
        method="POST")
    try:
        with request.build_opener(_NoRedirects()).open(req, timeout=8) as r:
            if r.status != 200:
                raise AlertRelayError("telegram_delivery_unacknowledged")
            body = r.read(4097)
            if len(body) > 4096:
                raise AlertRelayError("telegram_response_invalid")
        ack = json.loads(body)
        sent_chat = ack.get("result", {}).get("chat", {}).get("id")
        if (ack.get("ok") is not True or
                type(sent_chat) is not int or sent_chat != int(chat_id)):
            raise AlertRelayError("telegram_delivery_unacknowledged")
    except AlertRelayError:
        raise
    except (error.HTTPError, error.URLError, TimeoutError, OSError,
            ValueError, TypeError, KeyError, AttributeError):
        raise AlertRelayError("telegram_delivery_unavailable") from None


def _message_for(rows):
    """One bounded digest per delivery cycle, avoiding Telegram flood."""
    first, last = rows[0][0], rows[-1][0]
    account = os.environ.get("TRADEBOT_ALERT_ACCOUNT")
    if account not in (None, "", "BTC", "GOLD"):
        raise AlertRelayError("telegram_account_scope_unverified")
    lines = [
        "🚨 Tradebot 2.0 safety events",
        "Environment: Delta India DEMO",
        *((["Isolated subaccount: " + account]) if account else []),
        "Count: " + str(len(rows)),
        "Event IDs: " + str(first) + "–" + str(last),
        "",
    ]
    counts = {}
    for _, _, code, transition, severity in rows:
        key = (code, transition, severity)
        counts[key] = counts.get(key, 0) + 1
    for (code, transition, severity), number in sorted(counts.items()):
        lines.append(
            ("🔴 " if severity == "critical" else
             "⚠️ " if severity == "warning" else "ℹ️ ")
            + code + " — " + transition
            + (" (" + str(number) + "x)" if number != 1 else ""))
    lines += ["", "Alerts only. Trading is NOT authorized by this message."]
    result = "\n".join(lines)
    if len(result) > 3500:
        raise AlertRelayError("telegram_message_invalid")
    return result


def initialize_baseline(data_dir, token, chat_id):
    """Operator-only once. Explicitly skip old incidents; no network calls."""
    valid_credentials(token, chat_id)
    directory = Path(data_dir)
    max_id, active_count = inspect_outbox(directory)
    cursor_path = directory / TELEGRAM_CURSOR_DB
    if cursor_path.exists() or cursor_path.is_symlink():
        raise AlertRelayError("telegram_baseline_already_exists")
    with closing(_cursor_connection(cursor_path)) as db:
        db.execute(
            "UPDATE delivery_cursor SET last_event=? WHERE id=1 AND last_event=0",
            (max_id,))
        db.commit()
    return {"status": "telegram_baseline_initialized",
            "historical_events_skipped": max_id,
            "currently_active_incident_count": active_count,
            "telegram_delivery_commissioned": False,
            "trade_authorized": False}


def deliver_once(data_dir, token, chat_id, *, send=telegram_send):
    valid_credentials(token, chat_id)
    directory = Path(data_dir)
    _existing_outbox(directory)
    cursor_path = directory / TELEGRAM_CURSOR_DB
    if not cursor_path.is_file() or cursor_path.is_symlink():
        raise AlertRelayError("telegram_baseline_required")
    with closing(_cursor_connection(cursor_path)) as db:
        last = db.execute(
            "SELECT last_event FROM delivery_cursor WHERE id=1").fetchone()[0]
        rows = _read_alert_batch(directory / EVENT_DB, last)
        if not rows:
            return {"status": "no_new_telegram_incidents", "events_acked": 0,
                    "trade_authorized": False}
        try:
            send(token, chat_id, _message_for(rows))
        except AlertRelayError:
            raise
        except Exception:
            raise AlertRelayError("telegram_delivery_unavailable") from None
        # An ambiguous upstream timeout means at-least-once replay, NOT loss.
        db.execute(
            "UPDATE delivery_cursor SET last_event=? WHERE id=1 AND last_event=?",
            (rows[-1][0], last))
        db.commit()
    return {"status": "telegram_incident_batch_accepted",
            "events_acked": len(rows), "last_event": rows[-1][0],
            "trade_authorized": False}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--data-dir", default="data")
    actions = p.add_mutually_exclusive_group()
    actions.add_argument("--check", action="store_true",
                         help="Read-only local setup check; NO network")
    actions.add_argument("--baseline", action="store_true",
                         help="One-time opt-in; skip historical outbox events")
    actions.add_argument("--test", action="store_true",
                         help="Send one harmless commissioning test to Telegram")
    actions.add_argument("--once", action="store_true",
                         help="Deliver one outbox batch and exit")
    args = p.parse_args(argv)
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    try:
        valid_credentials(token, chat_id)
        if args.check:
            max_id, count = inspect_outbox(args.data_dir)
            result = {"status": "telegram_configured_not_commissioned",
                      "historical_event_count": max_id,
                      "active_incident_count": count,
                      "telegram_delivery_verified": False,
                      "trade_authorized": False}
        elif args.baseline:
            result = initialize_baseline(args.data_dir, token, chat_id)
        elif args.test:
            inspect_outbox(args.data_dir)
            telegram_send(token, chat_id,
                          "✅ Tradebot 2.0: automated alert relay TEST accepted. "
                          "Delta India DEMO. No trades placed.")
            result = {"status": "telegram_test_accepted",
                      "trade_authorized": False}
        elif args.once:
            result = deliver_once(args.data_dir, token, chat_id)
        else:
            while True:
                try:
                    result = deliver_once(args.data_dir, token, chat_id)
                    if result["events_acked"]:
                        print(json.dumps(result, sort_keys=True), flush=True)
                except AlertRelayError as exc:
                    print(json.dumps({"status": "telegram_relay_blocked",
                                      "reason": exc.code,
                                      "trade_authorized": False}), flush=True)
                time.sleep(60)
        print(json.dumps(result, sort_keys=True))
        return 0
    except AlertRelayError as exc:
        print(json.dumps({"status": "telegram_not_ready",
                          "reason": exc.code,
                          "trade_authorized": False}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
