import re,unittest
from recover_trading.dashboard import STATIC
class IntelligenceWorkspaceTests(unittest.TestCase):
    def test_intelligence_controls_and_panels(self):
        html=(STATIC/"index.html").read_text()
        self.assertEqual(set(re.findall(r'data-ai-filter="([^"]+)"',html)),{"all","entry","management"})
        for name in ("aiDirection","aiScoreTrack","aiTimeline","aiLatestContent","aiActiveRules","aiFamilyScores"):
            self.assertEqual(html.count('id="'+name+'"'),1)
