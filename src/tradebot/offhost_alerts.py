"""Outbound-only, non-trading bridge for durable safety alerts and VM-loss checks.

The collector writes sanitized events to fire-monitoring.sqlite. This optional
process forwards those exact event codes to an operator-configured HTTPS webhook,
recording acknowledged IDs separately. It sends an external "alive" check-in
ONLY when independent local watchdog AND collector heartbeat evidence is fresh.

Never place orders, read broker credentials, send equity/PII, or edit risk data.
The external receiver must be configured/commissioned by the operator; this
code alone does not constitute off-machine alert readiness.
"""
import argparse
from contextlib import closing
from datetime import datetime, timezone
import ipaddress
import json
import os
from pathlib import Path
import sqlite3
import time
from urllib import error, parse, request

from tradebot.equity_monitor import ALERTS, operations_health

EVENT_DB = "fire-monitoring.sqlite"
CURSOR_DB = "fire-alert-delivery.sqlite"
ALLOWED_TRANSITIONS = {"opened", "reminder", "resolved"}
ALLOWED_SEVERITIES = {"critical", "warning", "info"}
_MAX_BATCH = 40


class AlertRelayError(Exception):
    """Sanitized, bounded failure reason. No endpoint URL or broker data."""

    def __init__(self, code):
        self.code = code
        super().__init__(code)


def validate_https_destination(value):
    """Permit a configured public HTTPS destination, not localhost/metadata."""
    if not isinstance(value, str) or not value or len(value) > 2048:
        raise AlertRelayError("external_endpoint_unconfigured")
    try:
        url = parse.urlsplit(value)
        port = url.port
        hostname = url.hostname
    except (ValueError, TypeError):
        raise AlertRelayError("external_endpoint_invalid") from None
    if (url.scheme != "https" or not hostname or url.username is not None
            or url.password is not None or url.fragment or port == 0
            or any(ord(ch) < 33 for ch in value)):
        raise AlertRelayError("external_endpoint_invalid")
    domain = hostname.lower().rstrip(".")
    if domain in {"localhost", "metadata.google.internal"} or domain.endswith(
            (".local", ".localhost", ".internal", ".test", ".invalid")):
        raise AlertRelayError("external_endpoint_not_public")
    try:
        address = ipaddress.ip_address(domain)
    except ValueError:
        if "." not in domain:
            raise AlertRelayError("external_endpoint_not_public") from None
    else:
        if not address.is_global:
            raise AlertRelayError("external_endpoint_not_public")
    return value


class _NoRedirects(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise AlertRelayError("external_redirect_refused")


def https_send(url, data=None, *, event_id=None):
    """Bounded HTTPS call; redirects are forbidden and raw errors are hidden."""
    validate_https_destination(url)
    headers = {"User-Agent": "Tradebot2-MonitorRelay/1"}
    if data is not None:
        headers["Content-Type"] = "application/json"
        headers["X-Tradebot-Event-ID"] = str(event_id)
    req = request.Request(url, data=data, headers=headers,
                          method="POST" if data is not None else "GET")
    opener = request.build_opener(_NoRedirects())
    try:
        with opener.open(req, timeout=5) as response:
            if not 200 <= response.status < 300:
                raise AlertRelayError("external_delivery_unacknowledged")
    except AlertRelayError:
        raise
    except (error.HTTPError, error.URLError, TimeoutError, OSError, ValueError):
        raise AlertRelayError("external_delivery_unavailable") from None


def _read_alert_batch(path, after):
    if not path.is_file() or path.is_symlink():
        raise AlertRelayError("monitor_outbox_unavailable")
    try:
        with closing(sqlite3.connect(
                path.resolve().as_uri() + "?mode=ro", uri=True,
                timeout=1)) as db:
            db.execute("PRAGMA query_only=ON")
            if db.execute("PRAGMA quick_check(1)").fetchone() != ("ok",):
                raise AlertRelayError("monitor_outbox_integrity_failed")
            rows = db.execute(
                "SELECT id,at_us,code,transition,severity FROM monitor_events "
                "WHERE id>? ORDER BY id ASC LIMIT ?", (after, _MAX_BATCH)
            ).fetchall()
    except (sqlite3.Error, OSError, TypeError):
        raise AlertRelayError("monitor_outbox_unavailable") from None
    for identity, timestamp, code, transition, severity in rows:
        if (type(identity) is not int or identity <= after
                or type(timestamp) is not int or timestamp <= 0
                or code not in ALERTS or transition not in ALLOWED_TRANSITIONS
                or severity not in ALLOWED_SEVERITIES):
            raise AlertRelayError("monitor_event_not_verified")
        after = identity
    return rows


def _cursor_connection(path):
    if not path.parent.is_dir() or path.parent.is_symlink():
        raise AlertRelayError("delivery_state_directory_unavailable")
    if path.is_symlink():
        raise AlertRelayError("delivery_state_symlink_refused")
    flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags, 0o600)
        os.close(fd)
        os.chmod(path, 0o600)
        connection = sqlite3.connect(path, timeout=2)
        connection.execute("CREATE TABLE IF NOT EXISTS delivery_cursor("
                           "id INTEGER PRIMARY KEY CHECK(id=1), "
                           "last_event INTEGER NOT NULL CHECK(last_event>=0), "
                           "last_ping_us INTEGER NOT NULL CHECK(last_ping_us>=0))")
        connection.execute("INSERT OR IGNORE INTO delivery_cursor VALUES (1,0,0)")
        connection.commit()
        return connection
    except (sqlite3.Error, OSError, ValueError):
        raise AlertRelayError("delivery_state_unavailable") from None


