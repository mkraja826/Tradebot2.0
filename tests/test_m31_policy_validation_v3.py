"""Independent mathematical oracle for synthetic evidence, not release approval."""
import unittest
from fractions import Fraction
from decimal import Decimal
from datetime import datetime,timezone,timedelta
from tradebot.m25_equity_policy_research_v3 import study
from tradebot.m31_loss_observations_v3 import calculate
from tradebot.portfolio_equity_guard import stamp
from test_m25_equity_policy_research_v3 import fixture,val,flow

class PolicyValidationTests(unittest.TestCase):
    def test_exact_reference_multiple_flows(self):
        # Independent oracle: chain only the trading intervals, not transfers.
        for starting in (100,273,1000):
            for loss in (1,7,19):
                for capital in (25,-25):
                    before=starting-loss
                    after=before+capital
                    ending=after-1
                    expected=1-Fraction(before,starting)*Fraction(ending,after)
                    r=study(fixture(val(1,str(starting)),flow(400,str(before),str(after),str(capital)),val(401,str(ending))))
                    got=Fraction(Decimal(r["observed_peak_decline"]))
                    self.assertGreaterEqual(got,expected)
                    self.assertLess(got-expected,Fraction(1,10**38))
                    self.assertFalse(r["execution_authorized"])
    def test_transfer_cannot_erase_earlier_loss(self):
        r=study(fixture(val(1,"100"),val(2,"80"),flow(400,"80","1080","1000")))
        self.assertEqual(Decimal(r["observed_peak_decline"]),Decimal("0.2"))
    def test_wrong_transfer_pair_and_unknown(self):
        for event in (flow(400,"80","1080","999"),dict(val(400,"80"),kind="unknown")):
            with self.assertRaises(ValueError):study(fixture(val(1,"100"),event))
    def test_ambiguous_same_time(self):
        with self.assertRaises(ValueError):study(fixture(val(1,"100"),flow(400,"100","200","100"),val(400,"190")))
    def test_no_implicit_opening(self):
        t=datetime(2026,11,24,13,tzinfo=timezone.utc)
        r=calculate([(stamp(t),"100"),(stamp(t+timedelta(seconds=60)),"99")],t+timedelta(seconds=61))
        self.assertIsNone(r["daily_observed_decline"])
        self.assertIsNone(r["weekly_observed_decline"])
        self.assertFalse(r["historical_loss_reconciled"])
    def test_observed_peak_not_first_equity(self):
        t=datetime(2026,11,24,13,tzinfo=timezone.utc)
        r=calculate([(stamp(t),"100"),(stamp(t+timedelta(seconds=60)),"125"),(stamp(t+timedelta(seconds=120)),"100")],t+timedelta(seconds=121))
        self.assertEqual(Decimal(r["sampled_archive_peak_decline"]),Decimal("0.2"))
        self.assertFalse(r["historical_peak_verified"])
