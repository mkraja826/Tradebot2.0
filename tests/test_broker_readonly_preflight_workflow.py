"""Offline assertions that remote broker preflight cannot execute a trade."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "broker-readonly-preflight.yml"
PROBE = ROOT / "src" / "tradebot" / "fire_leverage_probe.py"


class SignedBrokerPreflightWorkflowTests(unittest.TestCase):
    def test_isolated_single_main_push_or_manual_repeat(self):
        source = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("branches: [main]", source)
        self.assertIn('".github/workflows/broker-readonly-preflight.yml"', source)
        self.assertIn("workflow_dispatch:", source)
        self.assertIn("permissions:\n  contents: read", source)
        self.assertIn("github.repository == 'mkraja826/Tradebot2.0'", source)
        self.assertIn("github.ref == 'refs/heads/main'", source)

    def test_get_only_non_authorizing_broker_audit(self):
        source = WORKFLOW.read_text(encoding="utf-8")
        probe = PROBE.read_text(encoding="utf-8")
        self.assertIn("python -m tradebot.fire_leverage_probe", source)
        self.assertIn("allow_orders=False", probe)
        self.assertIn('"safe_to_enable_fire": False', probe)
        self.assertIn('"trade_authorized": False', probe)
        self.assertIn('"safe_to_deploy": False', probe)
        self.assertIn("FULL_ACCOUNT_TWO_SWEEPS_PROVEN: false", source)
        self.assertIn("WALLET_RECONCILIATION_COMPLETE: false", source)
        self.assertIn("TRADING_ENABLED: false", source)
        for forbidden in (
            "fire_demo(", "tradebot.fire_demo", "POST /v2/orders",
            "systemctl", "ssh ", "scp ", "wrangler",
            "TRADEBOT_FIRE_DEMO_EXECUTION: \"true\"",
            "TRADEBOT_ARMED_ORDERS: \"true\"",
            "cancel_order", "place_order", "open_position", "close_position",
            "strategy_request", "deepseek", "gpt_",
        ):
            self.assertNotIn(forbidden, source)

    def test_secrets_are_never_dumped_or_written_to_files(self):
        source = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("secrets.DELTA_DEMO_API_KEY", source)
        self.assertIn("secrets.DELTA_DEMO_API_SECRET", source)
        self.assertIn("set +x", source)
        self.assertIn("persist-credentials: false", source)
        for bad in ("printenv", "env |", "cat .env", "echo $DELTA_", "tee ",
                    "upload-artifact", "actions/cache", "git push"):
            self.assertNotIn(bad, source)


if __name__ == "__main__":
    unittest.main()
