import io,json,unittest
from urllib.error import HTTPError,URLError
from recover_trading.broker import DeltaDemo,BrokerError,error_detail
from recover_trading.decision import validate,ProposalValidationError
from recover_trading.direction import compact_context
class Opener:
    def __init__(self,error):self.error=error
    def open(self,*args,**kw):raise self.error
class BrokerDiagnosticsTests(unittest.TestCase):
    def test_http_error_allowlisted_code(self):
        err=HTTPError("https://private.invalid",400,"private",{},io.BytesIO(b'{"success":false,"error":{"code":"insufficient_margin","context":"secret"}}'))
        with self.assertRaises(BrokerError) as e:DeltaDemo(opener=Opener(err)).ticker("BTCUSD")
        self.assertEqual(error_detail(e.exception),{"error":"BrokerError","category":"http_error","http_status":400,"exchange_code":"insufficient_margin"})
    def test_unknown_code_not_leaked(self):
        err=HTTPError("https://private.invalid",404,"private",{},io.BytesIO(b'{"error":{"code":"secret"}}'))
        with self.assertRaises(BrokerError) as e:DeltaDemo(opener=Opener(err)).ticker("BTCUSD")
        self.assertEqual(e.exception.exchange_code,"unrecognized_exchange_code")
        self.assertNotIn("secret",str(error_detail(e.exception)))
    def test_timeout_classified(self):
        with self.assertRaises(BrokerError) as e:DeltaDemo(opener=Opener(URLError(TimeoutError()))).ticker("BTCUSD")
        self.assertEqual(e.exception.category,"timeout")
    def test_proposal_code_and_context_trim(self):
        with self.assertRaises(ProposalValidationError) as e:validate({"symbol":"wrong"},"BTCUSD")
        self.assertEqual(e.exception.code,"proposal_symbol")
        original={"demo_account":{"product":{"settling_asset":{"symbol":"USD","precision":8,"networks":["discard"]},"contract_value":"0.001"},"wallets":[{"balance":"5"}]}}
        out=compact_context(original)
        self.assertEqual(out["demo_account"]["product"]["settling_asset"],{"symbol":"USD","precision":8})
        self.assertEqual(out["demo_account"]["wallets"],original["demo_account"]["wallets"])
        self.assertIn("networks",original["demo_account"]["product"]["settling_asset"])
