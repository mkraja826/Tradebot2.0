import unittest
from tempfile import TemporaryDirectory
from pathlib import Path
from tradebot.management_instructions_v3 import prepare,validate
from tradebot.management_journal_v3 import ManagementJournal
from tradebot.position_observer_v3 import view
from tradebot.product_context_v3 import product_spec
from test_model_wire_v3 import raw
from test_position_monitor_v3 import account,pos,NOW

class ManagementTests(unittest.TestCase):
    def request(self,s="BTCUSD",side="LONG"):
        p=pos(s,side); p.update(size="5" if side=="LONG" else "-5",mark="103" if side=="LONG" else "97")
        return prepare(view(s,account(s,positions=[p],orders=2),now=NOW),product_spec(raw(s),s,NOW),now=NOW)
    def reply(self,r,action,value=None):
        return dict(context_id=r["context_id"],symbol=r["payload"]["symbol"],action=action,value=value,rationale="Synthetic test only")
    def test_all_actions_both_markets_and_sides(self):
        for s in ("BTCUSD","XAUTUSD"):
            for side in ("LONG","SHORT"):
                r=self.request(s,side)
                for a,v in (("HOLD",None),("CLOSE",None),("PARTIAL_EXIT",2),("BREAKEVEN_STOP","100"),("MOVE_STOP","101" if side=="LONG" else "99"),("MOVE_TARGET","107" if side=="LONG" else "93")):
                    result=validate(r,self.reply(r,a,v))
                    self.assertFalse(result["execution_authorized"])
                    self.assertFalse(result["scanner_control"])
                    self.assertEqual(result["orders_submitted"],0)
    def test_invalid_instruction(self):
        r=self.request()
        for a,v in (("PARTIAL_EXIT",5),("PARTIAL_EXIT",True),("MOVE_STOP","94"),("MOVE_STOP","103"),("MOVE_STOP","101.01"),("BREAKEVEN_STOP","101"),("MOVE_TARGET","102"),("CLOSE",1),("ADD",1)):
            with self.assertRaises(ValueError): validate(r,self.reply(r,a,v))
        with self.assertRaises(ValueError): validate(r,dict(self.reply(r,"HOLD"),symbol="XAUTUSD"))
        with self.assertRaises(ValueError): prepare(r["payload"]["observation"],r["payload"]["product"],now=NOW+61)
        with self.assertRaises(ValueError): validate(dict(r,context_id="wrong"),self.reply(r,"HOLD"))
    def test_journal_idempotent(self):
        with TemporaryDirectory() as d:
            r=self.request(); p=Path(d)/"m.sqlite"; j=ManagementJournal(p); x=self.reply(r,"HOLD")
            self.assertEqual(j.record(r,x,now=NOW),"recorded_offline")
            self.assertEqual(ManagementJournal(p).record(r,x,now=NOW),"duplicate")
            with self.assertRaises(ValueError): j.record(r,self.reply(r,"CLOSE"),now=NOW)
            with self.assertRaises(ValueError): j.record(r,x,now=NOW+61)
