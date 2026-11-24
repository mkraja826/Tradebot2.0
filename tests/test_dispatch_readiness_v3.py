import unittest
from datetime import datetime,timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from tradebot.dashboard_context_v3 import read_accounts
from tradebot.dispatch_readiness_v3 import assess,preview
from tradebot.product_context_v3 import product_spec,account_unavailable
from tradebot.opportunity_journal_v3 import OpportunityJournal
from test_opportunity_scanner_v3 import scan,ctx,sig,NOW
from test_model_wire_v3 import raw
from test_account_context_v3 import report,NOW as ACCOUNT_NOW

class ReadinessTests(unittest.TestCase):
    def test_dashboard_adapter(self):
        a=read_accounts(report,now=ACCOUNT_NOW)
        self.assertEqual(a["BTCUSD"]["status"],"partial")
        self.assertTrue(a["BTCUSD"]["halted"])
        self.assertEqual(a["XAUTUSD"]["status"],"unavailable")
        def bad(): raise OSError()
        self.assertTrue(all(v["status"]=="unavailable" for v in read_accounts(bad).values()))
    def test_fresh_preview_and_expired(self):
        with TemporaryDirectory() as d:
            j=OpportunityJournal(Path(d)/"opportunities-v3.sqlite")
            e=j.record(scan(),ctx())
            p={"status":"ready","data":product_spec(raw("BTCUSD"),"BTCUSD",NOW)}
            a=account_unavailable("BTCUSD")
            x=assess(e,a,p,now=NOW)
            self.assertTrue(x["wire_prepared"])
            self.assertFalse(x["paid_dispatch_authorized"])
            self.assertEqual(x["status"],"signed_margin_context_incomplete")
            self.assertEqual(assess(e,dict(a,halted=True),p,now=NOW)["status"],"account_halted")
            self.assertEqual(assess(e,a,p,now=NOW+151)["status"],"expired")
            self.assertEqual(assess(e,account_unavailable("XAUTUSD"),p,now=NOW)["status"],"invalid_context")
            y=preview(d,account_reader=lambda:{s:account_unavailable(s) for s in ("BTCUSD","XAUTUSD")},spec_reader=lambda:{"BTCUSD":p,"XAUTUSD":{"status":"unavailable"}},clock=lambda:NOW)
            self.assertEqual(y["paid_ai_requests"],0)
            self.assertEqual(y["markets"]["XAUTUSD"]["status"],"no_opportunity")
            self.assertTrue((Path(d)/"dispatch-readiness-v3.json").exists())

    def test_native_equity_missing_and_stale(self):
        from unittest.mock import patch
        from tradebot.dispatch_readiness_v3 import native_equity_context
        with TemporaryDirectory() as d:
            self.assertEqual(native_equity_context(d,"BTCUSD",now=NOW)["status"],"unavailable")
            state=dict(last_observed_us=(NOW-181)*1000000,observed_periods={
                "daily":dict(observed_breach=True,opening_verified=True),
                "weekly":dict(observed_breach=None,opening_verified=False),
                "drawdown":dict(observed_breach=False)},historical_loss_reconciled=False,broker_finality_verified=False)
            with patch("tradebot.admin_v3.status",return_value=state):
                x=native_equity_context(d,"XAUTUSD",now=NOW)
                self.assertEqual(x["status"],"stale_evidence")
                self.assertEqual(x["observed_raw_breaches"],["daily"])
                self.assertEqual(x["unresolved_openings"],["weekly"])
                self.assertFalse(x["execution_authorized"])
                self.assertEqual(native_equity_context(d,"XAUTUSD",now=NOW-182)["status"],"unavailable")
