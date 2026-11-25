import tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from recover_trading.kimi_review import packet,validate,run,read

class KimiReviewTests(unittest.TestCase):
    def test_redaction_and_reference(self):
        data={"status":"observed","lessons":[{"symbol":"BTCUSD","decision_id":"private","closed":"date","outcome":"loss","net_before_funding":"-2","api_key":"secret"}]}
        p=packet("BTCUSD",data)
        self.assertNotIn("private",str(p));self.assertNotIn("secret",str(p))
        review={"summary":"Small sample","lessons":[{"kind":"observation","text":"One loss","evidence_ids":["R1"]}],"limitations":["No causal evidence"]}
        self.assertEqual(validate(review,p),review)
        with tempfile.TemporaryDirectory() as d,patch("recover_trading.kimi_review.outcomes",return_value=data):
            calls=[]
            def reviewer(e,k):calls.append(1);return review
            self.assertEqual(run(d,d,"BTCUSD",4000,"fake",reviewer)["status"],"reviewed")
            self.assertEqual(run(d,d,"BTCUSD",8000,"fake",reviewer)["status"],"reviewed")
            self.assertEqual(len(calls),1)
            self.assertEqual(read(d,"BTCUSD")["review"],review)
        review["lessons"][0]["evidence_ids"]=["R99"]
        with self.assertRaises(ValueError):validate(review,p)
