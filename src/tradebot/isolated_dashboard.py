"""Credential-isolated, broker-signed BTC/Gold read-only dashboard summaries.

The legacy dashboard operates against the original parent account. This module
never reuses that broker identity or those trading ledgers for the autonomous
BTC/GOLD report. No demo order, preview, model API, or POST capability.
"""
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from threading import Lock, Thread
from urllib.parse import quote
import json
import os
import re
import shlex
import sqlite3
import stat
import subprocess
import time

from tradebot.delta import DeltaDemo, DEMO_API
from tradebot.equity_monitor import risk_health
from tradebot.signed_margin_mode import _parent_signed_subaccount_mode, _user_id


ACCOUNTS = {
    "BTC": ("btc-isolated", "BTCUSD", "tb-gpt-6",
            "fire-ops.sqlite", "btc-auto-demo.sqlite", "btc_auto_attempts",
            "btc-auto-demo-halt", "btc-isolated-autonomous-armed"),
    "GOLD": ("gold-isolated", "XAUTUSD", "tb-deepseek-v4-1-flash",
             "fire-xaut.sqlite", "gold-auto-demo.sqlite", "gold_auto_attempts",
             "gold-auto-demo-halt", "gold-isolated-autonomous-armed"),
}
VALID_STATUS = frozenset(("protected_active", "flat_verified", "rejected_no_order",
                          "reasoning", "created", "awaiting_broker", "unknown"))
RECEIPT_FIELDS = ("status", "direction", "contracts", "selected_leverage",
                  "stop_loss", "take_profit", "model", "reason_code",
                  "orders_submitted", "protection_verified",
                  "liquidation_verified", "model_latency_ms")


def _num(value):
    try:
        x = Decimal(str(value))
        return str(x) if x.is_finite() else None
    except (TypeError, ValueError, InvalidOperation):
        return None


def _sqlite(path):
    if not path.is_file() or path.is_symlink():
        raise ValueError("Isolated account ledger unavailable")
    uri = "file:" + quote(str(path.resolve()), safe="/") + "?mode=ro"
    db = sqlite3.connect(uri, uri=True, timeout=1)
    db.execute("PRAGMA query_only=ON")
    return db


def _read_keyfile(path):
    """Return only two expected child credentials, never evaluate shell code."""
    if path.is_symlink() or not path.is_file():
        raise ValueError("Demo child API credentials unavailable")
    m = path.stat()
    if (m.st_uid != os.geteuid() or stat.S_IMODE(m.st_mode) != 0o600
            or m.st_size > 8192):
        raise ValueError("Demo child credential ownership invalid")
    result = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        match = re.fullmatch(
            r'\s*(?:export\s+)?(DELTA_DEMO_API_KEY|DELTA_DEMO_API_SECRET)=(.*)',
            line)
        if match is None:
            continue
        name, raw = match.groups()
        values = shlex.split(raw)
        if name in result or len(values) != 1 or not values[0]:
            raise ValueError("Demo child credential file malformed")
        result[name] = values[0]
    if set(result) != {"DELTA_DEMO_API_KEY", "DELTA_DEMO_API_SECRET"}:
        raise ValueError("Demo child API credentials incomplete")
    return result


def _fire_receipts(root, name):
    outcome = {"total": None, "recent": [], "source": "local_fire_receipts",
               "realized_pnl_verified": False}
    try:
        with _sqlite(root / name) as db:
            outcome["total"] = db.execute(
                "SELECT count(*) FROM fire_requests").fetchone()[0]
            rows = db.execute(
                "SELECT status, result, created_at FROM fire_requests "
                "ORDER BY created_at DESC, rowid DESC LIMIT 8").fetchall()
        for status, raw, at in rows:
            info = json.loads(raw)
            if not isinstance(info, dict):
                raise ValueError("Malformed FIRE receipt")
            selected = {}
            for field in RECEIPT_FIELDS:
                value = info.get(field)
                if isinstance(value, bool) or type(value) in (int, float):
                    selected[field] = value
                elif isinstance(value, str):
                    selected[field] = value[:90]
            selected["status"] = str(status)[:35]
            selected["time"] = str(at)[:40]
            outcome["recent"].append(selected)
    except (OSError, sqlite3.Error, ValueError, TypeError):
        outcome = {"total": None, "recent": [], "source": "unavailable",
                   "realized_pnl_verified": False}
    return outcome


