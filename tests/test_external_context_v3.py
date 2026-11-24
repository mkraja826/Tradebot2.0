import unittest
from datetime import datetime,timezone
from tradebot.external_context_v3 import spot,daily,calendar
import json
NOW=datetime(2026,11,24,6,0,tzinfo=timezone.utc)
class ExternalContextTests(unittest.TestCase):
    def test_spot_timestamp(self):
        row={"price":"100","bid":"99","ask":"101","time":"2026-11-24T05:59:59Z"}
        self.assertEqual(spot(json.dumps(row),NOW)["price"],100)
        for t in ("2026-11-24T05:50:00Z","2026-11-24T06:00:01Z"):
            with self.assertRaises(ValueError): spot(json.dumps(dict(row,time=t)),NOW)
    def test_daily_no_future_or_missing(self):
        raw="observation_date,DGS10,DFII10\n2026-11-20,4.0,2.0\n2026-11-23,,2.2\n2026-11-25,9,9\n"
        d=daily(raw,("DGS10","DFII10"),NOW)
        self.assertEqual(d["DGS10"]["date"],"2026-11-20")
        self.assertEqual(d["DFII10"]["value"],2.2)
    def test_calendar_timezone(self):
        raw="BEGIN:VCALENDAR\nBEGIN:VEVENT\nDTSTART;TZID=US-Eastern:20261201T083000\nSUMMARY:Consumer Price Index\nEND:VEVENT\nEND:VCALENDAR"
        self.assertEqual(calendar(raw,NOW)[0]["utc"],"2026-12-01T13:30:00+00:00")
