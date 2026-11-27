import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock,patch
from recover_trading.engine import Journal
from recover_trading.gold_v2_episode import EpisodeJournal
from recover_trading.gold_v2_runtime import config,owner_lock,bind_journal,verify_start

def env():
    return dict(RECOVER_GOLD_V2_ACCOUNT="123",RECOVER_BTC_ACCOUNT="456",RECOVER_MAIN_ACCOUNT="789",
        RECOVER_GOLD_DEMO_KEY="g",RECOVER_GOLD_DEMO_SECRET="s",
        RECOVER_BTC_DEMO_KEY="b",RECOVER_BTC_DEMO_SECRET="t",RECOVER_GOLD_V2_ALLOCATION=".1")

class RuntimeTests(unittest.TestCase):
    def test_config(self):
        self.assertEqual(config(env())[:3],("123","456","789"))
    def test_main_overlap(self):
        with self.assertRaises(ValueError):config(dict(env(),RECOVER_MAIN_ACCOUNT="123"))
    def test_key_overlap(self):
        with self.assertRaises(ValueError):config(dict(env(),RECOVER_BTC_DEMO_KEY="g"))
    def test_owner_lock(self):
        with TemporaryDirectory() as d:
            with owner_lock(d,"123"):
                with self.assertRaises(BlockingIOError):
                    with owner_lock(d,"123"):pass
                with owner_lock(d,"456"):pass
            with owner_lock(d,"123"):pass
    def test_bind_journal(self):
        with TemporaryDirectory() as d:
            root=Path(d);o=Journal(root/"orders.sqlite");e=EpisodeJournal(root/"episodes.sqlite")
            try:
                bind_journal(o,e,"123");bind_journal(o,e,"123")
                with self.assertRaises(ValueError):bind_journal(o,e,"456")
            finally:o.close();e.close()
    def test_unbound_existing_orders(self):
        from recover_trading.engine import OrderIntent
        with TemporaryDirectory() as d:
            root=Path(d);o=Journal(root/"orders.sqlite");e=EpisodeJournal(root/"episodes.sqlite")
            try:
                o.begin("legacy","XAUTUSD",OrderIntent(42,"buy",1))
                with self.assertRaises(ValueError):bind_journal(o,e,"123")
            finally:o.close();e.close()
    def test_no_adoption_of_legacy_position(self):
        broker=Mock();btc=Mock();btc.wallet.return_value={"result":[{"asset_symbol":"USD","user_id":456}]}
        with patch("recover_trading.gold_v2_runtime.verify_account"),patch("recover_trading.gold_v2_runtime.outstanding",return_value=[]),patch("recover_trading.gold_v2_runtime.account_snapshot",return_value={"position_state":"long","bracket_state":"matching_legs_observed"}):
            with self.assertRaisesRegex(ValueError,"legacy_or_unowned_position"):
                verify_start(broker,btc,"123","456","789",Mock())
    def test_start_flat(self):
        broker=Mock();btc=Mock();btc.wallet.return_value={"result":[{"asset_symbol":"USD","user_id":456}]}
        with patch("recover_trading.gold_v2_runtime.verify_account"),patch("recover_trading.gold_v2_runtime.outstanding",return_value=[]),patch("recover_trading.gold_v2_runtime.account_snapshot",return_value={"position_state":"flat","bracket_state":"no_orders_observed"}):
            self.assertEqual(verify_start(broker,btc,"123","456","789",Mock())["execution_effect"],"none")
