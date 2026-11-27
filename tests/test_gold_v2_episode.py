import unittest
from datetime import datetime,timezone
from tempfile import TemporaryDirectory
from pathlib import Path
from recover_trading.gold_v2_episode import client_id,reconcile,EpisodeJournal
from recover_trading.gold_v2_management_adapter import evaluate_episode
from recover_trading.gold_v2_engine import Bar

B=3600000
NOW=B+920
def ts(t):return datetime.fromtimestamp(t,timezone.utc).isoformat()
def fixture(partial=False,reduced=False,closed=False):
    cid=client_id(B)
    size=4 if not partial else 2
    seed={"symbol":"XAUTUSD","signal_boundary":B,"client_id":cid,"product_id":42,
          "side":"buy","size":4,"flat_verified":True,"flat_observed_at":B+1,
          "stop_loss":98,"take_profit":106,"signal_atr":1}
    receipt={"client_order_id":cid,"product_id":42,"side":"buy","size":4,
             "id":9,"state":"cancelled" if partial else "closed","reduce_only":False,
             "unfilled_size":4-size,"average_fill_price":100,
             "bracket_stop_loss_price":98,"bracket_take_profit_price":106}
    def fill(fid,oid,t,q,side,after):
        return {"id":fid,"order_id":oid,"product_id":42,"created_at":ts(t),
                "size":q,"price":100,"side":side,"new_position":{"size":after}}
    fills=[fill(1,9,B+2,1,"buy",1),fill(2,9,B+3,size-1,"buy",size)]
    reductions=[]
    if reduced or closed:
        qty=size if closed else 1
        size-=qty
        reductions=[{"id":10,"product_id":42,"side":"sell","reduce_only":True,
                     "state":"closed","size":qty,"unfilled_size":0}]
        fills.append(fill(3,10,B+400,qty,"sell",size))
    positions=[{"product_id":42,"size":size,"entry_price":100,"mark_price":102,
                "created_at":ts(B+2)}] if size else []
    orders=[{"id":i,"product_id":42,"side":"sell","state":"open",
             "stop_order_type":kind,"stop_price":price,"unfilled_size":size,
             "reduce_only":True,"bracket_order":True,"stop_trigger_method":"mark_price"}
            for i,(kind,price) in enumerate((("stop_loss_order",98),("take_profit_order",106)),1)] if size else []
    snapshot={"symbol":"XAUTUSD","observed":NOW,"positions":positions,"active_orders":orders,
              "active_orders_complete":True}
    return seed,receipt,fills,reductions,snapshot
def run(args,complete=True):return reconcile(*args,now=NOW,complete=complete)

