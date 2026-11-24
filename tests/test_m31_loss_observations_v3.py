import unittest
from datetime import datetime,timezone,timedelta
from decimal import Decimal
from tradebot.portfolio_equity_guard import stamp
from tradebot.m31_loss_observations_v3 import calculate

DAY=datetime(2026,11,23,tzinfo=timezone.utc)
def rows(*pairs):
    return [(stamp(DAY+timedelta(seconds=t)),v) for t,v in pairs]
class LossObservationsTests(unittest.TestCase):
    def test_openings_and_peak(self):
        r=calculate(rows((1,"100"),(61,"120"),(121,"90")),DAY+timedelta(seconds=122))
        self.assertEqual(Decimal(r["daily_observed_decline"]),Decimal("0.1"))
        self.assertEqual(Decimal(r["weekly_observed_decline"]),Decimal("0.1"))
        self.assertEqual(Decimal(r["sampled_archive_peak_decline"]),Decimal("0.25"))
        self.assertFalse(r["historical_peak_verified"])
        self.assertFalse(r["execution_authorized"])
    def test_partial_period(self):
        r=calculate(rows((400,"100"),(460,"90")),DAY+timedelta(seconds=461))
        self.assertIsNone(r["daily_observed_decline"])
        self.assertIsNone(r["weekly_observed_decline"])
    def test_gap(self):
        r=calculate(rows((1,"100"),(500,"90")),DAY+timedelta(seconds=501))
        self.assertEqual(r["gaps_over_180s"],1)
        self.assertIsNone(r["daily_observed_decline"])
    def test_stale_and_duplicate(self):
        with self.assertRaises(ValueError):calculate(rows((1,"100"),(60,"99")),DAY+timedelta(seconds=300))
        with self.assertRaises(ValueError):calculate(rows((1,"100"),(1,"99")),DAY+timedelta(seconds=2))
