"""No-network fail-closed review for short BTC supervised-session equity."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3
import tempfile
import unittest

from equity_fixtures import receipt_for
from tradebot.delta import DEMO_API
from tradebot.btc_supervised_session import (
    assess_supervised_session, inspect_btc_session_candidate,
)

NOW = datetime(2026, 11, 22, 17, 0, tzinfo=timezone.utc)


def healthy(*, weekly="missed_window", daily="verified", latest="verified",
            age=50, monitoring=True, extra=None):
    conditions = (["weekly_checkpoint_missed_window"] if weekly == "missed_window"
                  else []) + (extra or [])
    return {
        "status": "checkpoint_missed" if weekly == "missed_window" else "healthy",
        "daily_checkpoint": daily, "weekly_checkpoint": weekly,
        "latest_receipt_status": latest, "observation_status": "fresh",
        "database_integrity": "verified", "blocking_conditions": conditions,
        "monitoring": {
            "watchdog": "healthy" if monitoring else "stale",
            "equity_collector": "healthy",
            "watchdog_age_seconds": 5 if monitoring else 400,
            "equity_collector_age_seconds": 15,
            "alert_codes": [] if monitoring else ["watchdog_heartbeat_stale"],
        },
    }


class ReadOnlyDemo:
    base_url = DEMO_API
    allow_orders = False

    def __init__(self, equity="1000"):
        self.equity = equity
        self.calls = 0

    def wallet_balances(self):
        self.calls += 1
        return {"meta": {"net_equity": self.equity},
                "equity_read_receipt": receipt_for(self.equity, NOW)}


class SupervisedSessionTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.path = self.root / "fire-equity-risk.sqlite"
        with sqlite3.connect(self.path) as db:
            db.executescript("""
                CREATE TABLE equity_evidence(
                    observed_us INTEGER, equity_usd TEXT, origin TEXT);
                CREATE TABLE equity_watermark(
                    singleton INTEGER, high_usd TEXT);
                INSERT INTO equity_watermark VALUES (1,'1050');
            """)
            db.execute("INSERT INTO equity_evidence VALUES (?,?,?)",
                       (int((NOW-timedelta(seconds=35)).timestamp()*1_000_000),
                        "1000", "delta_demo_signed_wallet"))
            db.commit()

    def candidate(self, broker=None, health=None):
        broker = broker or ReadOnlyDemo()
        before = self.path.read_bytes()
        result = inspect_btc_session_candidate(
            broker, self.root, now=NOW,
            health_fn=lambda path, at: health or healthy())
        self.assertEqual(self.path.read_bytes(), before)
        return result, broker

    def test_missing_weekly_anchor_does_not_prevent_readonly_baseline_candidate(self):
        report, broker = self.candidate()
        self.assertEqual(report["status"], "baseline_candidate_review_only")
        self.assertTrue(report["standard_weekly_opening_missing"])
        self.assertTrue(report["fresh_session_wallet_baseline_verified"])
        self.assertTrue(report["original_equity_history_integrity_verified"])
        self.assertEqual(broker.calls, 1)
        for field in ("trade_authorized", "safe_to_enable_fire",
                      "broker_order_mutations", "original_equity_ledger_mutations",
                      "new_session_ledger_mutations", "signed_account_margin_verified",
                      "btc_historical_price_integrity_verified"):
            self.assertFalse(report[field])

    def test_verified_weekly_anchor_also_supports_candidate(self):
        report, _ = self.candidate(health=healthy(weekly="verified"))
        self.assertEqual(report["status"], "baseline_candidate_review_only")
        self.assertFalse(report["standard_weekly_opening_missing"])

    def test_other_equity_health_blocks_before_broker(self):
        for state in (healthy(daily="missed_window"),
                      healthy(latest="missing"),
                      healthy(extra=["latest_equity_read_receipt_unverified"]),
                      healthy(monitoring=False)):
            with self.subTest(state=state["blocking_conditions"]):
                broker = ReadOnlyDemo()
                result, _ = self.candidate(broker, health=state)
                self.assertEqual(result["status"], "blocked")
                self.assertEqual(broker.calls, 0)

    def test_refuses_live_or_order_capable_client(self):
        for address, orders in (("https://api.india.delta.exchange", False),
                                (DEMO_API, True)):
            broker = ReadOnlyDemo()
            broker.base_url, broker.allow_orders = address, orders
            result, _ = self.candidate(broker)
            self.assertEqual(result["reason"], "readonly_delta_demo_client_required")
            self.assertEqual(broker.calls, 0)

    def test_missing_original_history_never_creates_or_replaces(self):
        self.path.unlink()
        report = inspect_btc_session_candidate(
            ReadOnlyDemo(), self.root, now=NOW,
            health_fn=lambda path, at: healthy())
        self.assertEqual(report["reason"], "original_equity_ledger_unavailable")
        self.assertFalse(self.path.exists())

    def test_watermark_disagreement_blocks(self):
        with sqlite3.connect(self.path) as db:
            db.execute("UPDATE equity_watermark SET high_usd='900'")
            db.commit()
        report, broker = self.candidate()
        self.assertEqual(report["status"], "blocked")
        self.assertEqual(broker.calls, 0)

    def test_session_loss_ceiling_and_historical_peak_limit(self):
        start = receipt_for("1000", NOW - timedelta(minutes=5))
        for equity,peak,reason in (
            ("994", "1000", "supervised_session_loss_limit"),
            ("999", "1100", "historical_high_watermark_drawdown_limit"),
            ("1030", "1000", "possible_external_balance_change"),
            ("998", "1000", "requires_separate_broker_and_execution_release"),
        ):
            with self.subTest(equity=equity,peak=peak):
                result = assess_supervised_session(
                    "1000", equity, peak, start, receipt_for(equity,NOW), now=NOW)
                self.assertEqual(result["reason"], reason)
                self.assertEqual(result["within_session_limits"],
                                 equity == "998")
                self.assertFalse(result["trade_authorized"])

    def test_expired_or_out_of_order_session_refused(self):
        expired = assess_supervised_session(
            "1000", "1000", "1000",
            receipt_for("1000",NOW - timedelta(minutes=16)),
            receipt_for("1000",NOW), now=NOW)
        self.assertEqual(expired["reason"], "session_not_within_fifteen_minutes")
        future = assess_supervised_session(
            "1000", "1000", "1000",
            receipt_for("1000",NOW + timedelta(minutes=1)),
            receipt_for("1000",NOW), now=NOW)
        self.assertFalse(future["within_session_limits"])

    def test_untrusted_old_or_mismatched_wallet_receipt(self):
        broker = ReadOnlyDemo()
        broker.wallet_balances = lambda: {
            "meta": {"net_equity": "1000"},
            "equity_read_receipt": receipt_for("900",NOW),
        }
        report, _ = self.candidate(broker)
        self.assertEqual(report["status"], "blocked")
        self.assertFalse(report["fresh_session_wallet_baseline_verified"])

    def test_cli_is_permanently_nonauthorizing(self):
        from pathlib import Path
        module = (Path(__file__).resolve().parents[1] /
                  "src/tradebot/btc_supervised_session.py").read_text()
        self.assertIn("return 2  # Never emit release success", module)
        controller = (Path(__file__).resolve().parents[1] /
                      "src/tradebot/fire_execution.py").read_text()
        self.assertIn("self.equity_guard.require_verified_read(", controller)
        self.assertNotIn("btc_supervised_session", controller)


if __name__ == "__main__":
    unittest.main()
