import re,unittest
from recover_trading.dashboard import STATIC
class WorkspaceTests(unittest.TestCase):
    def test_unique_ids_and_existing_references(self):
        html=(STATIC/"index.html").read_text();js=(STATIC/"app.js").read_text()
        ids=re.findall(r'\bid="([^"]+)"',html)
        self.assertEqual(len(ids),len(set(ids)))
        self.assertTrue(set(re.findall(r'\$\("([^"]+)"\)',js))<=set(ids))
        self.assertEqual(len(re.findall(r'<section class="panel\b',html)),45)
    def test_routes_and_market_controls(self):
        html=(STATIC/"index.html").read_text()
        self.assertEqual(set(re.findall(r'data-page="([^"]+)"',html)),set(re.findall(r'data-workspace="([^"]+)"',html)))
        self.assertEqual(len(re.findall(r'data-workspace="([^"]+)"',html)),8)
        self.assertEqual(set(re.findall(r'data-symbol="([^"]+)"',html)),{"BTCUSD","XAUTUSD"})

    def test_history_explorer_controls_and_scope(self):
        html=(STATIC/"index.html").read_text();js=(STATIC/"app.js").read_text()
        history=html.split('data-workspace="history"',1)[1].split('data-workspace="intelligence"',1)[0]
        for identifier in ("historyQuery","historySide","historyReset","historyCounts","orders","fills"):
            self.assertIn(f'id="{identifier}"',history)
        self.assertIn('historyView(m);',js)
        self.assertIn('addEventListener("input",refreshHistoryView)',js)
        self.assertIn('addEventListener("change",refreshHistoryView)',js)
        self.assertIn('No orders match these filters',js)
        self.assertIn('No fills match these filters',js)

    def test_trade_inspector_is_read_only_and_market_scoped(self):
        html=(STATIC/"index.html").read_text();js=(STATIC/"app.js").read_text()
        history=html.split('data-workspace="history"',1)[1].split('data-workspace="intelligence"',1)[0]
        for identifier in ("inspectorEpisode","inspectorStatus","inspectorContent"):
            self.assertIn(f'id="{identifier}"',history)
        self.assertIn("historyView(m);inspectorView(m);",js)
        self.assertIn("inspectorMarket!==m.symbol",js)
        self.assertIn("x.id===e.decision_id",js)
        self.assertIn("matches.length!==1",js)
        self.assertIn("Final observed exit fill",js)

    def test_learning_intelligence_workspace(self):
        html=(STATIC/"index.html").read_text();js=(STATIC/"app.js").read_text()
        learning=html.split('data-workspace="learning"',1)[1].split('data-workspace="health"',1)[0]
        for identifier in ("learnSummary","learnMetrics","learnDistribution","learnPatterns","learnHypotheses","learnComparison","learnOutcomeFilter","learnFilterCount"):
            self.assertIn(f'id="{identifier}"',learning)
        self.assertIn("learnIntelligence(m);",js)
        self.assertIn("x.prospective_nonoverlap_samples",js)
        self.assertIn("x.mean_alternative_net_bps",js)
        self.assertIn("r.outcome===filter",js)
        self.assertIn("followups below remain unfiltered",js)
