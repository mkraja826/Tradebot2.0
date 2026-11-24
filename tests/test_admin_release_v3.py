import unittest,zipfile,json
from pathlib import Path
from tempfile import TemporaryDirectory
from tradebot.admin_release_v3 import archive,verify
class ReleaseTests(unittest.TestCase):
    def test_archive_integrity(self):
        with TemporaryDirectory() as d:
            root=Path(d)
            r=archive(root);i=r['release_id']
            p=root/'policy-review-candidates'/(i+'.zip')
            self.assertFalse(r['activation_authorized'])
            self.assertTrue(verify(p,expected_id=i))
            with self.assertRaises(ValueError):verify(p,expected_id='0'*64)
            with zipfile.ZipFile(p) as z:members={n:z.read(n) for n in z.namelist()}
            members['equity_policy_v3.py']+=b'# changed'
            q=root/'tampered.zip'
            with zipfile.ZipFile(q,'w') as z:
                for n,b in members.items():z.writestr(n,b)
            with self.assertRaisesRegex(ValueError,'file_integrity'):verify(q,expected_id=i)
