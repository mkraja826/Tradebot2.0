"""Read-only, loopback-only BTC demo monitoring dashboard.

No order endpoints or API credentials are ever returned. Bind restricted to
127.0.0.1 by design; access from a different device requires a separately
configured authenticated tunnel/reverse proxy.
"""
import argparse
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
import json
import os
import re
from pathlib import Path
import sqlite3
from threading import Event, Lock, Thread
import time
from urllib.parse import parse_qs, quote, urlsplit

from tradebot.candle_archive import CandleArchive
from tradebot.chart_desk import ChartDesk
from tradebot.delta import DeltaDemo
from tradebot.fire_dashboard import FirePreviewController
from tradebot.fire_execution import FireDemoController
from tradebot.equity_monitor import risk_health
from tradebot.isolated_dashboard import IsolatedAccountsDashboard
from tradebot.fire_probe import load_snapshot
from tradebot.trade_memory import public_learning_summary
from tradebot.market import _age_seconds, _candles, MarketDataError

SAFE_EVENT_FIELDS = frozenset({
    "mode", "strategy", "rationale", "model", "phase", "product_id",
    "side", "size", "contracts", "attempt", "attempts", "count", "at",
    "reason", "error", "error_type", "orders_submitted", "legs",
    "ai_tokens", "message", "decision_id", "order_id", "spread",
    "finish_reason", "content_chars",
})
ASSET_TYPES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/styles.css": ("styles.css", "text/css; charset=utf-8"),
    "/charts.js": ("charts.js", "text/javascript; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/isolated.js": ("isolated.js", "text/javascript; charset=utf-8"),
}


def _utc_now():
    return datetime.now(timezone.utc)


def _iso_age(raw, *, now=None):
    try:
        at = datetime.fromisoformat(raw)
        if at.tzinfo is None:
            return None
        return max(0, (_utc_now() if now is None else now).timestamp() -
                   at.timestamp())
    except (ValueError, TypeError):
        return None


def _safe_decimal(value):
    try:
        num = Decimal(str(value))
        if num.is_finite():
            return str(num)
    except (InvalidOperation, TypeError, ValueError):
        pass
    return None


def _load_json(path: Path):
    try:
        if not path.is_file() or path.stat().st_size > 1_000_000:
            return None
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError):
        return None


def _events(path: Path, limit: int = 70):
    try:
        if not path.is_file():
            return []
        # Bounded tail: do not read an unbounded journal into RAM.
        with path.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            end = handle.tell()
            handle.seek(max(0, end - 250_000))
            raw = handle.read()
        if end > len(raw):
            raw = raw.split(b"\n", 1)[-1]
        result = []
        for line in raw.splitlines()[-250:]:
            try:
                item = json.loads(line)
                kind = item.get("kind")
                details = item.get("details") or {}
                if not isinstance(kind, str) or not isinstance(details, dict):
                    continue
                selected = {k: v for k, v in details.items()
                            if k in SAFE_EVENT_FIELDS and
                            isinstance(v, (str, int, float, bool, list, dict))
                            and len(json.dumps(v, default=str)) <= 1200}
                result.append({
                    "time": str(item.get("at_utc") or "")[:35],
                    "kind": kind[:80],
                    "details": selected,
                })
            except (ValueError, TypeError):
                continue
        return result[-limit:][::-1]
    except OSError:
        return []


def _ledger(path: Path):
    result = {
        "confirmed_btc_fills": 0,
        "fees_by_asset": {},
        "equity_points": [],
        "is_realized_pnl": False,
        "ledger_present": path.exists(),
    }
    if not path.is_file():
        return result
    uri = "file:" + quote(str(path.resolve()), safe="/") + "?mode=ro"
    try:
        with sqlite3.connect(uri, uri=True, timeout=1) as db:
            rows = db.execute("SELECT commission, settling_asset FROM fills").fetchall()
            fees = {}
            for commission, asset in rows:
                parsed = _safe_decimal(commission)
                if parsed is None or not isinstance(asset, str):
                    continue
                fees[asset] = fees.get(asset, Decimal("0")) + Decimal(parsed)
            result["confirmed_btc_fills"] = len(rows)
            result["fees_by_asset"] = {k: str(v) for k, v in fees.items()}
            points = db.execute(
                "SELECT captured_at, net_equity FROM equity_snapshots "
                "ORDER BY captured_at DESC LIMIT 60"
            ).fetchall()
            result["equity_points"] = [
                {"at": str(at), "equity": value}
                for at, raw in reversed(points)
                if (value := _safe_decimal(raw)) is not None
            ]
            result["fills"] = [
                dict(zip(("time_ms", "symbol", "side", "size", "price", "fee", "asset", "order_id", "id"), row))
                for row in db.execute("SELECT at_us / 1000, symbol, side, size, price, commission, "
                                      "settling_asset, order_id, id FROM fills ORDER BY at_us DESC, id DESC LIMIT 160")
            ]
    except (sqlite3.Error, OSError):
        result["ledger_error"] = "Ledger unavailable or not yet initialized"
    return result


