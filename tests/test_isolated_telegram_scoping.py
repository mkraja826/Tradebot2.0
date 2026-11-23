"""Offline isolated BTC/GOLD Telegram alert routing; never sends messages."""
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from tradebot.telegram_alerts import _message_for
from tradebot.offhost_alerts import AlertRelayError


class IsolatedTelegramTests(unittest.TestCase):
    def setUp(self):
        self.rows=[(1,123456,"watchdog_emergency_flat_verified",
                    "opened","critical")]

    def test_btc_and_gold_incidents_are_identified_without_secrets(self):
        for account in ("BTC","GOLD"):
            with self.subTest(account=account):
                with patch.dict(os.environ,{"TRADEBOT_ALERT_ACCOUNT":account}):
                    message=_message_for(self.rows)
                self.assertIn("Isolated subaccount: "+account,message)
                self.assertIn("watchdog_emergency_flat_verified",message)
                self.assertNotIn("API_KEY",message)

    def test_unknown_account_label_is_not_reported(self):
        with patch.dict(os.environ,{"TRADEBOT_ALERT_ACCOUNT":"main-live"}):
            with self.assertRaisesRegex(AlertRelayError,
                                        "telegram_account_scope_unverified"):
                _message_for(self.rows)

    def test_legacy_alerts_keep_their_original_heading(self):
        with patch.dict(os.environ,{},clear=True):
            value=_message_for(self.rows)
        self.assertNotIn("Isolated subaccount:",value)
        self.assertIn("Delta India DEMO",value)

    def test_isolated_runner_never_loads_delta_keys_or_main_monitor(self):
        script=Path(__file__).resolve().parents[1]/"ops"/"run_isolated_demo_telegram.sh"
        content=script.read_text()
        self.assertIn("btc-isolated",content)
        self.assertIn("gold-isolated",content)
        self.assertIn("unset DELTA_DEMO_API_KEY DELTA_DEMO_API_SECRET",content)
        self.assertIn('TOKEN_FILE="$HOME/.config/tradebot2/telegram.env"',content)
        self.assertIn('--data-dir "$DATA"',content)
        self.assertNotIn('--data-dir "$PROJECT/data" ',content)


if __name__=="__main__":
    unittest.main()
