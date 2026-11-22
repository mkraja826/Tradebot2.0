"""Owner-declared mode never becomes exchange-signed trading authorization."""
import json
import tempfile
from pathlib import Path
from datetime import datetime, timedelta, timezone
import unittest
from tradebot.delta import DEMO_API
from tradebot.operator_account_mode import read_manual_mode

NOW=datetime(2026,11,23,tzinfo=timezone.utc)
class Fake:
    base_url=DEMO_API
    allow_orders=False
    user_id=501
    def _request(self,method,path,*,auth=False):
        assert (method,path,auth)==("GET","/v2/users/trading_preferences",True)
        return {"result":{"user_id":self.user_id}}

class OperatorSettingsTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/"mode.json"
        self.client=Fake()
        self.settings=dict(schema=1,environment="delta-india-demo",account="main",
                           mode="isolated",
                           declared_at=NOW.isoformat())
    def write(self,mode=0o600):
        self.path.write_text(json.dumps(self.settings))
        self.path.chmod(mode)
    def check(self):
        return read_manual_mode(self.client,path=self.path,now=NOW)
    def test_account_must_match_and_no_trade_release(self):
        self.write()
        r=self.check()
        self.assertEqual(r["status"],"owner_declared_not_broker_verified")
        self.assertEqual(r["declared_mode"],"isolated")
        for field in ("broker_margin_verified","trade_authorized","safe_to_enable_fire"):
            self.assertFalse(r[field])
    def test_file_mode_and_link_rejected(self):
        self.write(0o644)
        self.assertEqual(self.check()["status"],"not_configured")
        self.path.unlink()
        other=Path(self.tmp.name)/"other.json"
        other.write_text(json.dumps(self.settings))
        other.chmod(0o600)
        self.path.symlink_to(other)
        self.assertEqual(self.check()["status"],"not_configured")
    def test_age_restricted(self):
        self.settings["declared_at"]=(NOW-timedelta(days=31)).isoformat()
        self.write()
        self.assertEqual(self.check()["status"],"owner_declaration_expired")
    def test_wrong_environment_or_mode_rejected(self):
        for key,value in (("environment","live"),("mode","cross"),("account","sub")):
            old=self.settings[key]
            self.settings[key]=value
            self.write()
            self.assertEqual(self.check()["status"],"not_configured")
            self.settings[key]=old
    def test_trade_client_rejected(self):
        self.write()
        self.client.allow_orders=True
        self.assertEqual(self.check()["status"],"not_configured")
        authorized_for_demo = read_manual_mode(
            self.client,path=self.path,now=NOW,allow_order_client=True)
        self.assertEqual(authorized_for_demo["status"],
                         "owner_declared_not_broker_verified")
        self.assertFalse(authorized_for_demo["broker_margin_verified"])
        self.assertFalse(authorized_for_demo["trade_authorized"])
        self.client.base_url = "https://api.india.delta.exchange"
        self.assertEqual(read_manual_mode(
            self.client,path=self.path,now=NOW,allow_order_client=True)["status"],
            "not_configured")
