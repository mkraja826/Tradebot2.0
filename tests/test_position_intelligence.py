import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from decimal import Decimal
from recover_trading.position_intelligence import reduction_evidence, retention, report

class PositionIntelligenceTests(unittest.TestCase):
    def fixture(self):
        ep={"opened":"2026-11-25T00:00:00Z","closed":"2026-11-25T00:10:00Z","direction":"LONG","fills":3,
            "gross_pnl":"10","fees":"3","net_before_funding":"7"}
        def fill(i,order,time,side,size,price,after):
            return {"id":i,"order_id":order,"product_id":5,"created_at":"2026-11-25T00:"+time+"Z","side":side,
                    "size":size,"price":price,"commission":"1","settling_asset_symbol":"USD","new_position":{"size":after}}
        fills=[fill(1,10,"00:00","buy",10,100,10),fill(2,11,"05:00","sell",5,102,5),fill(3,12,"10:00","sell",5,100,0)]
        from datetime import datetime
        t=int(datetime.fromisoformat("2026-11-25T00:04:00+00:00").timestamp())
        ident="proposal";cid=hashlib.sha256(("management:"+ident).encode()).hexdigest()[:32]
        identity={"created_at":"x"}
        c={"execution_identity":identity}
        r={"proposal":{"action":"reduce"}}
        a={"identity":identity,"client_id":cid,"receipt":{"id":11,"client_order_id":cid,"product_id":5,"reduce_only":True},
           "plan":{"action":"reduce","product_id":5,"requested_reduction":5},
           "evidence":{"status":"partial_close_observed","target_size_observed":True}}
        records=[(ident,"actual-manager",t,"proposed",json.dumps(c),json.dumps(r),t+1,"reduce","verified",json.dumps(a))]
        spec={"id":5,"notional_type":"vanilla","contract_value":"1","settling_asset":{"symbol":"USD"},"quoting_asset":{"symbol":"USD"}}
        return ep,fills,records,spec
    def test_receipt_linked_net_contribution(self):
        x=reduction_evidence(*self.fixture())
        self.assertEqual(x["matched_exit_fills"],1)
        self.assertEqual(Decimal(x["actions"][0]["net_contribution_before_funding"]),Decimal("8.5"))
    def test_missing_or_mismatched_receipt(self):
        e,f,r,s=self.fixture();r[0]=(*r[0][:-1],"{}")
        self.assertEqual(reduction_evidence(e,f,r,s)["actions"],[])
    def test_accounting_mismatch(self):
        e,f,r,s=self.fixture();e["gross_pnl"]="999"
        self.assertEqual(reduction_evidence(e,f,r,s)["status"],"episode_accounting_mismatch")
    def test_retention_flags(self):
        e={"net_before_funding":"-1"}
        x={"status":"complete_interior_lower_bound","mfe_bps":40,"mae_bps":20,"gross_weighted_exit_return_bps":-10}
        self.assertEqual(retention(e,x)["diagnostic"],"favorable_movement_then_net_loss")
        x["mfe_bps"]=1064
        self.assertIsNone(retention(e,x)["observed_gap_bps"])
    def test_missing_journals_no_write(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/"BTCUSD"
            self.assertFalse(report(p,"BTCUSD")["coverage"]["management_journal_available"])
            self.assertFalse(p.exists())