def _runtime(path: Path):
    raw = _load_json(path)
    if not isinstance(raw, dict):
        return {"status": "not_started", "age_seconds": None,
                "mode": "unknown", "action": "No heartbeat"}
    age = _iso_age(raw.get("updated_at"))
    action = raw.get("action") if isinstance(raw.get("action"), str) else "unknown"
    mode = raw.get("mode") if raw.get("mode") in ("observe", "demo") else "unknown"
    schedule = raw.get("schedule") if raw.get("schedule") in (
        "nyse", "nyse-cash-observe", "crypto-24x7") else "unknown"
    status = "stopped" if action == "stopped" else (
        "running" if age is not None and age <= 180 else "stale"
    )
    return {
        "status": status, "age_seconds": round(age, 1) if age is not None else None,
        "mode": mode, "schedule": schedule, "action": action[:80],
        "next_scan": raw.get("next_scan"), "exit_due": raw.get("exit_due"),
        "updated_at": str(raw.get("updated_at") or "")[:35],
    }


def _cashflows(rows):
    """Signed posted wallet amounts per asset; exclude deposits and transfers."""
    groups = {"cashflow": "cashflow", "settlement": "cashflow",
              "funding": "funding", "commission": "fees",
              "liquidation_fee": "fees", "commission_rebate": "fees"}
    totals = {}
    for row in rows:
        group = groups.get(row["transaction_type"])
        if group is None:
            continue
        asset, amount = row.get("asset_symbol"), _safe_decimal(row.get("amount"))
        if not isinstance(asset, str) or not asset or amount is None:
            raise ValueError("Incomplete settlement data")
        parts = totals.setdefault(asset, dict.fromkeys(("cashflow", "funding", "fees"), Decimal(0)))
        parts[group] += Decimal(amount)
    return {asset: {k: str(v) for k, v in dict(parts, net=sum(parts.values())).items()}
            for asset, parts in totals.items()}


