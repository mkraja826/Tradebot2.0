import tempfile
import unittest
from pathlib import Path
from decimal import Decimal
from recover_trading.capital_intelligence import allocation, cohort, report

class CapitalIntelligenceTests(unittest.TestCase):
    def fixture(self):
        c={"symbol":"XAUTUSD","demo_account":{"product":{"symbol":"XAUTUSD","notional_type":"vanilla",
            "contract_value":"0.01","settling_asset":{"symbol":"USD"},"quoting_asset":{"symbol":"USD"}},
            "wallets":[{"asset_symbol":"USD","balance":"1000","available_balance":"800"},
                       {"asset_symbol":"INR","balance":"90000","available_balance":"90000"}]}}
        r={"symbol":"XAUTUSD","side":"buy","size":500,"leverage":20,"capital_allocation":900,
            "entry_reference":3600,"stop_loss":3590,"take_profit":3620}
        v={"filled_contracts":"250","average_fill_price":"3600"}
        e={"net_before_funding":"-20","fees":"1"}
        return c,r,v,e
    def test_partial_fill_and_currency(self):
        a=allocation(*self.fixture())
        self.assertEqual(Decimal(a["planned_initial_margin_estimate"]),900)
        self.assertEqual(Decimal(a["filled_initial_margin_estimate"]),450)
        self.assertEqual(Decimal(a["planned_loss_at_actual_fill"]),25)
        self.assertEqual(Decimal(a["filled_to_planned_contracts"]),Decimal("0.5"))
        self.assertEqual(Decimal(a["estimated_stop_loss_to_wallet_balance"]),Decimal("0.025"))
        self.assertEqual(Decimal(a["filled_margin_estimate_minus_planned_budget"]),-450)
    def test_duplicate_wallet_is_unknown(self):
        c,r,v,e=self.fixture()
        c["demo_account"]["wallets"].append({"asset_symbol":"USD","balance":"99"})
        a=allocation(c,r,v,e)
        self.assertIsNone(a["wallet_balance_at_decision"])
        self.assertIsNone(a["estimated_stop_loss_to_wallet_balance"])
    def test_wrong_product_or_leverage_is_not_normalized(self):
        c,r,v,e=self.fixture();r["leverage"]=100
        a=allocation(c,r,v,e)
        self.assertIsNone(a["filled_notional"])
        self.assertIsNone(a["planned_loss_at_actual_fill"])
    def test_cohort_currency_and_ties(self):
        rows=[{"allocation":{"currency":s,"estimated_stop_loss_to_wallet_balance":v,
               "observed_net_before_funding":n}} for s,v,n in
               [("USD","0.01","2"),("USD","0.01","-1"),("USD","0.03","-5"),("INR","0.02","100")]]
        out=cohort(rows)
        self.assertEqual(len(out),3)
        low=next(x for x in out if x["currency"]=="USD" and x["group"]=="at_or_below_sample_median")
        self.assertEqual(low["samples"],2)
        self.assertEqual(Decimal(low["net_before_funding"]),1)
    def test_missing_journals_no_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/"XAUTUSD"
            self.assertFalse(report(p,"XAUTUSD")["coverage"]["decision_journal_available"])
            self.assertFalse(p.exists())
