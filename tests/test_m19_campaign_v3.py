from contextlib import closing
import unittest,sqlite3
from tempfile import TemporaryDirectory
from pathlib import Path
from tradebot.m19_campaign_v3 import tick,NAME,LIMIT
from tradebot.m19_provider_shadow_v3 import Campaign
from tradebot.opportunity_journal_v3 import OpportunityJournal
from tradebot.product_context_v3 import product_spec
from test_model_wire_v3 import scan,ctx,sig,raw,NOW
from test_m19_provider_shadow_v3 import ProviderShadowTests
class CampaignTests(unittest.TestCase):
    def test_finite_campaign(self):
        with TemporaryDirectory() as d:
            root=Path(d); j=OpportunityJournal(root/"opportunities-v3.sqlite")
            specs={}
            for s,r in (("BTCUSD","B01"),("XAUTUSD","G01")):
                j.record(scan(s,[sig(r)]),ctx(s))
                specs[s]={"status":"ready","data":product_spec(raw(s),s,NOW)}
            stub=ProviderShadowTests();stub.calls=[]
            run=lambda:tick(root,transport=stub.stub,spec_reader=lambda:specs,clock=lambda:NOW)
            r=run();self.assertEqual(r["budget"]["reserved"],2)
            self.assertEqual(r["budget"]["states"],{"validated_paper_proposal":2})
            self.assertFalse(r["execution_authorized"])
            self.assertEqual(run()["budget"]["reserved"],2)
            self.assertEqual(len(stub.calls),2)
            c=Campaign(root/NAME,request_limit=LIMIT)
            for i in range(LIMIT-2):self.assertEqual(c.reserve("fixture-"+str(i),"BTCUSD",NOW,"fixture"),"reserved")
            self.assertEqual(c.reserve("overflow","BTCUSD",NOW,"fixture"),"budget_exhausted")
            self.assertEqual(run()["status"],"budget_exhausted")
            self.assertEqual(len(stub.calls),2)
            with closing(sqlite3.connect(root/NAME)) as db, db:
                with self.assertRaises(sqlite3.IntegrityError):db.execute("UPDATE requests SET state='reserved_outcome_unknown' WHERE state='validated_paper_proposal'")
    def test_no_fresh_event(self):
        with TemporaryDirectory() as d:
            root=Path(d);OpportunityJournal(root/"opportunities-v3.sqlite")
            def never(*args):raise AssertionError("unexpected dispatch")
            r=tick(root,transport=never,spec_reader=lambda:{},clock=lambda:NOW)
            self.assertEqual(r["budget"]["remaining"],LIMIT)
