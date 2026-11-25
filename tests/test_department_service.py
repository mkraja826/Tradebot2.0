"""Exercise actual service startup and management routing without network or orders."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from contextlib import ExitStack
from recover_trading import service

class DepartmentServiceTests(unittest.TestCase):
    def test_cli_default_and_opt_in(self):
        with tempfile.TemporaryDirectory() as tmp:
            for extra in ([], ["--learning-journal", str(Path(tmp)/"learning.sqlite")]):
                with self.subTest(extra=extra):
                    fake=Mock()
                    fake.symbol="BTCUSD"
                    with patch.object(sys,"argv",["recover","--once","--symbol","BTCUSD","--data-dir",tmp]+extra), patch.object(service,"MarketService",return_value=fake) as factory, patch.object(service,"configured_models",return_value={"BTCUSD":""}), patch.object(service.signal,"signal"):
                        self.assertEqual(service.main(),0)
                        kw=factory.call_args.kwargs
                        self.assertEqual(kw["learning_journal"],extra[1] if extra else None)
                        self.assertFalse(kw["manage_demo"])
                        self.assertIsNone(kw["management_model"])
                        self.assertIsNone(kw["broker"])
                        fake.run.assert_called_once()

    def test_entry_management_handoff(self):
        for symbol in ("BTCUSD","XAUTUSD"):
            for state in ("flat","open","unknown"):
                with self.subTest(symbol=symbol,state=state), tempfile.TemporaryDirectory() as tmp, ExitStack() as stack:
                    report={"symbol":symbol,"as_of":300,"status":"ok","signals":[]}
                    scan=Mock(return_value={"markets":{symbol:report}})
                    svc=service.MarketService(symbol,tmp,model="fake",provider=Mock(),broker=Mock(),
                        scan=scan,output=Mock(),manage_demo=True,
                        learning_journal=Path(tmp)/"missing.sqlite")
                    svc.executor=Mock()
                    svc.decisions=Mock()
                    svc.lifecycle=Mock()
                    svc.lifecycle.refresh.return_value=({"positions":[]}
                        if state=="flat" else {"positions":[{"size":1}]} if state=="open" else {})
                    svc.management=Mock()
                    svc.management.capture.return_value=({"status":"prepared","id":"test","context_bytes":10}
                        if state=="open" else {"status":"no_fresh_position"})
                    svc.management.evaluate.return_value={"status":"proposed"}
                    svc.management_executor=Mock()
                    svc.management_executor.reconcile_pending.return_value={"checked":0,"resolved":0,"execution_effect":"none"}
                    svc.management_executor.execute.return_value={"status":"verified","attempted":True}
                    svc.research=Mock()
                    svc.research.record.return_value={}
                    svc.planner=Mock()
                    svc.planner.record.return_value={}
                    for name in ("diagnostics","direction_for","opportunity","load_reference","packet","open_excursion_report"):
                        stack.enter_context(patch.object(service,name,return_value={}))
                    entry=stack.enter_context(patch.object(service,"evaluate_and_execute",return_value={"status":"test_entry"}))
                    result=svc.cycle()
                    capture_args=svc.management.capture.call_args.args
                    self.assertEqual(capture_args[2],"tb-deepseek-v4-pro")
                    self.assertEqual(result["entry_model"],"fake")
                    self.assertEqual(result["management_model"],"tb-deepseek-v4-pro")
                    packet=capture_args[0]["department_learning"]
                    self.assertEqual(packet["symbol"],symbol)
                    self.assertEqual(packet["status"],"unavailable")
                    if state=="flat":
                        entry.assert_called_once()
                        self.assertEqual(entry.call_args.args[0]["department_learning"],packet)
                        self.assertEqual(entry.call_args.args[3],{symbol:"fake"})
                        svc.management_executor.execute.assert_not_called()
                    elif state=="open":
                        entry.assert_not_called()
                        svc.management_executor.execute.assert_called_once_with(symbol,"test",enabled=True)
                        self.assertEqual(result["status"],"position_management_cycle")
                    else:
                        entry.assert_not_called()
                        svc.management_executor.execute.assert_not_called()
                        self.assertEqual(result["status"],"position_management_cycle")

    def test_management_model_override_is_separate(self):
        with tempfile.TemporaryDirectory() as tmp:
            for symbol in ("BTCUSD","XAUTUSD"):
                with self.subTest(symbol=symbol):
                    plain=service.MarketService(symbol,tmp,model="entry-model")
                    self.assertEqual(plain.management_model,"entry-model")
                    self.assertFalse(plain.manage_demo)
                    active=service.MarketService(symbol,tmp,model="entry-model",manage_demo=True,
                        management_model="test-management-model")
                    self.assertEqual(active.model,"entry-model")
                    self.assertEqual(active.management_model,"test-management-model")

    def test_cli_management_model_selection(self):
        with tempfile.TemporaryDirectory() as tmp:
            for extra,env,expected in (
                ([],{},service.DEFAULT_MANAGEMENT_MODEL),
                ([],{"RECOVER_MANAGEMENT_MODEL":"configured-manager"},"configured-manager"),
                (["--management-model","explicit-manager"],{"RECOVER_MANAGEMENT_MODEL":"configured-manager"},"explicit-manager")):
                with self.subTest(extra=extra,env=env):
                    fake=Mock()
                    fake.symbol="BTCUSD"
                    with patch.dict(service.os.environ,{"TB_API_KEY":"fixture","RECOVER_BTC_DEMO_KEY":"key","RECOVER_BTC_DEMO_SECRET":"secret",**env},clear=True), patch.object(sys,"argv",["recover","--once","--symbol","BTCUSD","--data-dir",tmp,"--execute-demo","--manage-demo"]+extra), patch.object(service,"MarketService",return_value=fake) as factory, patch.object(service,"configured_models",return_value={"BTCUSD":"entry-model"}), patch.object(service,"DeltaDemo"), patch.object(service,"Provider"), patch.object(service.signal,"signal"):
                        self.assertEqual(service.main(),0)
                        kw=factory.call_args.kwargs
                        self.assertEqual(kw["model"],"entry-model")
                        self.assertEqual(kw["management_model"],expected)
                        self.assertTrue(kw["manage_demo"])
