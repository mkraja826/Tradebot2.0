import unittest
from test_m18_text_wire_v3 import TextWireTests
from tradebot.messages_wire_v3 import build,parse,MODEL
from tradebot.ai_replay_v3 import wait_fixture
from tradebot.opportunity_journal_v3 import canonical
class MessagesTests(unittest.TestCase):
    def test_exact_identity(self):
        w=TextWireTests().make("BTCUSD")
        w["body"]["model"]=MODEL
        body=build(w)
        r={"type":"message","role":"assistant","model":MODEL,"stop_reason":"end_turn","content":[{"type":"text","text":canonical(wait_fixture(w["request"]))}]}
        self.assertEqual(parse(r,w,body)["action"],"WAIT")
        for patch in ({"model":"other"},{"model":None},{"stop_reason":"max_tokens"},{"content":[{"type":"tool_use"}]}):
            with self.assertRaises(ValueError):parse(dict(r,**patch),w,body)
        with self.assertRaises(ValueError):parse(r,w,dict(body,max_tokens=2048))
