"""Offline management scenarios; synthetic evidence, not model-quality backtests."""
import json
import sqlite3
import unittest
from unittest.mock import Mock
from recover_trading.exit_context import geometry
from recover_trading.management_shadow import ManagementShadow, VERSION
from recover_trading.management_lifecycle import plan

class DepartmentManagementScenarios(unittest.TestCase):
    def context(self,symbol,sign,mark,consensus,mfe):
        stop,target=(98,104) if sign==1 else (102,96)
        p={"direction":"long" if sign==1 else "short","size":10*sign,
           "entry_price":"100","mark_price":str(mark),"bracket_state":"matching_legs_observed",
           "legs":[{"type":"stop_loss_order","trigger":str(stop)},
                   {"type":"take_profit_order","trigger":str(target)}]}
        c={"version":VERSION,"symbol":symbol,"as_of":300,"position_observed":300,
           "position":p,"product":{"id":1,"tick_size":"0.1","symbol":symbol}}
        c["exit_geometry"]=geometry(p,{"mfe_bps":mfe,"mae_bps":100,"coverage":1},direction=consensus)
        return c

    def evaluate(self,c,action,**kwargs):
        raw={"symbol":c["symbol"],"action":action,"reason":"synthetic scenario",**kwargs}
        with sqlite3.connect(":memory:") as db:
            shadow=ManagementShadow(db)
            db.execute("INSERT INTO management_shadow VALUES (?,?,?,?,?,?,?,NULL)",
                       ("case",c["symbol"],1,300,"fixture","prepared",json.dumps(c)))
            db.commit()
            provider=Mock()
            provider.propose_management.return_value=raw
            outcome=shadow.evaluate("case",provider)
            provider.propose_management.assert_called_once_with("fixture",c)
            self.assertEqual(shadow.evaluate("case",provider)["status"],"not_prepared")
            self.assertEqual(provider.propose_management.call_count,1)
            self.assertEqual(outcome["execution_effect"],"none")
            return outcome

    def test_profit_retention_stop_only(self):
        for symbol in ("BTCUSD","XAUTUSD"):
            for sign in (1,-1):
                with self.subTest(symbol=symbol,sign=sign):
                    c=self.context(symbol,sign,100+sign, "SHORT" if sign==1 else "LONG", 220)
                    e=c["exit_geometry"]
                    self.assertAlmostEqual(e["current_gross_mark_return_bps"],100)
                    self.assertAlmostEqual(e["observed_excursion"]["observed_trade_peak_minus_current_mark_bps"],120)
                    self.assertEqual(e["direction_consensus_relation"],"opposed")
                    r=self.evaluate(c,"update_bracket",stop_loss=100+sign*0.5,take_profit=100+sign*4)
                    self.assertEqual(r["status"],"proposed")
                    p=plan(c,r["proposal"])
                    self.assertEqual(p["expected_size"],sign*10)
                    self.assertEqual(p["desired_triggers"]["take_profit"],100+sign*4)

    def test_losing_thesis_reduce_or_close(self):
        for symbol in ("BTCUSD","XAUTUSD"):
            for sign in (1,-1):
                with self.subTest(symbol=symbol,sign=sign):
                    c=self.context(symbol,sign,100-sign,"SHORT" if sign==1 else "LONG",10)
                    self.assertLess(c["exit_geometry"]["current_gross_mark_return_bps"],0)
                    for action,args,expected in (("reduce",{"contracts":4},sign*6),("close",{},0)):
                        r=self.evaluate(c,action,**args)
                        self.assertEqual(r["status"],"proposed")
                        self.assertEqual(plan(c,r["proposal"])["expected_size"],expected)

    def test_winner_extension_and_invalid_amendment(self):
        for symbol in ("BTCUSD","XAUTUSD"):
            for sign in (1,-1):
                with self.subTest(symbol=symbol,sign=sign):
                    c=self.context(symbol,sign,100+sign*2,"LONG" if sign==1 else "SHORT",220)
                    r=self.evaluate(c,"update_bracket",stop_loss=100-sign*2,take_profit=100+sign*6)
                    self.assertEqual(r["status"],"proposed")
                    self.assertEqual(plan(c,r["proposal"])["desired_triggers"]["stop_loss"],100-sign*2)
                    self.assertEqual(self.evaluate(c,"update_bracket",stop_loss=100,take_profit=100+sign*6)["status"],"failed")
                    self.assertEqual(self.evaluate(c,"reduce",contracts=10)["status"],"failed")
                    self.assertEqual(self.evaluate(c,"maintain")["status"],"proposed")
