"""Gold must have its own genuine initial equity history, never BTC's."""
from datetime import datetime,timedelta,timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import unittest

from equity_fixtures import receipt_for
from tradebot.btc_supervised_session import isolated_btc_signed_genesis_window
from tradebot.btc_supervised_equity_guard import SupervisedSessionEquityGuard
from tradebot.portfolio_equity_guard import PortfolioEquityGuard, EquityRiskError


class GoldSignedGenesisTests(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)/"gold-isolated"
        self.root.mkdir()
        self.db=self.root/"fire-equity-risk.sqlite"
        self.t=datetime(2026,11,23,5,0,tzinfo=timezone.utc)
        self.now=self.t+timedelta(minutes=1)
        PortfolioEquityGuard(self.db).observe_verified_read(
            "100",receipt_for("100",self.t),now=self.t)
        self.health={
            "daily_checkpoint":"missed_window",
            "weekly_checkpoint":"missed_window",
            "database_integrity":"verified",
            "latest_receipt_status":"verified",
            "observation_status":"fresh",
            "blocking_conditions":[
                "daily_checkpoint_missed_window",
                "weekly_checkpoint_missed_window"],
            "monitoring":{
                "watchdog":"healthy","equity_collector":"healthy",
                "watchdog_age_seconds":1.0,
                "equity_collector_age_seconds":1.0,
                "alert_codes":[],
            },
        }

    def test_gold_genesis_only_under_gold_subaccount_credentials(self):
        with patch.dict("os.environ",{
                "TRADEBOT_EXPECTED_DEMO_SUBACCOUNT":"GOLD"}):
            self.assertTrue(isolated_btc_signed_genesis_window(
                self.db,self.health,self.now,account="GOLD"))
            self.assertFalse(isolated_btc_signed_genesis_window(
                self.db,self.health,self.now,account="BTC"))
            checker=SupervisedSessionEquityGuard(self.db,
                health_fn=lambda path,at:self.health,
                allow_initial_isolated_genesis=True,
                isolated_genesis_account="GOLD",
                allow_daily_loss_warning=True,
                allow_portfolio_loss_warnings=True)
            decision=checker.require_verified_read(
                "100",receipt_for("100",self.now),now=self.now)
            self.assertTrue(decision["provisional_first_day_signed_genesis"])
            self.assertFalse(decision["daily_checkpoint_verified"])
            btc_checker=SupervisedSessionEquityGuard(self.db,
                health_fn=lambda path,at:self.health,
                allow_initial_isolated_genesis=True,
                isolated_genesis_account="BTC")
            with self.assertRaises(EquityRiskError):
                btc_checker.require_verified_read(
                    "100",receipt_for("100",self.now),now=self.now)

    def test_november_24_opening_must_be_real(self):
        with patch.dict("os.environ",{
                "TRADEBOT_EXPECTED_DEMO_SUBACCOUNT":"GOLD"}):
            self.assertFalse(isolated_btc_signed_genesis_window(
                self.db,self.health,
                datetime(2026,11,24,0,0,tzinfo=timezone.utc),
                account="GOLD"))


if __name__=="__main__":
    unittest.main()
