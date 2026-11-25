import re,unittest
from recover_trading.dashboard import STATIC
class WorkspaceTests(unittest.TestCase):
    def test_unique_ids_and_existing_references(self):
        html=(STATIC/"index.html").read_text();js=(STATIC/"app.js").read_text()
        ids=re.findall(r'\bid="([^"]+)"',html)
        self.assertEqual(len(ids),len(set(ids)))
        self.assertTrue(set(re.findall(r'\$\("([^"]+)"\)',js))<=set(ids))
        self.assertEqual(len(re.findall(r'<section class="panel\b',html)),42)
    def test_routes_and_market_controls(self):
        html=(STATIC/"index.html").read_text()
        self.assertEqual(set(re.findall(r'data-page="([^"]+)"',html)),set(re.findall(r'data-workspace="([^"]+)"',html)))
        self.assertEqual(len(re.findall(r'data-workspace="([^"]+)"',html)),8)
        self.assertEqual(set(re.findall(r'data-symbol="([^"]+)"',html)),{"BTCUSD","XAUTUSD"})
