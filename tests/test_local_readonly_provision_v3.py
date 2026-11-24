import unittest,os
from tempfile import TemporaryDirectory
from pathlib import Path
from tradebot.local_readonly_provision_v3 import save,load,validate,FILENAME
def dummy():
    return {s:{"key":"fixture-key","secret":"fixture-secret"} for s in ("BTCUSD","XAUTUSD","parent")}|{"provider":{"key":"fixture-provider"}}
class ProvisionTests(unittest.TestCase):
    def test_create_reuse_rotation(self):
        with TemporaryDirectory() as d:
            p=Path(d)/"config"
            a=dummy()
            save(p,a)
            self.assertEqual(p.stat().st_mode&0o777,0o700)
            self.assertEqual((p/FILENAME).stat().st_mode&0o777,0o600)
            self.assertEqual(load(p),a)
            with self.assertRaises(FileExistsError): save(p,a)
            a["provider"]["key"]="fixture-rotated"
            save(p,a,replace=True)
            self.assertEqual(load(p),a)
    def test_permissions_and_links(self):
        with TemporaryDirectory() as d:
            p=Path(d)/"config"
            save(p,dummy())
            f=p/FILENAME
            f.chmod(0o644)
            with self.assertRaises(ValueError): load(p)
            f.chmod(0o600)
            link=p/"link"
            os.link(f,link)
            with self.assertRaises(ValueError): load(p)
            link.unlink()
            f.unlink()
            f.symlink_to("/dev/null")
            with self.assertRaises(OSError): load(p)
            with self.assertRaises(ValueError): save(p,dummy(),replace=True)
            alias=Path(d)/"alias";alias.symlink_to(p,target_is_directory=True)
            with self.assertRaises(ValueError): load(alias)
    def test_missing_and_invalid(self):
        with TemporaryDirectory() as d:
            p=Path(d)/"config"
            with self.assertRaises(FileNotFoundError): load(p)
            a=dummy();a["BTCUSD"]["secret"]=""
            with self.assertRaises(ValueError): save(p,a)
            self.assertFalse(p.exists())
