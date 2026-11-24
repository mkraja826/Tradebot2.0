import unittest,json,threading
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.request import urlopen,Request
from urllib.error import HTTPError
from http.server import HTTPServer
from tradebot.dashboard_snapshot_v3 import snapshot
from tradebot.dashboard_server_v3 import handler
NOW=1800000000
class DashboardTests(unittest.TestCase):
    def test_missing_stale_and_fresh(self):
        with TemporaryDirectory() as d:
            p=Path(d)
            self.assertEqual(snapshot(p,now=NOW)["sources"]["scanner"]["state"],"unavailable")
            def put(t):
                (p/"position-monitor-status.json").write_text(json.dumps({"checked_at":t,"markets":{"BTCUSD":{"current":{"status":"flat_observed","positions":[]}}}}))
            put(NOW-151)
            r=snapshot(p,now=NOW)
            self.assertEqual(r["sources"]["position"]["state"],"stale")
            self.assertEqual(r["markets"]["BTCUSD"]["position"]["status"],"unknown")
            put(NOW)
            self.assertEqual(snapshot(p,now=NOW)["markets"]["BTCUSD"]["position"]["status"],"flat_observed")
            put(NOW+1)
            self.assertEqual(snapshot(p,now=NOW)["sources"]["position"]["state"],"unavailable")
    def test_read_only_http(self):
        with TemporaryDirectory() as d:
            server=HTTPServer(("127.0.0.1",0),handler(d))
            thread=threading.Thread(target=server.serve_forever,daemon=True); thread.start()
            try:
                url="http://127.0.0.1:"+str(server.server_port)
                with urlopen(url+"/") as r:
                    self.assertIn(b"Tradebot3.0",r.read())
                    self.assertEqual(r.headers["Cache-Control"],"no-store")
                with urlopen(url+"/api/status") as r:
                    x=json.load(r); self.assertFalse(x["execution_authorized"])
                for req in (Request(url+"/api/fire",method="POST"),Request(url+"/../etc/passwd")):
                    with self.assertRaises(HTTPError): urlopen(req)
            finally:
                server.shutdown(); server.server_close(); thread.join()
