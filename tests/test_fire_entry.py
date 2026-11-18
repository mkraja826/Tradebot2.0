import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock
from uuid import uuid4

from tradebot.delta import DeltaError
from tradebot.fire_entry import FireEntries


class FireEntryTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.db = Path(directory.name) / "entries.db"
        self.exchange = Mock()
        self.exchange.btc_positions.return_value = []
        self.entries = FireEntries(self.db, self.exchange)
        self.press = uuid4().hex
        self.plan = dict(direction="LONG", contracts=2, stop_loss="90", take_profit="115")
        self.snapshot = dict(environment="delta-india-demo", position_contracts=0,
                             core=dict(best_bid="99", best_ask="101", ticker=dict(
                                 product_id=7, symbol="BTCUSD", contract_type="perpetual_futures")))
        self.order = dict(product_id=7, id=10, client_order_id=self.press,
                          state="closed", unfilled_size=0)

    def submit(self):
        return self.entries.submit_first_entry(self.press, self.snapshot, self.plan)

    def test_duplicate_after_restart(self):
        self.exchange._request.return_value = {"result": self.order}
        first = self.submit()
        self.assertEqual(first["status"], "filled")
        payload = self.exchange._request.call_args.kwargs["payload"]
        self.assertEqual((payload["side"], payload["size"], payload["bracket_stop_loss_price"],
                          payload["bracket_take_profit_price"]), ("buy", 2, "90", "115"))
        self.entries = FireEntries(self.db, self.exchange)
        self.assertEqual(self.submit(), first)
        self.exchange._request.assert_called_once()

    def test_lost_reply_reconciles_without_reposting(self):
        self.exchange._request.side_effect = TimeoutError()
        self.assertEqual(self.submit()["status"], "unconfirmed")
        with self.assertRaises(DeltaError):
            self.entries.submit_first_entry(uuid4().hex, self.snapshot, self.plan)
        self.exchange.order_by_client_id.return_value = self.order
        self.assertEqual(self.entries.reconcile(self.press)["status"], "filled")
        self.exchange._request.assert_called_once()

    def test_changed_position(self):
        self.exchange.btc_positions.return_value = [{"product_id": 7, "size": "-2"}]
        with self.assertRaises(DeltaError):
            self.submit()
        self.exchange._request.assert_not_called()
