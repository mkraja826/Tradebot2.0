import unittest
from decimal import Decimal
from tradebot.m27_sizing_research_v3 import review
NOW=1795524349
def fixture(s="BTCUSD",side="LONG"):
    return dict(mode="synthetic_sizing_fixture",execution_authorized=False,symbol=s,direction=side,
        product=dict(symbol=s,source="delta_demo_public_product",observed_at=NOW,
            contract_type="perpetual_futures",quote_currency="USD",settlement_currency="USD",
            tick_size="0.1" if s=="BTCUSD" else "0.01",contract_value="0.001"),
        quote=dict(symbol=s,observed_at=NOW,best_bid="1000",best_ask="1000"),
        stop_loss="990" if side=="LONG" else "1010",take_profit="1040" if side=="LONG" else "960",
        fixture_equity="1000",fixture_available_margin="800",fixture_taker_rate="0.0005")
class SizingTests(unittest.TestCase):
    def test_four_cases(self):
        for s in ("BTCUSD","XAUTUSD"):
            for side in ("LONG","SHORT"):
                r=review(fixture(s,side),now=NOW)
                self.assertEqual(r["status"],"minimum_contract_fixture_validated")
                self.assertFalse(r["execution_authorized"])
                self.assertFalse(r["broker_margin_verified"])
                self.assertFalse(r["stop_execution_guaranteed"])
    def test_margin(self):
        self.assertEqual(review(dict(fixture(),fixture_available_margin="0.1"),now=NOW)["status"],"fixture_margin_shortfall")
    def test_loss(self):
        f=dict(fixture(),fixture_equity="1",fixture_available_margin="1")
        self.assertEqual(review(f,now=NOW)["status"],"existing_risk_validator_rejected_fixture")
    def test_off_tick(self):
        with self.assertRaises(ValueError):review(dict(fixture(),stop_loss="990.01"),now=NOW)
    def test_wrong_side(self):
        with self.assertRaises(ValueError):review(dict(fixture(),stop_loss="1010"),now=NOW)
    def test_stale(self):
        with self.assertRaises(ValueError):review(fixture(),now=NOW+61)
    def test_scope(self):
        with self.assertRaises(ValueError):review(dict(fixture(),mode="live"),now=NOW)
        with self.assertRaises(ValueError):review(dict(fixture(),symbol="XAUTUSD"),now=NOW)
    def test_costs(self):
        r=review(fixture(),now=NOW)
        self.assertGreater(Decimal(r["estimated_stop_loss"]),Decimal("0.01"))