def _attempt_summary(root, name, table):
    try:
        with _sqlite(root / name) as db:
            count = db.execute("SELECT count(*) FROM " + table).fetchone()[0]
            row = db.execute("SELECT status,requested_at FROM " + table
                             + " ORDER BY requested_at DESC LIMIT 1").fetchone()
        return {"total": count,
                "latest_status": str(row[0])[:50] if row else None,
                "last_attempt_utc": datetime.fromtimestamp(
                    row[1], timezone.utc).isoformat() if row else None}
    except (OSError, sqlite3.Error, ValueError, TypeError, OverflowError):
        return {"total": None, "latest_status": None, "last_attempt_utc": None}


def _equity_series(root):
    try:
        with _sqlite(root / "fire-equity-risk.sqlite") as db:
            rows = db.execute(
                "SELECT observed_us,equity_usd FROM equity_evidence "
                "ORDER BY observed_us DESC LIMIT 72").fetchall()
        return [{"at": datetime.fromtimestamp(us / 1e6, timezone.utc).isoformat(),
                 "equity": _num(value)}
                for us, value in reversed(rows) if _num(value) is not None]
    except (OSError, sqlite3.Error, ValueError, TypeError, OverflowError):
        return []


def _service(unit, checker=None):
    if checker is not None:
        return checker(unit) is True
    try:
        return subprocess.run(
            ["systemctl", "is-active", "--quiet", unit + ".service"],
            check=False, timeout=3).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _sanitized_positions(rows, symbol):
    if isinstance(rows, dict):
        rows = [rows]
    if not isinstance(rows, list) or len(rows) > 200:
        raise ValueError("Unverified positions")
    positions = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("Malformed broker position")
        size = _num(row.get("size"))
        if size is None:
            raise ValueError("Unknown signed position quantity")
        if Decimal(size) == 0:
            continue
        # Account IDs, user IDs, broker product names, and other raw fields
        # must never be forwarded to browser clients.
        reported_symbol = row.get("product_symbol")
        shown_symbol = (reported_symbol if reported_symbol in
                        ("BTCUSD", "XAUTUSD") else "OTHER DERIVATIVE")
        positions.append({
            "symbol": shown_symbol, "size": size,
            "side": "LONG" if Decimal(size) > 0 else "SHORT",
            "entry": _num(row.get("entry_price")),
            "unrealized_pnl": _num(row.get("unrealized_pnl")),
        })
    return positions[:10]


