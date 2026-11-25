import unittest
from recover_trading.broker import safe_exchange_code
from recover_trading.submission_audit import audit
class SubmissionAuditTests(unittest.TestCase):
    def test_documented_code_and_privacy(self):
        self.assertEqual(safe_exchange_code({"error":{"code":"position_bracket_exist_or_invalid_data","context":{"secret":"private"}}}),"position_bracket_exist_or_invalid_data")
        self.assertEqual(safe_exchange_code({"error":{"code":"private_value"}}),"unrecognized_exchange_code")
    def test_position_and_tick_audit(self):
        contexts={"a":{"demo_account":{"product":{"id":1,"tick_size":"0.1"},"positions":[{"product_id":1,"size":-50}]}}}
        i={"product_id":1,"side":"sell","stop_loss":101.1,"take_profit":99}
        r=audit([("a","unknown",i,{"exchange_code":"position_bracket_exist_or_invalid_data"}),("b","acknowledged",i,{})],contexts)
        self.assertEqual(r["by_decision_position"]["unknown"],{"short":1})
        self.assertEqual(r["by_decision_position"]["acknowledged"],{"unavailable":1})
        self.assertEqual(r["misaligned_brackets"],0)
        self.assertEqual(r["unknown_tick_alignment"],1)
        self.assertEqual(r["execution_effect"],"none")

    def test_product_scoped_position_without_row_id(self):
        from recover_trading.submission_audit import position_state
        self.assertEqual(position_state({"positions":[{"size":-50}]},{"id":84}),"short")
        self.assertEqual(position_state({"positions":[{"size":0}]},{"id":84}),"flat")
        self.assertEqual(position_state({"positions":[{"size":-50,"product_id":99}]},{"id":84}),"unavailable")
