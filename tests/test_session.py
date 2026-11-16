import unittest
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from tradebot.session import SessionPhase, session_phase

IST = ZoneInfo("Asia/Kolkata")


class TestSession(unittest.TestCase):
    def test_winter_open(self):
        self.assertEqual(session_phase(datetime(2026, 11, 17, 20, 0, tzinfo=IST)),
                         SessionPhase.TRADING)

    def test_summer_open(self):
        self.assertEqual(session_phase(datetime(2026, 7, 1, 19, 0, tzinfo=IST)),
                         SessionPhase.TRADING)

    def test_winter_flatten(self):
        self.assertEqual(session_phase(datetime(2026, 11, 18, 2, 20, tzinfo=IST)),
                         SessionPhase.FLATTEN)

    def test_winter_close(self):
        self.assertEqual(session_phase(datetime(2026, 11, 18, 2, 30, tzinfo=IST)),
                         SessionPhase.CLOSED)

    def test_weekend(self):
        self.assertEqual(session_phase(datetime(2026, 11, 21, 20, 0, tzinfo=IST)),
                         SessionPhase.CLOSED)

    def test_naive_rejected(self):
        with self.assertRaises(ValueError):
            session_phase(datetime(2026, 11, 17, 20, 0))
