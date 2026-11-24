import unittest
from datetime import datetime,timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from tradebot.position_observer_v3 import view
from tradebot.position_journal_v3 import PositionJournal
from tradebot.position_monitor_v3 import tick
NOW=1795500000
def account(s="BTCUSD",t=NOW,positions=None,orders=0):
    return dict(symbol=s,subaccount="BTC" if s=="BTCUSD" else "GOLD",signed_account_verified=True,
                broker_checked_at=datetime.fromtimestamp(t,timezone.utc).isoformat(),
                positions=positions or [],open_order_count=orders,halted=False)
def pos(s="BTCUSD",side="LONG"):
    return dict(symbol=s,size="1" if side=="LONG" else "-1",side=side,entry="100",mark="101",
                protection=dict(status="signed_pending_bracket",source="signed_pending_broker_orders",
                stop_loss="95" if side=="LONG" else "105",take_profit="105" if side=="LONG" else "95"))
class PositionTests(unittest.TestCase):
    def test_views(self):
        for s in ("BTCUSD","XAUTUSD"):
            for side in ("LONG","SHORT"):
                a=account(s,positions=[pos(s,side)],orders=2)
                self.assertEqual(view(s,a,now=NOW)["status"],"open_protection_reported")
                a["positions"][0]["protection"]["stop_loss"]="100"
                self.assertEqual(view(s,a,now=NOW)["status"],"open_protection_unverified")
        self.assertEqual(view("BTCUSD",account(),now=NOW)["status"],"flat_observed")
        self.assertEqual(view("BTCUSD",account(orders=1),now=NOW)["status"],"flat_orders_present")
    def test_stale_and_wrong_identity(self):
        for a in ({},account(t=NOW-61),account("XAUTUSD"),account(positions=[pos("XAUTUSD")]),account(positions=[pos()]*10)):
            self.assertEqual(view("BTCUSD",a,now=NOW)["status"],"unknown")
    def test_journal_recovery_and_unsettled(self):
        with TemporaryDirectory() as d:
            p=Path(d)/"p.sqlite"; j=PositionJournal(p)
            a=view("BTCUSD",account(),now=NOW); self.assertEqual(j.record(a),"initial_observation")
            b=view("BTCUSD",account(t=NOW+1,positions=[pos()],orders=2),now=NOW+1)
            self.assertEqual(j.record(b),"position_appeared")
            j=PositionJournal(p); self.assertEqual(j.record(b),"duplicate_or_older")
            self.assertEqual(j.record(a),"duplicate_or_older")
            self.assertEqual(j.record(view("BTCUSD",{},now=NOW+2)),"unknown_not_recorded")
            self.assertEqual(j.last("BTCUSD"),b)
            c=view("BTCUSD",account(t=NOW+3),now=NOW+3)
            self.assertEqual(j.record(c),"position_disappeared_unsettled")
            self.assertFalse(j.last("BTCUSD")["settlement_verified"])
            self.assertEqual(j.counts()["BTCUSD"],3)
    def test_independent_monitor(self):
        with TemporaryDirectory() as d:
            root=Path(d); marker=root/"scanner-status.json"; marker.write_text("unchanged")
            result=tick(root,reader=lambda:{"BTCUSD":account()},clock=lambda:NOW)
            self.assertEqual(result["markets"]["BTCUSD"]["current"]["status"],"flat_observed")
            self.assertEqual(result["markets"]["XAUTUSD"]["current"]["status"],"unknown")
            self.assertEqual(marker.read_text(),"unchanged")
            self.assertFalse(result["scanner_control"])
            self.assertEqual(result["orders_submitted"],0)
