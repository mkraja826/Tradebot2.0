import unittest,sqlite3
from contextlib import closing
from tempfile import TemporaryDirectory
from pathlib import Path
from tradebot.admin_release_v3 import archive
from tradebot.admin_audit_v3 import record,inspect
class AdminAuditTests(unittest.TestCase):
    def test_chain_and_tamper(self):
        with TemporaryDirectory() as d:
            i=archive(d)['release_id']
            a=record(d,i);b=record(d,i)
            self.assertEqual(b['events'],2)
            self.assertNotEqual(a['head_sha'],b['head_sha'])
            self.assertEqual(inspect(d)['head_sha'],b['head_sha'])
            self.assertFalse(inspect(d)['activation_authorized'])
            with closing(sqlite3.connect(Path(d)/'admin-review-audit.sqlite')) as db,db:
                db.execute('UPDATE events SET sha=? WHERE seq=1',('0'*64,))
            with self.assertRaisesRegex(ValueError,'audit_integrity'):inspect(d)
            with self.assertRaisesRegex(ValueError,'audit_integrity'):record(d,i)
    def test_invalid_release(self):
        with TemporaryDirectory() as d:
            with self.assertRaises(ValueError):record(d,'../invalid')
            self.assertFalse((Path(d)/'admin-review-audit.sqlite').exists())
