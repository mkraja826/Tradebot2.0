import unittest

from tradebot.delta import DeltaDemo, DeltaError


class Pages(DeltaDemo):
    def __init__(self, pages):
        super().__init__("demo", "secret")
        self.pages = pages
        self.calls = []

    def _request(self, method, path, *, params=None, payload=None, auth=False):
        self.calls.append({"method": method, "path": path,
                           "params": params, "auth": auth})
        cursor = (params or {}).get("after")
        return self.pages.get(cursor, {"result": [], "meta": {}})


class PaginationTests(unittest.TestCase):
    def test_open_orders_paginates_to_the_end(self):
        client = Pages({
            None: {"result": [{"id": 1, "product_symbol": "BTCUSD"}],
                   "meta": {"after": "c2"}},
            "c2": {"result": [{"id": 2, "product_symbol": "BTCUSD"}],
                   "meta": {"after": None}},
        })
        orders = client.open_orders()
        self.assertEqual(len(orders), 2)
        self.assertEqual(client.calls[0]["params"]["page_size"], 50)
        self.assertEqual(client.calls[1]["params"]["after"], "c2")
        self.assertTrue(all(x["auth"] for x in client.calls))

    def test_open_order_cursor_loop_fails(self):
        client = Pages({
            None: {"result": [], "meta": {"after": "c1"}},
            "c1": {"result": [], "meta": {"after": "c1"}},
        })
        with self.assertRaises(DeltaError):
            client.open_orders()

    def test_open_orders_limit_fails_not_silent(self):
        client = Pages({None: {"result": [],
                               "meta": {"after": "c1"}}})
        with self.assertRaises(DeltaError):
            client.open_orders(max_pages=1)

    def test_btc_fills_filters_and_paginates(self):
        client = Pages({
            None: {"result": [
                {"id": "a", "product_symbol": "BTCUSD"},
                {"id": "ignored", "product_symbol": "ETHUSD"},
            ], "meta": {"after": "c2"}},
            "c2": {"result": [
                {"id": "b", "product_symbol": "P-BTC-90000-271126"}
            ], "meta": {"after": None}},
        })
        fills = client.btc_fills(start_time_us=1000, end_time_us=2000)
        self.assertEqual([x["id"] for x in fills], ["a", "b"])
        self.assertEqual(client.calls[0]["path"], "/v2/fills")
        self.assertEqual(client.calls[0]["params"]["page_size"], 50)
        self.assertTrue(client.calls[0]["auth"])

    def test_no_truncated_fill_summary(self):
        client = Pages({
            None: {"result": [], "meta": {"after": "c1"}},
        })
        with self.assertRaises(DeltaError):
            client.btc_fills(start_time_us=1, end_time_us=2, max_pages=1)

    def test_invalid_fill_window_fails(self):
        client = Pages({})
        with self.assertRaises(ValueError):
            client.btc_fills(start_time_us=200, end_time_us=100)
        self.assertEqual(client.calls, [])


if __name__ == "__main__":
    unittest.main()
