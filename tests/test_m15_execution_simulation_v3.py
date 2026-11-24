import unittest,sqlite3
from pathlib import Path
from tempfile import TemporaryDirectory
from contextlib import closing
from tradebot.synthetic_lifecycle_v3 import LifecycleLedger,project,fixture_receipt,fixture_protections
from tradebot.m15_execution_simulation_v3 import tick
from tradebot.product_context_v3 import product_spec
from tradebot.model_wire_v3 import MODEL_IDS
from test_model_wire_v3 import raw
from test_opportunity_scanner_v3 import NOW
def preview():
    return dict(mode="synthetic_execution_preview",execution_authorized=False,orders_submitted=0,action="LONG",symbol="BTCUSD",event_id="fixture",
        entry=dict(product_id=84,side="buy",contracts=3,preview_client_id="fixture-entry"),
        protection=dict(stop_loss="95",take_profit="105",quantity_basis="actual_filled_contracts",direction="LONG"))
class LifecycleTests(unittest.TestCase):
    def test_all_assets_and_directions(self):
        with TemporaryDirectory() as d:
            r=tick(d,spec_reader=lambda:{s:dict(status="ready",data=product_spec(raw(s),s,NOW)) for s in MODEL_IDS},clock=lambda:NOW)
            self.assertEqual(sum(len(v["fixtures"]) for v in r["markets"].values()),4)
            self.assertFalse(r["execution_authorized"])
    def test_scope_and_protection(self):
        p=preview(); rec=fixture_receipt(p,1,"open"); good=fixture_protections(p,1)
        self.assertEqual(project(p,rec,good)["protection_state"],"fixture_bracket_matched")
        for key,value in (("contracts",3),("reduce_only",False),("symbol","XAUTUSD"),("product_id",181689),("parent_client_id","other"),("side","buy"),("trigger","96"),("order_id",good[1]["order_id"])):
            b=[dict(good[0],**{key:value}),good[1]]
            self.assertEqual(project(p,rec,b)["protection_state"],"fixture_protection_unverified")
        self.assertEqual(project(p,dict(rec,symbol="XAUTUSD"),good)["entry_state"],"unknown_requires_reconciliation")
    def test_immutable_and_monotonic(self):
        p=preview()
        with TemporaryDirectory() as d:
            l=LifecycleLedger(Path(d)/"db.sqlite")
            self.assertEqual(l.reserve(p),"reserved")
            l.observe(p,fixture_receipt(p,1,"open"),[],stamp=NOW)
            l.observe(p,None,[],stamp=NOW+1)
            with self.assertRaises(ValueError): l.observe(p,fixture_receipt(p,0,"open"),[],stamp=NOW+2)
            with self.assertRaises(ValueError): l.observe(p,None,[],stamp=NOW-1)
            l.observe(p,fixture_receipt(p,3,"closed"),fixture_protections(p,3),stamp=NOW+2)
            with self.assertRaises(ValueError): l.observe(p,fixture_receipt(p,2,"open"),[],stamp=NOW+3)
            with self.assertRaises(ValueError): l.reserve(dict(p,action="SHORT"))
            with closing(l.connect()) as db:
                with self.assertRaises(sqlite3.IntegrityError): db.execute("DELETE FROM observations")
