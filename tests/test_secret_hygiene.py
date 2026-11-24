"""Prevent an accidental Top Billing live key from entering version control."""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEXT_PATHS = [
    ROOT / ".env.example",
    ROOT / "README.md",
    *sorted((ROOT / "src").rglob("*.py")),
    *sorted((ROOT / "tests").glob("*.py")),
]
LIVE_KEY_RE = re.compile(r"tb_live_[A-Za-z0-9]{16,}")


class CredentialHygieneTests(unittest.TestCase):
    def test_no_topbilling_live_key_in_committed_sources(self):
        for path in TEXT_PATHS:
            with self.subTest(path=str(path.relative_to(ROOT))):
                self.assertIsNone(
                    LIVE_KEY_RE.search(path.read_text(encoding="utf-8")),
                    "A Top Billing live credential was committed to source control",
                )

    def test_env_example_is_placeholder_only(self):
        text = (ROOT / ".env.example").read_text(encoding="utf-8")
        self.assertIn("TB_API_KEY=\n", text)
        self.assertIn("TB_MODEL=tb-deepseek-v4-1-flash", text)


if __name__ == "__main__":
    unittest.main()
