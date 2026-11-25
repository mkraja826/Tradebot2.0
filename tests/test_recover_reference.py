import unittest
import io,json
from recover_trading.reference_history import candles
from recover_trading.price_audit import audit,affected_events,correlations
class ReferenceTests(unittest.TestCase):
    def test_readonly_reference(self):
        class Response(io.BytesIO):
            pass
        class Opener:
            def open(self,req,timeout):
                assert req.get_method()=="GET"
                assert req.full_url.startswith("https://api.india.delta.exchange/v2/history/candles?")
                assert not req.has_header("Authorization")
                return Response(json.dumps({"success":True,"result":[{"time":1800000000,"open":100,"close":100,"high":101,"low":99,"volume":1}]}).encode())
        self.assertEqual(len(candles("BTCUSD","5m",1800000300,1,opener=Opener())),1)
        with self.assertRaises(ValueError):candles("unknown","5m",1800000300,1,opener=Opener())
    def test_flags_and_correlation(self):
        rows=[{"time":300,"open":100,"close":100,"high":101,"low":99},{"time":600,"open":110,"close":110,"high":120,"low":90}]
        r=audit(rows)
        self.assertEqual(r["gap_count"],1)
        self.assertIn(600,r["flagged_timestamps"])
        ev=[{"rule_id":k,"horizon_s":3600,"partition":"development","decision_at":t,"entry_at":t+300,"exit_at":t+3900,"gross_bps":t*m} for t in range(300,9000,300) for k,m in (("B01",1),("B02",-1))]
        self.assertAlmostEqual(correlations(ev)[0]["correlation"],-1)
        self.assertGreater(affected_events(ev,[600],partition="development")[0]["flagged_windows"],0)
