"""Offline signal coverage, candle integrity and duplicate-event regression tests."""
import copy
import unittest

from tradebot.multi_strategy_signals import (
    STRATEGIES, _evaluate, scan_completed_5m,
)


def features():
    return {
        "symbol":"BTCUSD","time":1800000000,"open":100.0,
        "close":100.0,"prev_close":100.0,"high":101.0,"low":99.0,
        "prev_high":101.0,"prev_low":99.0,
        "ema20":100.0,"ema20_prev":100.0,"ema50":100.0,"ema200":100.0,
        "rsi":50.0,"rsi_prev":50.0,"adx":15.0,"plus_di":15.0,"minus_di":15.0,
        "macd":0.0,"prev_macd":0.0,"stoch":50.0,"prev_stoch":50.0,
        "rvol":None,"atr":1.0,"bb_low":98.0,"bb_mid":100.0,
        "bb_high":102.0,"bb_width":.04,
        "prev_bb_low":98.0,"prev_bb_high":102.0,"prev_bb_width":.04,
        "vwap":None,"prev_vwap":None,"range_high":105.0,"range_low":95.0,
        "retest_high":105.0,"retest_low":95.0,"true_range":2.0,
    }


def candles(n=230):
    start=1800000000
    bars=[]
    for i in range(n):
        p=100+(.3*i)
        bars.append({"time":start+i*300,"open":p-.1,"high":p+1,
                     "low":p-1,"close":p,"volume":10.0})
    return bars

