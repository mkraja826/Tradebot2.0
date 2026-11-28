import unittest
from datetime import datetime,timezone
from recover_trading.gold_v2_fed_fallback import parse_preview,collect,url,parse
NOW=datetime(2026,11,28,tzinfo=timezone.utc).timestamp()
ID="H15/H15/RIFLGFCY10_XII_N.B"
def preview():
    rows=[("2026-11-26","ND"),("2026-11-25","2.73"),("2026-11-24","2.79"),("2026-11-23","2.79"),
          ("2026-11-20","2.77"),("2026-11-19","2.88"),("2026-11-18","2.88")]
    return ("<html><p>"+ID+"</p><p>Percent Per Year</p><table><tr><th>Unique ID</th><th>Time Period</th><th>Value</th></tr>"+
        "".join(f"<tr><td>{ID}</td><td>{d}</td><td>{v}</td></tr>" for d,v in rows)+
        "</table><script>fake observations must be ignored</script></html>")
class FedPreviewTests(unittest.TestCase):
    def test_actual_preview_shape_and_holiday(self):
        x=parse_preview(preview(),"real_yield",NOW)
        self.assertEqual(x["observations"][-1],{"date":"2026-11-25","value":2.73})
        self.assertEqual(len(x["observations"]),6)
        self.assertAlmostEqual(x["change"],-15)
        self.assertEqual(x["source"],"federal_reserve_board_h15_preview_as_observed")
    def test_wrong_unit_or_series_rejected(self):
        for bad in (preview().replace("Percent Per Year","Index"),preview().replace(ID,"H15/H15/OTHER")):
            with self.assertRaises(ValueError):parse_preview(bad,"real_yield",NOW)
    def test_published_unit_spelling(self):
        self.assertAlmostEqual(parse_preview(preview().replace("Percent Per Year","Percent:_Per_Year"),"real_yield",NOW)["change"],-15)
    def test_csv_metadata_punctuation(self):
        ident="JRXWTFB_N.B"
        raw="Unique Identifier: ,H10/H10/"+ident+"\nTime Period,"+ident+"\n"+"\n".join(f"2026-11-{d},{100+d}" for d in (18,19,20,23,24,25))
        self.assertEqual(parse(raw,"broad_dollar",NOW)["observations"][-1]["value"],125)
        with self.assertRaises(ValueError):parse(raw.replace("H10/H10/","H15/H15/"),"broad_dollar",NOW)
    def test_stale_preview_rejected(self):
        with self.assertRaises(ValueError):parse_preview(preview(),"real_yield",NOW+7*86400)
    def test_collect_uses_preview_endpoint(self):
        x=collect(reader=lambda u:preview() if "Preview.aspx" in u else "",clock=lambda:NOW)
        self.assertEqual(x["real_yield"]["status"],"ready")
        self.assertEqual(x["broad_dollar"]["status"],"unavailable")
        self.assertIn("Preview.aspx",url("real_yield"))
