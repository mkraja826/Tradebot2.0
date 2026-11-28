import unittest
from datetime import datetime,timezone,timedelta
from recover_trading.gold_v2_fed_fallback import parse,apply_fallback,SERIES

TODAY=datetime(2026,11,28,tzinfo=timezone.utc)
NOW=TODAY.timestamp()
def csv(key,age=1):
    rel,_,ident,_=SERIES[key]
    lines=[f"Unique Identifier,{rel}/{rel}/{ident}",f"Time Period,{ident}"]
    for i in range(7):
        d=TODAY.date()-timedelta(days=age+6-i)
        lines.append(f"{d},{100+i if key=='broad_dollar' else 1+i/10}")
    return "\n".join(lines)
class FedFallbackTests(unittest.TestCase):
    def test_dollar_exact_series(self):
        x=parse(csv("broad_dollar"),"broad_dollar",NOW)
        self.assertEqual(len(x["observations"]),6)
        self.assertAlmostEqual(x["change"],100*(106/101-1))
    def test_real_yield_bps(self):
        x=parse(csv("real_yield"),"real_yield",NOW)
        self.assertAlmostEqual(x["change"],50)
    def test_stale_and_wrong_identifier(self):
        with self.assertRaisesRegex(ValueError,"stale"):parse(csv("broad_dollar",age=9),"broad_dollar",NOW)
        with self.assertRaisesRegex(ValueError,"wrong_identifier"):parse(csv("real_yield").replace("H15/H15/","H10/H10/"),"real_yield",NOW)
    def test_fallback_preserves_primary_and_provenance(self):
        refs={"fed_official":{k:parse(csv(k),k,NOW) for k in SERIES}}
        m,s=apply_fallback({"broad_dollar_5obs_pct":None,"real_yield_5obs_bp":7},refs,NOW)
        self.assertEqual(m["real_yield_5obs_bp"],7)
        self.assertIn("broad_dollar",s)
        self.assertNotIn("real_yield",s)
        self.assertEqual(apply_fallback({"broad_dollar_5obs_pct":None},refs,NOW+22201)[0]["broad_dollar_5obs_pct"],None)