class MultiStrategyTests(unittest.TestCase):
    def test_registry_has_ten_unique_independent_strategies(self):
        self.assertEqual(len(STRATEGIES),10)
        self.assertEqual(len(set(STRATEGIES)),10)

    def test_strategy_rules_cover_every_combination(self):
        cases=[
            {"ema20":103,"ema50":102,"ema200":100,"close":104,"open":103,
             "adx":26,"plus_di":30,"minus_di":10,"rsi":60,"rsi_prev":54},
            {"ema20":101,"ema20_prev":100,"ema50":99,"close":103,
             "open":102,"prev_low":99,"rsi":60,"rsi_prev":55,
             "stoch":50,"prev_stoch":40},
            {"macd":.2,"prev_macd":-.2,"adx":23,"plus_di":30,
             "minus_di":10,"rvol":1.3},
            {"close":111,"open":109,"range_high":110,
             "true_range":2.5,"rvol":1.3},
            {"prev_close":108,"retest_high":105,"low":104,
             "close":107,"open":106,"ema20":104,"ema50":101,"rvol":1.1},
            {"prev_bb_width":.02,"bb_width":.025,"bb_high":105,
             "close":106,"open":104,"rvol":1.3},
            {"adx":14,"prev_close":95,"prev_bb_low":97,
             "close":99,"open":98,"bb_low":97,
             "rsi":45,"rsi_prev":40},
            {"prev_vwap":100,"vwap":100,"prev_close":99,
             "close":102,"ema20":101,"ema50":99,"rsi":55},
            {"range_low":99,"low":98.9,"close":100.5,"open":100,
             "stoch":40,"prev_stoch":30},
            {"range_low":99,"low":98.5,"close":100.5,"open":100,
             "rsi":50,"rsi_prev":45},
        ]
        for i,changes in enumerate(cases):
            with self.subTest(strategy=STRATEGIES[i]):
                f=features()
                f.update(changes)
                actual=_evaluate(f)                matching=[s for s in actual if s["strategy_id"]==STRATEGIES[i]
                          and s["direction"]=="LONG"]
                self.assertTrue(matching, f"detector {i} did not trigger: {actual}")
                self.assertFalse(matching[0]["trade_authorized"])
                self.assertGreaterEqual(matching[0]["score"],60)

    def test_strong_and_moderate_signals_both_qualify(self):
        f=features()
        f.update({"ema20":103,"ema50":102,"ema200":100,
                  "close":104,"open":103,"adx":29,
                  "plus_di":30,"minus_di":10,
                  "rsi":60,"rsi_prev":54,"rvol":1.3})
        result=_evaluate(f)
        target=next(s for s in result if s["strategy_id"]==STRATEGIES[0])
        self.assertEqual(target["strength"],"strong")
        f["adx"]=25;f["rsi_prev"]=61;f["rvol"]=None
        target=next(s for s in _evaluate(f) if s["strategy_id"]==STRATEGIES[0])
        self.assertEqual(target["strength"],"moderate")

    def test_short_signal_is_supported(self):
        f=features()
        f.update({"ema20":97,"ema50":98,"ema200":100,
                  "close":96,"open":97,"adx":29,
                  "plus_di":10,"minus_di":30,
                  "rsi":40,"rsi_prev":47,"rvol":1.3})
        matches=[s for s in _evaluate(f) if s["strategy_id"]==STRATEGIES[0]
                 and s["direction"]=="SHORT"]
        self.assertEqual(len(matches),1)

    def test_repeat_deterministic_deduplicable_signal_id(self):
        f=features()
        f.update({"macd":1,"prev_macd":-.5,"adx":20,
                  "plus_di":30,"minus_di":10,"rvol":1.25})
        one=_evaluate(f)
        self.assertEqual(one,_evaluate(copy.deepcopy(f)))        self.assertEqual(len({x["signal_id"] for x in one}),len(one))
        f["time"]+=300
        self.assertNotEqual(one[0]["signal_id"],_evaluate(f)[0]["signal_id"])

    def test_missing_volume_cannot_confirm_volume_breakout(self):
        f=features()
        f.update({"close":111,"open":109,"range_high":110,
                  "true_range":3,"rvol":None})
        self.assertFalse(any(s["strategy_id"]==STRATEGIES[3] for s in _evaluate(f)))

    def test_closed_candle_scan_is_read_only(self):
        bars=candles()
        original=copy.deepcopy(bars)
        as_of=bars[-1]["time"]+300
        res=scan_completed_5m(bars,"BTCUSD",as_of=as_of)
        self.assertEqual(res["source"],"completed_5m_local_1_of_10")
        self.assertFalse(res["execution_authorized"])
        self.assertEqual(res["trigger_ai"],bool(res["signals"]))
        self.assertEqual(res["candidate_count"],len(res["signals"]))
        self.assertEqual(original,bars)

    def test_incomplete_stale_or_gapped_candles_rejected(self):
        bars=candles()
        now=bars[-1]["time"]+300
        for data,stamp in (
            (bars,now-1),(bars,now+900),
            (bars[:80]+bars[81:],now),
            (bars[:-1],now+3600),
        ):
            with self.subTest(length=len(data),stamp=stamp):
                with self.assertRaises(ValueError):
                    scan_completed_5m(data,"BTCUSD",as_of=stamp)

    def test_malformed_data_rejected(self):
        bars=candles()        now=bars[-1]["time"]+300
        for invalid in ({"volume":float("nan")},{"low":-5},
                        {"close":float("inf")},{"time":"not an int"}):
            copybars=copy.deepcopy(bars)
            copybars[-1].update(invalid)
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    scan_completed_5m(copybars,"BTCUSD",as_of=now)

    def test_wrong_market_or_missing_history_rejected(self):
        bars=candles()
        stamp=bars[-1]["time"]+300
        for symbol in ("BTCUSDT","GOLD","BTCUSD;DROP"):
            with self.subTest(symbol=symbol):
                with self.assertRaises(ValueError):
                    scan_completed_5m(bars,symbol,as_of=stamp)
        with self.assertRaises(ValueError):
            scan_completed_5m(bars[-100:],"XAUTUSD",as_of=stamp)

    def test_single_strategy_triggers_one_ai_evaluation_event(self):
        from unittest.mock import patch
        bars=candles()
        signal={"strategy_id":STRATEGIES[3],"direction":"LONG",
                "signal_id":"unique-candle-signal","score":70}
        with patch("tradebot.multi_strategy_signals._evaluate",return_value=[signal]):
            result=scan_completed_5m(bars,"BTCUSD",
                                     as_of=bars[-1]["time"]+300)
        self.assertTrue(result["trigger_ai"])
        self.assertEqual(result["candidate_count"],1)
        self.assertEqual(result["direction_hint"],"LONG")
        self.assertFalse(result["execution_authorized"])

    def test_opposing_signals_require_ai_conflict_resolution(self):
        from unittest.mock import patch
        bars=candles()        signals=[{"strategy_id":STRATEGIES[2],"direction":"LONG","score":70},
                 {"strategy_id":STRATEGIES[7],"direction":"SHORT","score":80}]
        with patch("tradebot.multi_strategy_signals._evaluate",return_value=signals):
            result=scan_completed_5m(bars,"BTCUSD",
                                     as_of=bars[-1]["time"]+300)
        self.assertTrue(result["trigger_ai"])
        self.assertTrue(result["conflicting_directions"])
        self.assertIsNone(result["direction_hint"])
        self.assertFalse(result["execution_authorized"])

    def test_support_reversal_does_not_use_resistance_as_support(self):
        f=features()
        f.update({"range_low":95,"range_high":150,"low":110,"close":111,
                  "open":110,"stoch":35,"prev_stoch":25,"rsi":45,"rsi_prev":40})
        matched=[s for s in _evaluate(f) if s["strategy_id"]==STRATEGIES[8]
                 and s["direction"]=="LONG"]
        self.assertFalse(matched)

    def test_missing_volume_does_not_crash(self):
        bars=candles()
        for b in bars:b["volume"]=0
        res=scan_completed_5m(bars,"XAUTUSD",as_of=bars[-1]["time"]+300)
        self.assertFalse(res["execution_authorized"])

    def test_gold_is_supported_without_changing_live_bot(self):
        bars=candles()
        result=scan_completed_5m(bars,"XAUTUSD",as_of=bars[-1]["time"]+300)
        self.assertEqual(result["symbol"],"XAUTUSD")
        self.assertFalse(result["execution_authorized"])
