import unittest
from datetime import datetime,timezone
from decimal import Decimal
from tradebot.m25_equity_policy_research_v3 import study

T=int(datetime(2026,11,23,tzinfo=timezone.utc).timestamp())*1000000
def val(i,e,offset=None):
    return dict(event_id=str(i),at_us=T+(i if offset is None else offset)*1000000,kind="valuation",equity=e,symbol="BTCUSD",fixture_account="synthetic-btc")
def flow(i,b,a,f):
    return dict(val(i,b),kind="capital",before=b,after=a,flow=f)
def fixture(*events):
    return dict(mode="synthetic_policy_research",execution_authorized=False,symbol="BTCUSD",fixture_account="synthetic-btc",complete_fixture=True,events=list(events))

class EquityPolicyTests(unittest.TestCase):
    def test_outflow_neutral(self):
        r=study(fixture(val(1,"1000"),flow(400,"1000","600","-400"),val(401,"600")))
        self.assertEqual(Decimal(r["observed_peak_decline"]),0)
        self.assertEqual(Decimal(r["weekly_decline"]),0)
        self.assertFalse(r["execution_authorized"])
    def test_inflow_does_not_hide_loss(self):
        r=study(fixture(val(1,"1000"),val(400,"900"),flow(401,"900","1900","1000")))
        self.assertEqual(Decimal(r["observed_peak_decline"]),Decimal("0.1"))
    def test_loss_after_withdrawal(self):
        r=study(fixture(val(1,"1000"),flow(400,"1000","500","-500"),val(401,"450")))
        self.assertEqual(Decimal(r["observed_peak_decline"]),Decimal("0.1"))
    def test_missing_week_not_replaced(self):
        r=study(fixture(val(1,"100",offset=3600),val(2,"90",offset=3601)))
        self.assertIsNone(r["weekly_decline"])
        self.assertFalse(r["historical_anchor_created"])
    def test_invalid_events(self):
        for events in ((val(1,"100"),flow(2,"100","90","-5")),
                       (val(1,"100"),dict(val(2,"100"),fixture_account="other")),
                       (val(1,"100"),val(1,"90")),
                       (val(1,"100"),dict(val(2,"90"),event_id="1")),
                       (val(1,"100"),val(2,"0"))):
            with self.assertRaises(ValueError):study(fixture(*events))
    def test_incomplete_and_nonfixture(self):
        f=fixture(val(1,"100"))
        self.assertEqual(study(dict(f,complete_fixture=False))["status"],"missing_fixture_evidence")
        with self.assertRaises(ValueError):study(dict(f,mode="live"))
    def test_peak_before_transfer(self):
        r=study(fixture(val(1,"100"),flow(400,"125","225","100"),val(401,"180")))
        self.assertEqual(Decimal(r["observed_peak_decline"]),Decimal("0.2"))

    def test_fraction_and_conservative_rounding(self):
        from fractions import Fraction
        r=study(fixture(val(1,"3"),val(400,"2")))
        loss=Fraction(Decimal(r["observed_peak_decline"]))
        self.assertGreaterEqual(loss,Fraction(1,3))
        self.assertLess(loss-Fraction(1,3),Fraction(1,10**38))
    def test_generated_flow_invariance(self):
        for principal in (10,17,100,273,276):
            for extra in (1,3,19,100):
                base=principal*3
                a=study(fixture(val(1,str(base)),val(400,str(base-1))))
                b=study(fixture(val(1,str(base)),val(400,str(base-1)),flow(401,str(base-1),str(base-1+extra),str(extra))))
                self.assertEqual(a["observed_peak_decline"],b["observed_peak_decline"])
    def test_near_zero_refused(self):
        with self.assertRaises(ValueError):study(fixture(val(1,"0.00001")))

    def test_oversized_model_number_refused(self):
        from tradebot.ai_decision_v3 import positive
        self.assertFalse(positive(10**400))
        self.assertFalse(positive(float("inf")))
        self.assertFalse(positive(True))
