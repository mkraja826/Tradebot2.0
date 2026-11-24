import unittest
from datetime import datetime, timezone
from tradebot.subaccount_equity_report_v3 import account_report


class SubaccountEquityReportTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 11, 24, 19, 0, tzinfo=timezone.utc)
        self.overview = {
            "environment": "delta-india-demo",
            "source": "isolated_child_accounts", "mode": "read_only",
            "accounts": {
                label: {"label": label, "symbol": symbol, "status": "connected",
                        "margin_mode": "isolated_verified",
                        "broker_checked_at": self.now.isoformat(),
                        "equity_health": {"blocking_conditions": [], "alert_codes": [],
                                          "checkpoint_prerequisites_met": True,
                                          "as_of": self.now.isoformat(),
                                          "database_integrity": "verified",
                                          "latest_receipt_status": "verified",
                                          "observation_status": "fresh",
                                          "daily_checkpoint": "verified",
                                          "weekly_checkpoint": "verified"}}
                for label, symbol in (("BTC", "BTCUSD"), ("GOLD", "XAUTUSD"))
            }
        }

    def report(self):
        return account_report(self.overview, now=self.now)

    def test_parent_fields_do_not_contaminate_child_report(self):
        self.overview["blocking_conditions"] = ["equity_loss_limit_breached"]
        self.overview["accounts"]["MAIN"] = {"equity_health": self.overview}
        result = self.report()
        self.assertEqual(set(result["accounts"]), {"BTC", "GOLD"})
        self.assertEqual(result["accounts"]["BTC"]["equity_conditions"], [])
        self.assertEqual(result["accounts"]["GOLD"]["equity_conditions"], [])
        self.assertFalse(result["trade_authorized"])

    def test_child_breach_remains_visible_and_separate(self):
        self.overview["accounts"]["BTC"]["equity_health"]["blocking_conditions"] = [
            "equity_loss_limit_breached", "watchdog_protection_unverified"]
        result = self.report()["accounts"]
        self.assertEqual(result["BTC"]["equity_loss_warnings"], ["equity_loss_limit_breached"])
        self.assertIn("watchdog_protection_unverified", result["BTC"]["other_review_conditions"])
        self.assertEqual(result["GOLD"]["equity_conditions"], [])
        self.assertFalse(result["BTC"]["trade_authorized"])

    def test_missing_child_never_substitutes_parent(self):
        del self.overview["accounts"]["GOLD"]
        result = self.report()["accounts"]["GOLD"]
        self.assertEqual(result["equity_conditions"], ["child_evidence_unavailable"])
        self.assertFalse(result["broker_identity_and_margin_reported"])

    def test_wrong_source_and_swapped_market_fail_closed(self):
        self.overview["accounts"]["BTC"]["symbol"] = "XAUTUSD"
        self.assertFalse(self.report()["accounts"]["BTC"]["broker_identity_and_margin_reported"])
        self.overview["source"] = "legacy_parent"
        self.assertFalse(self.report()["accounts"]["GOLD"]["broker_identity_and_margin_reported"])

    def test_stale_broker_evidence_and_unknown_codes_remain_visible(self):
        child = self.overview["accounts"]["BTC"]
        child["broker_checked_at"] = "2026-11-24T18:00:00+00:00"
        child["equity_health"]["alert_codes"] = ["PRIVATE_UNKNOWN_VALUE"]
        result = self.report()["accounts"]["BTC"]
        self.assertFalse(result["broker_identity_and_margin_reported"])
        self.assertIn("child_broker_evidence_unverified", result["other_review_conditions"])
        self.assertNotIn("PRIVATE_UNKNOWN_VALUE", str(result))
        self.assertIn("other_equity_condition_requires_review", result["equity_conditions"])

    def test_stale_or_unverified_equity_does_not_look_healthy(self):
        health = self.overview["accounts"]["GOLD"]["equity_health"]
        health.update(as_of="2026-11-24T18:00:00+00:00",
                      weekly_checkpoint="missed_window",
                      latest_receipt_status="invalid")
        row = self.report()["accounts"]["GOLD"]
        self.assertFalse(row["checkpoint_prerequisites_met"])
        self.assertIn("child_equity_report_stale_or_missing", row["equity_conditions"])
        self.assertIn("child_weekly_checkpoint_unverified", row["equity_conditions"])
        self.assertIn("child_equity_receipt_unverified", row["equity_conditions"])

    def test_loss_blocker_not_suppressed_even_with_inconsistent_health(self):
        health = self.overview["accounts"]["BTC"]["equity_health"]
        health["blocking_conditions"] = ["equity_loss_limit_breached"]
        row = self.report()["accounts"]["BTC"]
        self.assertEqual(row["reported_checkpoint_blockers"], ["equity_loss_limit_breached"])
        self.assertFalse(row["checkpoint_prerequisites_met"])

    def test_missing_evidence_and_bad_broker_are_explicit(self):
        self.overview["accounts"]["GOLD"].pop("equity_health")
        self.overview["accounts"]["GOLD"]["status"] = "broker_unavailable"
        row = self.report()["accounts"]["GOLD"]
        self.assertFalse(row["checkpoint_prerequisites_met"])
        self.assertIn("child_evidence_unavailable", row["other_review_conditions"])
        self.assertIn("child_broker_evidence_unverified", row["other_review_conditions"])
