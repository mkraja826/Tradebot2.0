import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from recover_trading.tb2_intelligence_tools import register

class FakeMCP:
    def __init__(self):self.tools={}
    def tool(self):
        def add(f):self.tools[f.__name__]=f;return f
        return add

class TB2IntelligenceToolsTests(unittest.TestCase):
    def test_registration_and_missing_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);m=FakeMCP()
            register(m,data_dir=p/"demo",learning_dir=p/"learning")
            self.assertEqual(len(m.tools),9)
            self.assertFalse(m.tools["research_status"]()["deployment_access"])
            self.assertEqual(m.tools["saved_research_validation"]()["status"],"audit_unavailable")
            self.assertFalse((p/"demo").exists())
    def test_bounded_output_and_symbol_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            m=FakeMCP();register(m,data_dir=tmp,learning_dir=tmp)
            with patch("recover_trading.trade_intelligence.report",return_value={"execution_effect":"none","trades":list(range(30))}):
                x=m.tools["trade_intelligence_report"]("BTCUSD",3)
                self.assertEqual(x["trades"],[27,28,29])
                self.assertEqual(x["available_items"],30)
            with self.assertRaises(ValueError):m.tools["trade_intelligence_report"]("../other",3)
            with self.assertRaises(ValueError):m.tools["trade_intelligence_report"]("BTCUSD",100)
    def test_future_window_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            m=FakeMCP();register(m,data_dir=tmp,learning_dir=tmp)
            with self.assertRaises(ValueError):m.tools["trading_cost_report"]("BTCUSD",0,int(time.time())+1)
    def test_saved_report_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/"audit.json"
            p.write_text(json.dumps({"version":"research-validation-v1","execution_effect":"none","status":"review_required",
                "snapshot_finished_utc":int(time.time()),"unknown_field":"not passed"}))
            m=FakeMCP();register(m,data_dir=tmp,learning_dir=tmp,audit_file=p)
            r=m.tools["saved_research_validation"]()
            self.assertEqual(r["status"],"review_required")
            self.assertNotIn("unknown_field",r)
