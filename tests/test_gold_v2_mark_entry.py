import unittest
from recover_trading.gold_v2_mark_entry import plan_mark,prepare_mark,MARK_SOURCE,MODEL
from recover_trading.gold_v2_entry_adapter import select
from test_gold_v2_hybrid import reference,ticker,NOW
from test_gold_v2_entry_adapter import PRODUCT,WALLET,ReadBroker

def envelope(side="LONG"):
    r=reference(side);m=r.pop("strict_reference_report")
    r.update(signal_source=MARK_SOURCE,execution_eligible=False,mark_report=m)
    m.update(signal_source=MARK_SOURCE,version=MODEL,execution_eligible=False)
    return r

def run(r=None,d=None):
    return plan_mark(envelope() if r is None else r,ticker(1,100),ticker(42,110) if d is None else d,
                     PRODUCT,WALLET,reference_pid=1,allocation_fraction=.1,now=NOW)

class MarkEntryTests(unittest.TestCase):
    def test_translated_brackets(self):
        for side,sl,tp in (("LONG",106.7,116.6),("SHORT",113.3,103.4)):
            r=envelope(side);x=run(r)
            self.assertEqual(x["status"],"proposed")
            self.assertEqual((x["proposal"]["stop_loss"],x["proposal"]["take_profit"]),(sl,tp))
            self.assertEqual(x["proposal"]["leverage"],20)
            self.assertFalse(x["dispatch_supported"])
            self.assertFalse(r["execution_eligible"])
            self.assertEqual(select(r["mark_report"])[1],"reference_research_only")
    def test_conflict_and_staleness(self):
        r=envelope();r["mark_report"]["candidates"]+=envelope("SHORT")["mark_report"]["candidates"]
        self.assertEqual(run(r)["status"],"conflicting_candidates")
        self.assertEqual(run(d=ticker(42,110,NOW-31))["status"],"quote_unavailable")
    def test_wrong_model(self):
        r=envelope();r["mark_report"]["version"]="other"
        self.assertEqual(run(r)["status"],"wrong_model")
    def test_existing_position_preserved(self):
        class Open(ReadBroker):
            def positions(self,pid):return [{"product_id":pid,"size":30}]
        x,_=prepare_mark(Open(),envelope(),ticker(1,100),reference_pid=1,
                         expected_gold_account="123",allocation_fraction=.1,clock=lambda:NOW)
        self.assertEqual(x["status"],"existing_exposure")