class DashboardData:
    def __init__(self, data_dir=None, exchange=None, refresh_seconds=20):
        self.root = Path(data_dir or os.getenv("TRADEBOT_DASHBOARD_DATA", "data")).resolve()
        self.fire_preview = FirePreviewController()
        self.fire_trade = FireDemoController(
            self.root / "fire-ops.sqlite",
            enabled=os.getenv("TRADEBOT_FIRE_DEMO_EXECUTION", "false") == "true",
        )
        self.isolated_accounts = IsolatedAccountsDashboard(self.root)
        self.gold_preview = FirePreviewController(snapshot_loader=lambda: load_snapshot("XAUTUSD"))
        self.gold_trade = FireDemoController(
            self.root / "fire-xaut.sqlite", symbol="XAUTUSD",
            enabled=self.fire_trade.enabled,
        )
        self.exchange = exchange or DeltaDemo(
            api_key=os.getenv("DELTA_DEMO_API_KEY", ""),
            api_secret=os.getenv("DELTA_DEMO_API_SECRET", ""),
            allow_orders=False,
        )
        self.chart_desk = ChartDesk(self.exchange, {"BTCUSD": self.fire_trade.store, "XAUTUSD": self.gold_trade.store})
        self.refresh_seconds = max(10, int(refresh_seconds))
        self._lock = Lock()
        self._history_lock = Lock()
        self._history = {}
        self._performance_checked = float("-inf")
        self._performance = None
        self._recent_fills = []
        self._fills_checked = float("-inf")
        self._started_at = 0.0
        self._updating = False
        self._live = {
            "checked_at": None, "market": {"status": "waiting"},
            "account": {"status": "waiting"},
        }

    def _load_remote(self):
        payload = {
            "checked_at": _utc_now().isoformat(),
            "market": {"status": "unavailable"},
            "account": {"status": "unavailable"},
        }
        try:
            ticker = self.exchange.ticker("BTCUSD")
            quotes = ticker.get("quotes") or {}
            if not isinstance(quotes, dict):
                quotes = {}
            age = _age_seconds(ticker.get("timestamp"), _utc_now())
            bid = _safe_decimal(quotes.get("best_bid"))
            ask = _safe_decimal(quotes.get("best_ask"))
            mark = _safe_decimal(ticker.get("mark_price"))
            if (age <= 60 and bid is not None and ask is not None and
                    Decimal(bid) > 0 and Decimal(ask) > Decimal(bid)):
                payload["market"] = {
                    "status": "fresh", "symbol": "BTCUSD", "bid": bid,
                    "ask": ask, "mark": mark, "age_seconds": round(age, 1),
                }
            else:
                payload["market"] = {"status": "stale_or_unquotable"}
        except (Exception):
            # Never serialize HTTP response bodies, auth errors or credentials.
            payload["market"] = {"status": "unavailable"}
        try:
            if not self.exchange.api_key or not self.exchange.api_secret:
                raise ValueError("Read-only credentials not configured")
            positions = self.exchange.btc_positions()
            orders = self.exchange.open_orders()
            wallet = self.exchange.wallet_balances()
            if not isinstance(positions, list) or not isinstance(orders, list):
                raise ValueError("Malformed account state")
            active = []
            for row in positions:
                if not isinstance(row, dict):
                    raise ValueError("Malformed position")
                size = _safe_decimal(row.get("size"))
                if size is None:
                    raise ValueError("Invalid position size")
                if Decimal(size) != 0:
                    active.append({
                        "symbol": str(row.get("product_symbol") or "BTC derivative")[:70],
                        "size": size, "entry": _safe_decimal(row.get("entry_price")),
                    })
            meta = wallet.get("meta") or {}
            payload["account"] = {
                "status": "connected", "positions": active[:30],
                "btc_open_positions": len(active),
                "account_open_orders": len(orders),
                "net_equity": _safe_decimal(meta.get("net_equity")),
            }
        except (Exception):
            payload["account"] = {"status": "unavailable"}
        now = _utc_now()
        try:
            end = int(now.timestamp())
            rows = self.exchange.candles(start=end - 7200, end=end)
            payload["candles"] = _candles(rows, now)["last_24"]
        except Exception:
            payload["candles"] = []
        if time.monotonic() - self._fills_checked >= 60:
            try:
                end_us = int(now.timestamp() * 1_000_000)
                rows = self.exchange.btc_fills(start_time_us=end_us - 86_400_000_000,
                                               end_time_us=end_us)
                self._recent_fills = [{
                    "time_ms": int(f["created_at"]) // 1000, "symbol": f["product_symbol"],
                    "side": f["side"], "size": _safe_decimal(f["size"]),
                    "price": _safe_decimal(f["price"]), "fee": _safe_decimal(f["commission"]),
                    "asset": f["settling_asset_symbol"], "order_id": str(f.get("order_id") or ""),
                    "id": str(f["id"]),
                } for f in sorted(rows, key=lambda f: int(f["created_at"]), reverse=True)[:160]]
            except Exception:
                self._recent_fills = None
            self._fills_checked = time.monotonic()
        payload["recent_fills"] = self._recent_fills
        if time.monotonic() - self._performance_checked >= 300:
            try:
                end_us = int(now.timestamp() * 1_000_000)
                rows = self.exchange.wallet_postings(end_us - 86_400_000_000, end_us)
                self._performance = {"at": now.isoformat(), "assets": _cashflows(rows)}
            except Exception:
                self._performance = None
            self._performance_checked = time.monotonic()
        payload["performance"] = self._performance
        with self._lock:
            self._live = payload
            self._updating = False

    def historical_bars(self, at):
        """Two hours around a selected journal event, cached by five-minute bucket."""
        end = min(int(_utc_now().timestamp()), (at // 300 + 4) * 300)
        if at < 1 or at > int(_utc_now().timestamp()) + 60:
            raise ValueError("Invalid inspection time")
        with self._history_lock:
            if end not in self._history:
                rows = self.exchange.candles(start=end - 7200, end=end)
                bars = _candles(rows, datetime.fromtimestamp(end, timezone.utc))["last_24"]
                if len(self._history) >= 16:
                    del self._history[next(iter(self._history))]
                self._history[end] = bars
            return self._history[end]

    def snapshot(self):
        now = time.monotonic()
        with self._lock:
            if (not self._updating and
                    now - self._started_at >= self.refresh_seconds):
                self._updating = True
                self._started_at = now
                Thread(target=self._load_remote, daemon=True).start()
            live = dict(self._live)
        runtime = _runtime(self.root / "runtime.json")
        return {
            "environment": "delta-india-demo",
            "dashboard_mode": "read_only",
            "generated_at": _utc_now().isoformat(),
            "runner": runtime,
            "live": live,
            "ledger": _ledger(self.root / "confirmed-fills.sqlite"),
            "events": _events(self.root / "trades.jsonl"),
            "halted": (self.root / "trades.jsonl.crypto24x7-halt").is_file(),
            "warnings": [
                "AI proposals are not executed orders.",
                "Confirmed fill counts and equity observations are not realized P&L.",
                "An offline or stale heartbeat does not prove the VM is powered off.",
            ],
        }


FIRE_ENDPOINTS = {"/api/fire": "fire_trade", "/api/fire-preview": "fire_preview",
                  "/api/fire/XAUTUSD": "gold_trade", "/api/fire-preview/XAUTUSD": "gold_preview"}


def create_handler(state, *, allowed_hosts=None):
    hosts = {"127.0.0.1", "localhost", "[::1]"}
    if allowed_hosts:
        hosts.update(allowed_hosts)

    class Handler(BaseHTTPRequestHandler):
        server_version = "TradebotDashboard/1.0"
        sys_version = ""

        def _headers(self, size, mime, code=200):
            self.send_response(code)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(size))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy",
                             "default-src 'none'; script-src 'self'; "
                             "style-src 'self'; connect-src 'self'; "
                             "img-src 'self'; frame-ancestors 'none'; "
                             "base-uri 'none'; form-action 'none'")
            self.end_headers()

        def _handle(self, *, body=True):
            authority = (self.headers.get("Host") or "").split(":")[0].lower()
            if authority not in hosts:
                data = b"Forbidden host"
                self._headers(len(data), "text/plain", 403)
                if body:
                    self.wfile.write(data)
                return
            path = urlsplit(self.path).path
            if path == "/api/overview":
                data = json.dumps(state.snapshot(), separators=(",", ":")).encode()
                mime = "application/json; charset=utf-8"
            elif path == "/api/isolated/overview":
                overview = getattr(state, "isolated_accounts", None)
                if overview is None:
                    self._headers(0, "application/json", 503)
                    return
                data = json.dumps(overview.snapshot(), separators=(",", ":")).encode()
                mime = "application/json; charset=utf-8"
            elif path == "/api/isolated/performance":
                overview = getattr(state, "isolated_accounts", None)
                perf = getattr(overview, "performance", None)
                if perf is None:
                    self._headers(0, "application/json", 503)
                    return
                data = json.dumps(perf.snapshot(), separators=(",", ":"),
                                  allow_nan=False).encode()
                mime = "application/json; charset=utf-8"
            elif path == "/api/risk/checkpoints":
                data = json.dumps(
                    risk_health(state.root / "fire-equity-risk.sqlite"),
                    separators=(",", ":"),
                ).encode()
                mime = "application/json; charset=utf-8"
            elif path == "/api/learning":
                data = json.dumps(
                    public_learning_summary(state.root / "trade-learning.sqlite"),
                    separators=(",", ":")
                ).encode()
                mime = "application/json; charset=utf-8"
            elif path in FIRE_ENDPOINTS:
                controller = getattr(state, FIRE_ENDPOINTS[path], None)
                if controller is None:
                    self._headers(0, "application/json", 503)
                    return
                data = json.dumps(controller.snapshot(), separators=(",", ":")).encode()
                mime = "application/json; charset=utf-8"
            elif match := re.fullmatch(r"/api/plugin/review/(BTCUSD|XAUTUSD)/([a-f0-9]{32})", path):
                symbol, press = match.groups()
                controller = state.fire_trade if symbol == "BTCUSD" else state.gold_trade
                receipt = controller.store.receipt(press)
                if receipt is None:
                    self._headers(0, "application/json", 404)
                    return
                trade = dict(receipt, id=press)
                data = json.dumps(state.chart_desk.replay(symbol, trade), allow_nan=False).encode()
                mime = "application/json"
            elif path == "/api/chart-desk":
                try:
                    data = json.dumps(state.chart_desk.read(parse_qs(urlsplit(self.path).query)),
                                      allow_nan=False).encode()
                except ValueError:
                    self._headers(0, "application/json", 400)
                    return
                except Exception:
                    self._headers(0, "application/json", 503)
                    return
                mime = "application/json"
            elif path == "/api/candles":
                try:
                    at = int(parse_qs(urlsplit(self.path).query).get("at", [""])[0])
                    data = json.dumps(state.historical_bars(at)).encode()
                except (TypeError, ValueError):
                    self._headers(0, "application/json", 400)
                    return
                except Exception:
                    self._headers(0, "application/json", 503)
                    return
                mime = "application/json"
            elif path in ASSET_TYPES:
                filename, mime = ASSET_TYPES[path]
                data = files("tradebot").joinpath("dashboard_static", filename).read_bytes()
            else:
                data = b"Not found"
                mime = "text/plain; charset=utf-8"
                self._headers(len(data), mime, 404)
                if body:
                    self.wfile.write(data)
                return
            self._headers(len(data), mime)
            if body:
                self.wfile.write(data)

        def do_GET(self):
            self._handle()

        def do_HEAD(self):
            self._handle(body=False)

        def do_POST(self):
            # A paid preview route and an explicitly opt-in Demo FIRE route.
            # Both require strict same-origin POST + custom action header.
            # The host is private loopback behind Cloudflare Access.
            # Never expose the port or accept unauthenticated public traffic.
            host_header = self.headers.get("Host") or ""
            authority = host_header.split(":")[0].lower()
            origin = urlsplit(self.headers.get("Origin") or "")
            expected_scheme = "http" if authority in ("127.0.0.1", "localhost") else "https"
            path = urlsplit(self.path).path
            plugin = re.fullmatch(r"/api/plugin/fire/(BTCUSD|XAUTUSD)/([a-f0-9]{32})", path)
            if plugin:
                symbol, press = plugin.groups()
                path = "/api/fire" if symbol == "BTCUSD" else "/api/fire/XAUTUSD"
            if path not in FIRE_ENDPOINTS:
                data = b"Unsupported route"
                self._headers(len(data), "text/plain", 405)
                self.wfile.write(data)
                return
            if (authority not in hosts or origin.scheme != expected_scheme or
                    origin.netloc.lower() != host_header.lower() or
                    self.headers.get("X-Tradebot-Action") != (
                        "fire-execute" if FIRE_ENDPOINTS[path].endswith("_trade") else "fire-preview") or
                    self.headers.get("Sec-Fetch-Site", "same-origin") != "same-origin" or
                    self.headers.get("Content-Length", "0") != "0"):
                data = b"Forbidden"
                self._headers(len(data), "text/plain", 403)
                self.wfile.write(data)
                return
            controller = getattr(state, FIRE_ENDPOINTS[path], None)
            if controller is None:
                self._headers(0, "application/json", 503)
                return
            if plugin:
                allowed, reason = controller.start(press=press)
                result = {"symbol":symbol, "press":press, "mode":"delta_india_demo_execution",
                          "receipt":controller.store.receipt(press), "reason":reason}
            else:
                allowed, reason = controller.start()
                result = controller.snapshot()
            if not allowed:
                result["reason"] = reason
            data = json.dumps(result, separators=(",", ":")).encode()
            self._headers(
                len(data), "application/json; charset=utf-8",
                202 if allowed else 403 if reason == "execution_disabled"
                else 409 if reason in ("already_running", "existing_trade_or_cooldown")
                else 429)
            self.wfile.write(data)

        def log_message(self, format, *args):
            # Avoid logging potentially attacker-controlled paths or headers.
            pass

    return Handler


def main():
    parser = argparse.ArgumentParser(
        description="Tradebot 2.0 private Delta Demo trading terminal")
    parser.add_argument("--host", default="127.0.0.1",
                        choices=["127.0.0.1"],
                        help="Must bind to loopback; never 0.0.0.0")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("Port must be between 1024 and 65535")
    extra_host = os.getenv("TRADEBOT_DASHBOARD_ALLOWED_HOST", "").strip().lower()
    allowed = {extra_host} if extra_host and ":" not in extra_host else None
    state = DashboardData()
    archive = CandleArchive(state.root / "delta-demo-candles.sqlite")
    state.chart_desk.archive = state.fire_trade.archive = state.gold_trade.archive = archive
    server = ThreadingHTTPServer(
        (args.host, args.port), create_handler(state, allowed_hosts=allowed))
    stopping = Event()
    worker = Thread(target=archive.run, args=(DeltaDemo(), stopping), daemon=True)
    worker.start()
    print("Tradebot 2.0 private dashboard on http://127.0.0.1:" + str(args.port),
          flush=True)
    print("Private loopback only: configure authenticated tunneling before viewing remotely.",
          flush=True)
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        stopping.set()
        server.server_close()
        worker.join(timeout=10)


if __name__ == "__main__":
    main()
