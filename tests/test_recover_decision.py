import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
from recover_trading.decision import DecisionJournal,evaluate_report,validate


class Fake:
    calls=0
    def propose(self,model,context):
        self.calls+=1
        return {"symbol":context["symbol"],"action":"trade","side":"sell","size":900,
                "leverage":20,"entry_reference":100,"stop_loss":110,"take_profit":98,
                "reason":"fixture"}


def report(symbol="BTCUSD",stamp=1800000000):
    return {"symbol":symbol,"as_of":stamp,"signals":[{"id":"B01" if symbol=="BTCUSD" else "G01",
             "frame":"5m" if symbol=="BTCUSD" else "1h","direction":"SHORT","closed_at":stamp}],
             "market_context":{"frames":{},"context":{},"quotes":{}}}


class DecisionTests(unittest.TestCase):
    def test_one_signal_triggers_and_restarts_do_not_repeat(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/"db.sqlite"
            provider=Fake()
            models={"BTCUSD":"test","XAUTUSD":"test-gold"}
            r=evaluate_report(report(),DecisionJournal(p),provider,models)
            self.assertEqual(r["status"],"proposed")
            self.assertEqual(r["proposal"]["size"],900)
            self.assertEqual(evaluate_report(report(),DecisionJournal(p),provider,models)["status"],"already_evaluated")
            self.assertEqual(evaluate_report(report("XAUTUSD"),DecisionJournal(p),provider,models)["status"],"proposed")
            self.assertEqual(evaluate_report(report(stamp=1800000300),DecisionJournal(p),provider,models)["status"],"proposed")
            self.assertEqual(provider.calls,3)

    def test_no_signal_no_call(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Fake()
            r=report();r["signals"]=[]
            self.assertEqual(evaluate_report(r,DecisionJournal(Path(tmp)/"db"),p,{"BTCUSD":"test"})["ai_calls"],0)
            self.assertEqual(p.calls,0)

    def test_invalid_proposal_is_not_replayed(self):
        class Bad(Fake):
            def propose(self,model,context):
                self.calls+=1
                return {"symbol":"XAUTUSD","action":"trade"}
        with tempfile.TemporaryDirectory() as tmp:
            j=DecisionJournal(Path(tmp)/"db");p=Bad()
            self.assertEqual(evaluate_report(report(),j,p,{"BTCUSD":"test"})["status"],"failed")
            self.assertEqual(evaluate_report(report(),j,p,{"BTCUSD":"test"})["status"],"already_evaluated")
            self.assertEqual(p.calls,1)

    def test_no_trade_valid_and_invalid_quantity(self):
        self.assertEqual(validate({"symbol":"BTCUSD","action":"no_trade","reason":"fixture"},"BTCUSD")["action"],"no_trade")
        raw=Fake().propose("test",{"symbol":"BTCUSD"});raw["size"]=True
        with self.assertRaises(ValueError):validate(raw,"BTCUSD")

    def test_failed_provider_request_recovers_once_using_fresh_context(self):
        class Flaky(Fake):
            def propose(self,model,context):
                self.calls+=1
                if self.calls==1: raise TimeoutError()
                return {"symbol":context["symbol"],"action":"no_trade","reason":"recovered"}
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"db"; p=Flaky(); models={"BTCUSD":"test"}
            with patch("recover_trading.decision.time.time",return_value=1800000000):
                a=evaluate_report(report(),DecisionJournal(path),p,models)
                self.assertEqual(a["status"],"failed")
            with patch("recover_trading.decision.time.time",return_value=1800000179):
                self.assertEqual(evaluate_report(report(),DecisionJournal(path),p,models)["status"],"already_evaluated")
            with patch("recover_trading.decision.time.time",return_value=1800000180):
                b=evaluate_report(report(),DecisionJournal(path),p,models)
                self.assertEqual(b["status"],"proposed")
                self.assertNotEqual(a["decision_id"],b["decision_id"])
            with patch("recover_trading.decision.time.time",return_value=1800001000):
                self.assertEqual(evaluate_report(report(),DecisionJournal(path),p,models)["status"],"already_evaluated")
            self.assertEqual(p.calls,2)

    def test_repeated_timeout_never_retries_indefinitely(self):
        class Flaky(Fake):
            def propose(self,model,context):
                self.calls+=1
                raise TimeoutError()
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"db"; p=Flaky(); models={"BTCUSD":"test"}
            for now,expected in [(1800000000,"failed"),(1800000180,"failed"),(1800001000,"already_evaluated")]:
                with patch("recover_trading.decision.time.time",return_value=now):
                    self.assertEqual(evaluate_report(report(),DecisionJournal(path),p,models)["status"],expected)
            self.assertEqual(p.calls,2)
