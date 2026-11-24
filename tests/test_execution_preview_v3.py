import unittest
from tempfile import TemporaryDirectory
from pathlib import Path
from tradebot.execution_preview_v3 import translate,observe_fixture
from tradebot.execution_preview_ledger_v3 import PreviewLedger
from tradebot.ai_decision_v3 import prepare
from tradebot.ai_replay_v3 import wait_fixture
from tradebot.product_context_v3 import product_spec
from tradebot.opportunity_journal_v3 import OpportunityJournal
from test_opportunity_scanner_v3 import scan,ctx,sig,NOW
from test_model_wire_v3 import raw
class ExecutionPreviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory(); self.addCleanup(self.tmp.cleanup); self.root=Path(self.tmp.name)
        j=OpportunityJournal(self.root/"events.sqlite")
        self.events=[j.record(scan(),ctx()),j.record(scan("XAUTUSD",[sig("G01")]),ctx("XAUTUSD"))]
    def make(self,e,side="LONG",kind="MARKET"):
        s=e["symbol"]; q=prepare(e,{"symbol":s,"mode":"synthetic_fixture"})
        r=wait_fixture(q)
        r.update(action=side,plan=dict(entry_type=kind,entry_reference=100,contracts=3,leverage=2,margin_quote=1,
            stop_loss=95 if side=="LONG" else 105,take_profit=105 if side=="LONG" else 95,holding_minutes=15,management="Synthetic"))
        return q,r,product_spec(raw(s),s,NOW)
    def test_translation(self):
        for e in self.events:
            for side in ("LONG","SHORT"):
                for kind in ("MARKET","LIMIT"):
                    q,r,s=self.make(e,side,kind); p=translate(q,r,s,now=NOW)
                    self.assertEqual(p["entry"]["side"],"buy" if side=="LONG" else "sell")
                    self.assertEqual(p["entry"]["kind"],kind)
                    self.assertEqual(p["protection"]["quantity_basis"],"actual_filled_contracts")
                    self.assertFalse(p["execution_authorized"])
                    self.assertEqual(p["orders_submitted"],0)
    def test_invalid_and_wait(self):
        q,r,s=self.make(self.events[0])
        self.assertIsNone(translate(q,wait_fixture(q),s,now=NOW)["entry"])
        with self.assertRaises(ValueError): translate(q,r,s,now=NOW+151)
        with self.assertRaises(ValueError): translate(q,r,dict(s,symbol="XAUTUSD"),now=NOW)
        r["plan"]["stop_loss"]=95.01
        with self.assertRaises(ValueError): translate(q,r,s,now=NOW)
    def test_model_product_context_must_bind_exactly(self):
        from tradebot.model_wire_v3 import build_synthetic_fixture
        e=self.events[0]; symbol=e["symbol"]
        spec=product_spec(raw(symbol),symbol,NOW)
        q=build_synthetic_fixture(e,spec,{"symbol":symbol,"mode":"synthetic_fixture"},now=NOW)["request"]
        r=wait_fixture(q)
        self.assertEqual(translate(q,r,spec,now=NOW)["action"],"WAIT")
        for change in ({"product_id":spec["product_id"]+1},{"tick_size":"0.2"},{"contract_value":"0.002"}):
            with self.subTest(change=change), self.assertRaisesRegex(ValueError,"product_binding_mismatch"):
                translate(q,r,dict(spec,**change),now=NOW)
    def test_receipts_and_restart(self):
        q,r,s=self.make(self.events[0]); p=translate(q,r,s,now=NOW)
        receipt=dict(source="synthetic_fixture",client_order_id=p["entry"]["preview_client_id"],symbol=p["symbol"],product_id=s["product_id"],side="buy",filled_contracts=1,status="open")
        self.assertEqual(observe_fixture(p,receipt)["state"],"fixture_partial")
        self.assertEqual(observe_fixture(p,dict(receipt,filled_contracts=3,status="closed"))["state"],"fixture_filled")
        self.assertEqual(observe_fixture(p,dict(receipt,symbol="XAUTUSD"))["state"],"unknown_requires_reconciliation")
        self.assertEqual(observe_fixture(p,None)["state"],"unknown_requires_reconciliation")
        self.assertEqual(observe_fixture(p,dict(receipt,product_id=float(s["product_id"])))["state"],"unknown_requires_reconciliation")
        path=self.root/"preview.sqlite"; j=PreviewLedger(path)
        self.assertEqual(j.reserve(p,now=NOW),"reserved")
        j=PreviewLedger(path); self.assertEqual(j.recover(now=NOW+120),1)
        self.assertEqual(j.reserve(p,now=NOW+121),"already_reserved")
        self.assertFalse(j.finish(p,receipt,now=NOW+122))
        with self.assertRaises(ValueError): j.reserve(dict(p,action="SHORT"),now=NOW+123)
