from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock
from tradebot.chart_desk import ChartDesk, epoch
from tradebot.fire_execution import FireTradeStore


class ChartDeskTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.store = FireTradeStore(Path(temp.name)/"fire.sqlite")
        self.exchange = Mock()
        self.desk = ChartDesk(self.exchange, {"XAUTUSD":self.store})
        self.exchange.ticker.return_value = {
            "symbol":"XAUTUSD", "product_id":17, "mark_price":"3750", "close":"3751",
            "quotes":{"best_bid":"3749","best_ask":"3752"}, "timestamp":1795120000000000}
        self.exchange._request.return_value = {"result":{"product_id":17,"size":1,"entry_price":"3730"}}
        self.exchange.open_orders.return_value = [
            {"product_id":17,"state":"pending","bracket_order":True,"stop_order_type":"stop_loss_order",
             "side":"sell","stop_price":"3700"},
            {"product_id":27,"state":"pending","bracket_order":True,"stop_order_type":"stop_loss_order",
             "side":"sell","stop_price":"62000"}]

    def test_market_identity_and_observed_exit_levels(self):
        result = self.desk.read({"symbol":["XAUTUSD"],"summary":["1"]})
        self.assertEqual(result["quote"]["time"],1795120000)
        self.assertEqual([o["price"] for o in result["account"]["exits"]],["3700"])
        self.exchange.candles.assert_not_called()

    def test_replay_requires_confirmed_order_identity(self):
        self.exchange._request.return_value = {"result":{
            "id":9, "product_symbol":"XAUTUSD","state":"closed","unfilled_size":0,
            "average_fill_price":"3760","paid_commission":"0.01","updated_at":1795120000000000}}
        trade={"exit_order_ids":{"take_profit_order":"9"}}
        self.assertEqual(self.desk.replay("XAUTUSD",trade)["take_profit_order"]["price"],"3760")
        self.assertNotIn("take_profit_order",self.desk.replay("BTCUSD",trade))
        self.exchange._request.return_value["result"]["state"]="cancelled"
        self.assertNotIn("take_profit_order",self.desk.replay("XAUTUSD",trade))

    def test_unavailable_account_preserves_market_quote(self):
        self.exchange._request.side_effect = TimeoutError()
        result=self.desk.read({"symbol":["XAUTUSD"],"summary":["1"]})
        self.assertEqual(result["quote"]["price"],"3751")
        self.assertNotIn("account",result)