class EpisodeTests(unittest.TestCase):
    def test_split_entry(self):
        x=run(fixture())
        self.assertEqual((x["status"],x["size"],x["first_full_bar_close"]),("owned_open",4,B+600))
    def test_cancelled_partial(self):
        x=run(fixture(partial=True))
        self.assertEqual((x["status"],x["size"]),("owned_open",2))
    def test_reduced(self):
        x=run(fixture(reduced=True))
        self.assertEqual((x["status"],x["size"],x["reduced"]),("owned_open",3,True))
    def test_closed(self):
        self.assertEqual(run(fixture(closed=True))["status"],"closed")
    def test_unattributed_reduction(self):
        a=list(fixture(reduced=True));a[3]=[]
        self.assertEqual(run(a)["status"],"unattributed_fill")
    def test_duplicate_fill(self):
        a=fixture();a[2].append(dict(a[2][0]))
        self.assertEqual(run(a)["status"],"duplicate_fill")
    def test_incomplete_history(self):
        self.assertEqual(run(fixture(),False)["status"],"fill_window_incomplete")
    def test_missing_bracket(self):
        a=fixture();a[4]["active_orders"].pop()
        self.assertEqual(run(a)["status"],"bracket_coverage_unverified")
    def test_size_mismatch(self):
        a=fixture();a[4]["positions"][0]["size"]=3
        self.assertEqual(run(a)["status"],"position_mismatch")
    def test_reduced_management(self):
        seed,receipt,fills,reductions,snapshot=fixture(reduced=True)
        report={"symbol":"XAUTUSD","status":"observed","as_of":B+900,"decision_as_of":NOW-1,
                "features":{300:{"atr":1,"ema":[101,101,101,101]}}}
        bars=[Bar(B+600,100,101.5,99.5,101,1),Bar(B+900,101,102.5,100.5,102,1)]
        x=evaluate_episode(report,snapshot,{"symbol":"XAUTUSD","id":42,"tick_size":"0.1"},
                           seed,receipt,fills,reductions,now=NOW,history=bars,complete=True)
        self.assertEqual(x["status"],"proposal_prepared")
        self.assertEqual(x["proposal"]["action"],"update_bracket")
        self.assertEqual(x["context"]["position"]["size"],3)
    def test_journal_restart(self):
        a=fixture()
        with TemporaryDirectory() as temp:
            path=Path(temp)/"episodes.sqlite"
            j=EpisodeJournal(path);cid=j.reserve(a[0])
            x=j.record(cid,*a[1:],now=NOW,complete=True);j.close()
            j=EpisodeJournal(path)
            try:
                self.assertEqual(j.reserve(a[0]),cid)
                self.assertEqual(j.record(cid,*a[1:],now=NOW,complete=True),x)
                with self.assertRaises(ValueError):
                    j.record(cid,*a[1:],now=NOW-1,complete=True)
            finally:j.close()
    def test_terminal_no_reopen(self):
        a=fixture(closed=True)
        with TemporaryDirectory() as temp:
            j=EpisodeJournal(Path(temp)/"episodes.sqlite")
            try:
                cid=j.reserve(a[0]);j.record(cid,*a[1:],now=NOW,complete=True)
                with self.assertRaises(ValueError):
                    j.record(cid,*a[1:],now=NOW+1,complete=True)
            finally:j.close()

    def test_partial_profit_proposal(self):
        seed,receipt,fills,reductions,snapshot=fixture()
        snapshot["positions"][0]["mark_price"]=103.5
        report={"symbol":"XAUTUSD","status":"observed","as_of":B+900,"decision_as_of":NOW-1,
                "features":{300:{"atr":1,"ema":[101,101,101,101]}}}
        bars=[Bar(B+600,101,102.5,100.5,102,1),Bar(B+900,102,104,101.5,103.5,1)]
        x=evaluate_episode(report,snapshot,{"symbol":"XAUTUSD","id":42,"tick_size":"0.1"},
                           seed,receipt,fills,reductions,now=NOW,history=bars,complete=True)
        self.assertEqual(x["proposal"]["action"],"reduce")
        self.assertEqual(x["proposal"]["contracts"],2)
        self.assertIn("partial profit",x["proposal"]["reason"])


    def test_terminal_entry_journal_recovery(self):
        from recover_trading.engine import Journal
        from recover_trading.execution import BracketIntent
        from recover_trading.gold_v2_recovery import synchronize_terminal_entries
        seed,receipt,fills,reductions,snapshot=fixture(closed=True)
        seed["account_id"]="123"
        with TemporaryDirectory() as temp:
            ep=EpisodeJournal(Path(temp)/"episodes.sqlite")
            orders=Journal(Path(temp)/"orders.sqlite")
            try:
                cid=ep.reserve(seed)
                orders.begin(cid,"XAUTUSD",BracketIntent(42,"buy",4,20,20,100,98,106))
                orders.finish(cid,"unknown",{"error":"timeout"})
                ep.record(cid,receipt,fills,reductions,snapshot,now=NOW,complete=True)
                self.assertEqual(synchronize_terminal_entries(orders,ep,"456"),0)
                self.assertEqual(orders.unresolved(),[cid])
                self.assertEqual(synchronize_terminal_entries(orders,ep,"123"),1)
                self.assertEqual(orders.unresolved(),[])
                self.assertEqual(synchronize_terminal_entries(orders,ep,"123"),0)
            finally:orders.close();ep.close()

    def test_terminal_recovery_rejects_wrong_intent(self):
        from recover_trading.engine import Journal
        from recover_trading.execution import BracketIntent
        from recover_trading.gold_v2_recovery import synchronize_terminal_entries
        seed,receipt,fills,reductions,snapshot=fixture(closed=True)
        seed["account_id"]="123"
        with TemporaryDirectory() as temp:
            ep=EpisodeJournal(Path(temp)/"episodes.sqlite")
            orders=Journal(Path(temp)/"orders.sqlite")
            try:
                cid=ep.reserve(seed)
                orders.begin(cid,"XAUTUSD",BracketIntent(42,"buy",5,20,20,100,98,106))
                ep.record(cid,receipt,fills,reductions,snapshot,now=NOW,complete=True)
                self.assertEqual(synchronize_terminal_entries(orders,ep,"123"),0)
                self.assertEqual(orders.unresolved(),[cid])
            finally:orders.close();ep.close()


    def test_early_exit_diagnostic_not_attribution(self):
        from unittest.mock import Mock
        from recover_trading.gold_v2_recovery import early_exit_diagnostic
        seed,receipt,fills,reductions,snapshot=fixture(closed=True)
        seed["account_id"]="123"
        receipt["user_id"]=123
        r=dict(reductions[0],user_id=123,bracket_order=True,stop_trigger_method="mark_price",
               stop_order_type="stop_loss_order",stop_price=98)
        broker=Mock();broker._request.return_value=r
        result=early_exit_diagnostic(broker,seed,receipt,fills,snapshot,now=NOW,complete=True)
        self.assertEqual(result["status"],"possible_early_protective_exit")
        self.assertFalse(result["attribution_verified"])
        self.assertEqual(reconcile(seed,receipt,fills,[],snapshot,now=NOW,complete=True)["status"],"unattributed_fill")
        r["user_id"]=456
        self.assertEqual(early_exit_diagnostic(broker,seed,receipt,fills,snapshot,now=NOW,complete=True)["status"],"protective_evidence_mismatch")

    def test_early_exit_requires_complete_history(self):
        from unittest.mock import Mock
        from recover_trading.gold_v2_recovery import early_exit_diagnostic
        seed,receipt,fills,reductions,snapshot=fixture(closed=True)
        broker=Mock()
        self.assertEqual(early_exit_diagnostic(broker,seed,receipt,fills,snapshot,now=NOW,complete=False)["status"],"incomplete_fills")
        broker._request.assert_not_called()
