import unittest,copy
from pathlib import Path
from tempfile import TemporaryDirectory
from tradebot.management_instructions_v3 import prepare
from tradebot.management_journal_v3 import ManagementJournal
from tradebot.m23_management_adapter_v3 import adapt,observe

NOW=1795500000
def fixture(s="BTCUSD",side="LONG"):
    p=dict(fixture_position_id="fixture-1",side=side,quantity="3",entry="100",mark="102" if side=="LONG" else "98",stop_loss="95" if side=="LONG" else "105",take_profit="110" if side=="LONG" else "90",protection="broker_reported_bracket")
    o=dict(symbol=s,source="existing_signed_dashboard",fixture_only=True,halted=False,status="open_protection_reported",observed_us=NOW*1000000,open_order_count=2,positions=[p])
    spec=dict(symbol=s,source="delta_demo_public_product",observed_at=NOW,tick_size="0.1")
    return o,prepare(o,spec,now=NOW)
def response(q,action,value):
    return dict(context_id=q["context_id"],symbol=q["payload"]["symbol"],action=action,value=value,rationale="Synthetic fixture")
class AdapterTests(unittest.TestCase):
    def test_all_actions(self):
        for s in ("BTCUSD","XAUTUSD"):
            for side in ("LONG","SHORT"):
                o,q=fixture(s,side)
                for action,v in (("HOLD",None),("MOVE_STOP",99 if side=="LONG" else 101),("BREAKEVEN_STOP",100),("MOVE_TARGET",115 if side=="LONG" else 85),("PARTIAL_EXIT",1),("CLOSE",None)):
                    plan=adapt(q,response(q,action,v),o,now=NOW)
                    after=copy.deepcopy(o);after["observed_us"]+=1000000
                    if plan["expected_remaining"]:
                        after["positions"][0].update(quantity=str(plan["expected_remaining"]),stop_loss=plan["expected_stop"],take_profit=plan["expected_target"])
                        expect="fixture_expected_state_observed"
                    else:
                        after.update(status="flat_observed",positions=[],open_order_count=0)
                        expect="fixture_flat_observed_unsettled"
                    r=observe(plan,after,now=NOW+1)
                    self.assertEqual(r["status"],expect)
                    self.assertFalse(r["settlement_verified"])
                    self.assertFalse(r["execution_authorized"])
    def test_reject_changes(self):
        o,q=fixture();changed=copy.deepcopy(o);changed["positions"][0]["quantity"]="2"
        for current,now in ((changed,NOW),(o,NOW+61)):
            with self.assertRaises(ValueError):adapt(q,response(q,"HOLD",None),current,now=now)
        for a,v in (("MOVE_STOP",90),("MOVE_STOP",100.01),("PARTIAL_EXIT",3),("MOVE_TARGET",101)):
            with self.assertRaises(ValueError):adapt(q,response(q,a,v),o,now=NOW)
    def test_unknown_after(self):
        o,q=fixture();p=adapt(q,response(q,"PARTIAL_EXIT",1),o,now=NOW)
        for after in (None,o,dict(o,symbol="XAUTUSD",observed_us=(NOW+1)*1000000)):
            self.assertTrue(observe(p,after,now=NOW+1)["status"].startswith("unknown"))
    def test_journal_restart(self):
        o,q=fixture();r=response(q,"PARTIAL_EXIT",1)
        with TemporaryDirectory() as d:
            path=Path(d)/"management.sqlite"
            self.assertEqual(ManagementJournal(path).record(q,r,now=NOW),"recorded_offline")
            self.assertEqual(ManagementJournal(path).record(q,r,now=NOW),"duplicate")
            with self.assertRaises(ValueError):ManagementJournal(path).record(q,response(q,"CLOSE",None),now=NOW)
