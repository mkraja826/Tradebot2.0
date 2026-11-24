import unittest,json
from tempfile import TemporaryDirectory
from pathlib import Path
from tradebot.opportunity_journal_v3 import OpportunityJournal
from tradebot.product_context_v3 import product_spec,account_unavailable
from tradebot.model_wire_v3 import build_request,parse_fixture,catalogue_status,MODEL_IDS
from tradebot.ai_replay_v3 import wait_fixture
from test_opportunity_scanner_v3 import scan,ctx,sig,NOW

def raw(s):
    return dict(id=84 if s=="BTCUSD" else 181689,symbol=s,contract_type="perpetual_futures",
        state="live",trading_status="operational",contract_unit_currency="BTC" if s=="BTCUSD" else "XAUT",
        quoting_asset={"symbol":"USD"},settling_asset={"symbol":"USD"},
        contract_value="0.001",tick_size="0.1",initial_margin="0.5",maintenance_margin="0.25")
class WireTests(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        j=OpportunityJournal(Path(self.tmp.name)/"j.sqlite")
        self.b=j.record(scan(),ctx())
        self.g=j.record(scan("XAUTUSD",[sig("G01")]),ctx("XAUTUSD"))
    def wire(self,event):
        return build_request(event,product_spec(raw(event["symbol"]),event["symbol"],NOW),now=NOW)
    def test_product_validation(self):
        for s in MODEL_IDS:
            p=product_spec(raw(s),s,NOW)
            self.assertEqual(p["contract_value"],"0.001")
            self.assertIsNone(p["max_leverage"])
            self.assertFalse(account_unavailable(s)["signed_account_verified"])
        for key,val in (("symbol","XAUTUSD"),("tick_size","NaN"),("state","closed"),("contract_unit_currency","XAUT")):
            with self.assertRaises(ValueError): product_spec(dict(raw("BTCUSD"),**{key:val}),"BTCUSD",NOW)
    def test_model_routes(self):
        result=catalogue_status({"data":[{"id":MODEL_IDS["BTCUSD"]}]})
        self.assertTrue(result["BTCUSD"]["available"])
        self.assertFalse(result["XAUTUSD"]["available"])
        for e in (self.b,self.g):
            w=self.wire(e)
            self.assertEqual(w["body"]["model"],MODEL_IDS[e["symbol"]])
            self.assertEqual(w["request"]["payload"]["account"]["status"],"unavailable")
            self.assertFalse(w["execution_authorized"])
    def test_freshness_and_isolation(self):
        with self.assertRaises(ValueError): build_request(self.b,product_spec(raw("XAUTUSD"),"XAUTUSD",NOW),now=NOW)
        with self.assertRaises(ValueError): build_request(self.b,product_spec(raw("BTCUSD"),"BTCUSD",NOW),now=NOW+151)
    def test_provider_envelope(self):
        w=self.wire(self.b); r=wait_fixture(w["request"])
        envelope={"model":MODEL_IDS["BTCUSD"],"choices":[{"finish_reason":"stop","message":{"content":json.dumps(r)}}]}
        self.assertEqual(parse_fixture(envelope,w)["action"],"WAIT")
        with self.assertRaises(ValueError): parse_fixture(dict(envelope,model=MODEL_IDS["XAUTUSD"]),w)
        envelope["choices"][0]["finish_reason"]="length"
        with self.assertRaises(ValueError): parse_fixture(envelope,w)
        envelope["choices"][0]["finish_reason"]="stop"
        envelope["choices"][0]["message"]["content"]='{"action":"WAIT","action":"LONG"}'
        with self.assertRaises(ValueError): parse_fixture(envelope,w)
