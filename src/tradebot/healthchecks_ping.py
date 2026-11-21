"""Outbound-only Healthchecks.io heartbeat for Tradebot 2.0 protective monitors.

A systemd timer runs this process approximately once per minute. A success
check-in is sent ONLY when both the independent watchdog and read-only equity
collector have fresh, healthy SQLite heartbeats. If the VM/network is lost, or
either monitor is unhealthy, check-ins stop; an EXTERNAL Healthchecks.io check
must be configured by the operator to alert on missing pings.

Never loads Delta API secrets, submits trades, calls AI or mutates SQLite.
An accepted check-in is liveness evidence, NOT trading release authority.
"""
import argparse
import json
import os
from pathlib import Path
import re
from urllib import error, parse, request

from tradebot.equity_monitor import operations_health

_ALLOWED_DOMAINS = frozenset({"hc-ping.com", "hchk.io"})
_SEGMENT = re.compile(r"[A-Za-z0-9_-]{1,128}")


class HeartbeatError(Exception):
    """Sanitized, token-free error code."""

    def __init__(self, code):
        self.code = code
        super().__init__(code)


class _NoRedirects(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise HeartbeatError("external_redirect_refused")


def validate_ping_url(raw):
    """Require the private URL from the user's real Healthchecks.io check."""
    if not isinstance(raw, str) or not 0 < len(raw) <= 512:
        raise HeartbeatError("healthchecks_url_unconfigured")
    try:
        url = parse.urlsplit(raw)
        if (url.scheme != "https"
                or url.hostname not in _ALLOWED_DOMAINS
                or url.username is not None
                or url.password is not None
                or url.port is not None
                or url.query or url.fragment
                or any(ord(c) < 33 or ord(c) > 126 for c in raw)):
            raise HeartbeatError("healthchecks_url_invalid")
    except (ValueError, TypeError):
        raise HeartbeatError("healthchecks_url_invalid") from None
    segments = url.path.strip("/").split("/")
    if len(segments) not in (1, 2) or any(
            _SEGMENT.fullmatch(segment) is None for segment in segments):
        raise HeartbeatError("healthchecks_url_invalid")
    return raw


def monitoring_preflight(data_dir):
    """Read-only; do not interpret stale/future service markers as healthy."""
    root = Path(data_dir)
    path = root / "fire-monitoring.sqlite"
    if (not root.is_dir() or root.is_symlink()
            or not path.is_file() or path.is_symlink()):
        raise HeartbeatError("monitor_evidence_unavailable")
    result = operations_health(path)
    if (result.get("watchdog") != "healthy"
            or result.get("equity_collector") != "healthy"
            or result.get("alert_codes")):
        raise HeartbeatError("protective_monitor_unhealthy")
    return {"watchdog": "healthy", "equity_collector": "healthy"}


def send_ping(url):
    """One no-body HTTPS GET. Never expose token-bearing URL or errors."""
    validate_ping_url(url)
    opener = request.build_opener(_NoRedirects())
    try:
        with opener.open(request.Request(url, method="GET"), timeout=8) as r:
            if r.status != 200 or r.read(32).strip() != b"OK":
                raise HeartbeatError("healthchecks_ack_unverified")
    except HeartbeatError:
        raise
    except (error.HTTPError, error.URLError, TimeoutError,
            OSError, ValueError, TypeError):
        raise HeartbeatError("healthchecks_delivery_unavailable") from None


def run_once(data_dir, url, *, sender=send_ping):
    """Only a local healthy-state snapshot permits one remote check-in."""
    validate_ping_url(url)
    monitoring_preflight(data_dir)
    try:
        sender(url)
    except HeartbeatError:
        raise
    except Exception:
        raise HeartbeatError("healthchecks_delivery_unavailable") from None
    return {"status": "external_heartbeat_accepted_not_trade_authority",
            "watchdog": "healthy", "equity_collector": "healthy",
            "trade_authorized": False, "broker_order_mutations": False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", default="data")
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--check", action="store_true",
                        help="No network, no writes; check URL and local evidence")
    action.add_argument("--ping", action="store_true",
                        help="One network success check-in when monitors healthy")
    args = parser.parse_args(argv)
    try:
        url = validate_ping_url(
            os.environ.get("TRADEBOT_EXTERNAL_HEARTBEAT_URL", ""))
        if args.check:
            health = monitoring_preflight(args.data_dir)
            report = {"status": "healthchecks_ready_for_supervised_ping",
                      **health, "external_delivery_verified": False,
                      "trade_authorized": False}
        else:
            report = run_once(args.data_dir, url)
        print(json.dumps(report, sort_keys=True))
        return 0
    except HeartbeatError as exc:
        print(json.dumps({"status": "healthchecks_ping_blocked",
                          "reason": exc.code, "trade_authorized": False},
                         sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
