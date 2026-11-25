"""Exercise actual service startup and management routing without network or orders."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from recover_trading import service

class DepartmentServiceTests(unittest.TestCase):
    def test_cli_default_and_opt_in(self):
        with tempfile.TemporaryDirectory() as tmp:
            for extra in ([], ["--learning-journal", str(Path(tmp)/"learning.sqlite")]):
                with self.subTest(extra=extra):
                    fake=Mock()
                    fake.symbol="BTCUSD"
                    with patch.object(sys,"argv",["recover","--once","--symbol","BTCUSD","--data-dir",tmp]+extra), patch.object(service,"MarketService",return_value=fake) as factory, patch.object(service,"configured_models",return_value={"BTCUSD":""}), patch.object(service.signal,"signal"):
                        self.assertEqual(service.main(),0)
                        kw=factory.call_args.kwargs
                        self.assertEqual(kw["learning_journal"],extra[1] if extra else None)
                        self.assertFalse(kw["manage_demo"])
                        self.assertIsNone(kw["broker"])
                        fake.run.assert_called_once()