class IsolatedAccountsDashboard:
    """Thread-cached read-only broker queries + account-private immutable logs."""

    def __init__(self, data_dir, *, key_dir=None, client_factory=DeltaDemo,
                 credential_loader=_read_keyfile, service_check=None,
                 refresh_seconds=35):
        self.root = Path(data_dir)
        self.keys = Path(key_dir or (Path.home() / ".config/tradebot2"))
        self.client_factory = client_factory
        self.credential_loader = credential_loader
        self.service_check = service_check
        self.refresh_seconds = max(20, int(refresh_seconds))
        self._lock = Lock()
        self._checked = float("-inf")
        self._updating = False
        self._report = {
            "environment": "delta-india-demo",
            "mode": "read_only",
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "source": "isolated_child_accounts",
            "accounts": {label: {"status": "loading"} for label in ACCOUNTS},
            "realized_pnl_verified": False,
        }

    @staticmethod
    def _armed(label, path):
        try:
            if label == "BTC":
                from tradebot.btc_autonomous_demo import is_armed
                return is_armed(path)
            from tradebot.gold_autonomous_demo import is_gold_armed
            return is_gold_armed(path)
        except Exception:
            return False

    def _account(self, label):
        dirname, symbol, model, ledger, attempts_db, attempt_table, halt, arm = ACCOUNTS[label]
        root = self.root / dirname
        if root.is_symlink() or not root.is_dir():
            return {"status": "unavailable", "reason": "account_private_directory_missing"}
        info = {
            "label": label, "symbol": symbol, "model": model,
            "status": "unavailable", "market": "Delta India DEMO",
            "margin_mode": "unverified", "broker_checked_at": None,
            "positions": None, "open_orders": None, "net_equity": None,
            "live_position_count": None,
            "worker_active": _service(
                "tradebot2-" + ("btc" if label == "BTC" else "gold")
                + "-autonomous-demo", self.service_check),
            "watchdog_active": _service(
                "tradebot2-isolated-demo-monitor@" + label + "-watchdog",
                self.service_check),
            "equity_collector_active": _service(
                "tradebot2-isolated-demo-monitor@" + label + "-equity",
                self.service_check),
            "alerts_active": _service(
                "tradebot2-isolated-telegram@" + label, self.service_check),
            "halted": (root / halt).is_file(),
            "armed": self._armed(label, self.keys / arm),
            "fire": _fire_receipts(root, ledger),
            "attempts": _attempt_summary(root, attempts_db, attempt_table),
            "equity_points": _equity_series(root),
            "realized_pnl": None,
            "realized_pnl_verified": False,
            "reconciliation_warning": None,
        }
        try:
            health = risk_health(root / "fire-equity-risk.sqlite")
            info["equity_health"] = {
                k: health.get(k) for k in (
                    "status", "daily_checkpoint", "weekly_checkpoint",
                    "database_integrity", "latest_receipt_status",
                    "observation_status", "latest_observation_age_seconds"
                )}
            monitor = health.get("monitoring") or {}
            info["equity_health"]["monitoring"] = {
                k: monitor.get(k) for k in ("watchdog", "equity_collector")
            }
        except Exception:
            info["equity_health"] = {"status": "unavailable"}
        try:
            child = self.credential_loader(
                self.keys / ("btc-demo-keys.env" if label == "BTC"
                             else "gold-demo-keys.env"))
            broker = self.client_factory(
                api_key=child["DELTA_DEMO_API_KEY"],
                api_secret=child["DELTA_DEMO_API_SECRET"],
                allow_orders=False)
            if (broker.base_url != DEMO_API or broker.allow_orders is not False):
                raise ValueError("Only broker-signed DEMO readonly clients allowed")
            parent_key = os.environ.get("DELTA_DEMO_API_KEY")
            parent_secret = os.environ.get("DELTA_DEMO_API_SECRET")
            if not parent_key or not parent_secret:
                raise ValueError("Signed parent identity not configured")
            parent = self.client_factory(
                api_key=parent_key, api_secret=parent_secret, allow_orders=False)
            if parent.base_url != DEMO_API or parent.allow_orders is not False:
                raise ValueError("Parent broker evidence is not read-only DEMO")
            child_prefs = broker._request(
                "GET", "/v2/users/trading_preferences", auth=True)
            prefs = child_prefs.get("result")
            if not isinstance(prefs, dict):
                raise ValueError("Signed child identity unavailable")
            user = _user_id(prefs.get("user_id"))
            mode = _parent_signed_subaccount_mode(
                user, prefs.get("margin_mode"),
                parent_exchange=parent, expected_label=label)
            if mode != "isolated":
                raise ValueError("Signed isolated margin mode unavailable")
            # Delta requires this signed account-wide inventory endpoint; the
            # product-filtered /v2/positions route cannot prove other exposure.
            positions = broker._request("GET", "/v2/positions/margined", auth=True)
            rows = positions.get("result")
            view = _sanitized_positions(rows, symbol)
            orders = broker.open_orders()
            wallet = broker.wallet_balances()
            net = _num((wallet.get("meta") or {}).get("net_equity"))
            if not isinstance(orders, list) or net is None:
                raise ValueError("Broker orders or net equity unverified")
            info.update({
                "status": "connected", "margin_mode": "isolated_verified",
                "broker_checked_at": datetime.now(timezone.utc).isoformat(),
                "positions": view, "live_position_count": len(view),
                "open_orders": len(orders), "net_equity": net,
            })
            recent = info["fire"]["recent"]
            if recent:
                latest = recent[0]
                if latest.get("status") == "protected_active" and not view:
                    info["reconciliation_warning"] = (
                        "The latest FIRE receipt is protected_active, but "
                        "the signed broker now reports a flat account. "
                        "Final trade settlement needs reconciliation.")
                elif latest.get("status") == "flat_verified" and view:
                    info["reconciliation_warning"] = (
                        "The latest FIRE receipt is flat_verified, but "
                        "the signed broker reports an open position. "
                        "Inspect the watchdog and settlement ledger.")
        except Exception:
            # No stale/raw broker data or credential details exposed on error.
            info["status"] = "broker_unavailable"
            info["margin_mode"] = "unverified"
        return info

    def refresh(self):
        result = {
            "environment": "delta-india-demo", "mode": "read_only",
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "source": "isolated_child_accounts",
            "accounts": {},
            "realized_pnl_verified": False,
        }
        for label in ACCOUNTS:
            try:
                result["accounts"][label] = self._account(label)
            except Exception:
                result["accounts"][label] = {
                    "status": "unavailable",
                    "reason": "isolated_account_snapshot_unavailable",
                }
        with self._lock:
            self._report = result
            self._updating = False
        return result

    def snapshot(self):
        with self._lock:
            if (not self._updating
                    and time.monotonic() - self._checked >= self.refresh_seconds):
                self._checked = time.monotonic()
                self._updating = True
                Thread(target=self.refresh, daemon=True).start()
            return dict(self._report)