def deliver_once(data_dir, webhook, heartbeat_url, *, send=https_send,
                 now=None):
    """Send a bounded batch; at-least-once with stable receiver event IDs.

    Separate delivery cursor is used to avoid writes to safety-monitoring or
    immutable equity databases. Never advance cursor before remote 2xx.
    """
    validate_https_destination(webhook)
    validate_https_destination(heartbeat_url)
    directory = Path(data_dir)
    if not directory.is_dir() or directory.is_symlink():
        raise AlertRelayError("monitor_data_unavailable")
    now_us = int((now or datetime.now(timezone.utc)).timestamp() * 1_000_000)
    sent = 0
    with closing(_cursor_connection(directory / CURSOR_DB)) as cursor:
        last_event, last_ping = cursor.execute(
            "SELECT last_event,last_ping_us FROM delivery_cursor WHERE id=1"
        ).fetchone()
        rows = _read_alert_batch(directory / EVENT_DB, last_event)
        for identity, at_us, code, transition, severity in rows:
            payload = json.dumps({
                "event": "tradebot2_monitor_alert",
                "environment": "delta-india-demo",
                "id": identity,
                "at_us": at_us,
                "code": code,
                "transition": transition,
                "severity": severity,
            }, separators=(",", ":"), allow_nan=False).encode("ascii")
            try:
                send(webhook, payload, event_id=identity)
            except AlertRelayError:
                raise
            except Exception:
                raise AlertRelayError("external_delivery_unavailable") from None
            cursor.execute(
                "UPDATE delivery_cursor SET last_event=? WHERE id=1 AND last_event<?",
                (identity, identity)
            )
            cursor.commit()
            sent += 1
        # A healthy check-in from THIS VM must not hide a dead watchdog or
        # collector. If either local heartbeat is unverified, withhold ping
        # and let the independent external service notify the operator.
        health = operations_health(directory / EVENT_DB,
                                   at=datetime.fromtimestamp(now_us/1_000_000,
                                                             timezone.utc))
        healthy = (health.get("watchdog") == "healthy"
                   and health.get("equity_collector") == "healthy"
                   and not health.get("alert_codes"))
        pinged = False
        if healthy and now_us - last_ping >= 60_000_000:
            try:
                send(heartbeat_url)
            except AlertRelayError:
                raise
            except Exception:
                raise AlertRelayError("external_delivery_unavailable") from None
            cursor.execute(
                "UPDATE delivery_cursor SET last_ping_us=? WHERE id=1",
                (now_us,)
            )
            cursor.commit()
            pinged = True
    return {"status": "delivery_cycle_completed_not_trade_authority",
            "events_acked": sent, "healthy_ping_acked": pinged,
            "local_monitors_healthy": healthy,
            "trade_authorized": False, "broker_order_mutations": False}


def check_only(data_dir, webhook, heartbeat_url):
    """No network and no writes. Confirm configuration and local evidence."""
    validate_https_destination(webhook)
    validate_https_destination(heartbeat_url)
    path = Path(data_dir) / EVENT_DB
    if not path.is_file() or path.is_symlink():
        raise AlertRelayError("monitor_outbox_unavailable")
    status = operations_health(path)
    return {"status": "outbound_alerts_configured_not_commissioned",
            "watchdog": status["watchdog"],
            "equity_collector": status["equity_collector"],
            "external_delivery_verified": False,
            "external_vm_loss_detection_verified": False,
            "trade_authorized": False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--check", action="store_true",
                        help="No network, no new database or cursor writes")
    parser.add_argument("--once", action="store_true",
                        help="One bounded delivery attempt only")
    args = parser.parse_args(argv)
    webhook = os.environ.get("TRADEBOT_ALERT_WEBHOOK_URL", "")
    heartbeat = os.environ.get("TRADEBOT_EXTERNAL_HEARTBEAT_URL", "")
    if args.check:
        try:
            print(json.dumps(check_only(args.data_dir, webhook, heartbeat),
                             sort_keys=True))
            return 0
        except AlertRelayError as exc:
            print(json.dumps({"status": "unverified",
                              "reason": exc.code, "trade_authorized": False}))
            return 2
    while True:
        try:
            result = deliver_once(args.data_dir, webhook, heartbeat)
            print(json.dumps(result, sort_keys=True), flush=True)
        except AlertRelayError as exc:
            print(json.dumps({"status": "delivery_blocked",
                              "reason": exc.code,
                              "trade_authorized": False}), flush=True)
            if args.once:
                return 2
        if args.once:
            return 0
        time.sleep(60)


if __name__ == "__main__":
    raise SystemExit(main())
