import unittest,json,tempfile
from pathlib import Path
from datetime import datetime,timezone
from tradebot.m20_subaccount_baseline_v3 import project,create,SOURCE,TARGET
class BaselineTests(unittest.TestCase):
 def fixture(self):
    at=datetime.fromtimestamp(1000,timezone.utc).isoformat()
    return dict(mode="subaccount_evidence_only",checked_at=1000,parent_equity_included=False,execution_authorized=False,orders_submitted=0,paid_ai_requests=0,markets={s:dict(window_end=at,status="complete_window",subaccount=l,signed_identity_verified=True,signed_wallet_receipt_verified=True,counts={"unclassified":0},snapshot_equity_usd="100") for s,l in (("BTCUSD","BTC"),("XAUTUSD","GOLD"))})
 def test_scope(self):
    r=project(json.dumps(self.fixture()).encode(),1001)
    self.assertFalse(r["historical_checkpoint_replaced"])
    self.assertFalse(r["execution_authorized"])
    self.assertEqual(r["markets"]["BTCUSD"]["historical_loss_status"],"not_reconciled")
 def test_stale_or_unverified(self):
    with self.assertRaises(ValueError):project(json.dumps(self.fixture()).encode(),1100)
    f=self.fixture();f["markets"]["BTCUSD"]["signed_identity_verified"]=False
    with self.assertRaises(ValueError):project(json.dumps(f).encode(),1001)
 def test_no_overwrite(self):
    with tempfile.TemporaryDirectory() as d:
        p=Path(d)/SOURCE;p.write_text(json.dumps(self.fixture()));p.chmod(0o600)
        create(d,clock=lambda:1001)
        self.assertEqual((Path(d)/TARGET).stat().st_mode&0o777,0o600)
        with self.assertRaises(FileExistsError):create(d,clock=lambda:1002)
