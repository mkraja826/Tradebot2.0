"""Offline tests for one-time end-to-end encrypted GitHub Actions VM transfer."""
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import x25519

import tradebot.sealed_transfer as transfer


def keypair():
    private = x25519.X25519PrivateKey.generate()
    private_bytes = private.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption())
    public_bytes = private.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw)
    return private_bytes, transfer.PREFIX + transfer._encode(public_bytes)


DUMMY_VALUES = {
    "DELTA_DEMO_API_KEY": "test-demo-key-123",
    "DELTA_DEMO_API_SECRET": "test-secret' with whitespace",
    "TB_API_KEY": "test-topbilling-model-key",
}


class SealedTransferTests(unittest.TestCase):
    def test_encryption_round_trip_never_outputs_plaintext(self):
        secret_key, public = keypair()
        package = transfer._seal(DUMMY_VALUES, public)
        serialized = json.dumps(package)
        for value in DUMMY_VALUES.values():
            self.assertNotIn(value, serialized)
        self.assertEqual(transfer._unseal(package, secret_key), DUMMY_VALUES)
        self.assertEqual(package["format"], transfer.FORMAT)

    def test_randomized_ciphertext_each_time(self):
        secret_key, public = keypair()
        a = transfer._seal(DUMMY_VALUES, public)
        b = transfer._seal(DUMMY_VALUES, public)
        self.assertNotEqual(a["ciphertext"], b["ciphertext"])
        self.assertEqual(transfer._unseal(a, secret_key), DUMMY_VALUES)

    def test_wrong_vm_key_cannot_decrypt(self):
        _, public_a = keypair()
        key_b, _ = keypair()
        package = transfer._seal(DUMMY_VALUES, public_a)
        with self.assertRaises(transfer.TransferError):
            transfer._unseal(package, key_b)

    def test_authenticated_ciphertext_rejects_tampering(self):
        key, public = keypair()
        package = transfer._seal(DUMMY_VALUES, public)
        encrypted = bytearray(transfer._decode_any(package["ciphertext"]))
        encrypted[0] ^= 0x01
        package["ciphertext"] = transfer._encode(bytes(encrypted))
        with self.assertRaises(transfer.TransferError):
            transfer._unseal(package, key)

    def test_import_creates_private_file_and_deletes_transfer_key(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            secret = root / ".config/tradebot2/transfer-x25519.key"
            env_file = root / ".config/tradebot2/keys.env"
            sealed_file = root / "ops/sealed/secrets.enc.json"
            secret.parent.mkdir(parents=True)
            sealed_file.parent.mkdir(parents=True)
            private, pub = keypair()
            secret.write_bytes(private)
            sealed_file.write_text(json.dumps(transfer._seal(DUMMY_VALUES, pub)))
            with patch.object(transfer, "PRIVATE_KEY_FILE", secret), \
                 patch.object(transfer, "SEALED_FILE", sealed_file), \
                 patch.object(transfer, "ENV_FILE", env_file):
                with redirect_stdout(io.StringIO()) as output:
                    transfer.import_once()
            self.assertFalse(secret.exists())
            self.assertEqual(env_file.stat().st_mode & 0o777, 0o600)
            self.assertEqual(env_file.parent.stat().st_mode & 0o777, 0o700)
            exported = env_file.read_text()
            self.assertIn("export ENABLE_DEMO_ORDERS=false\n", exported)
            self.assertIn("export TB_MODEL=tb-deepseek-v4-1-flash\n", exported)
            self.assertIn("DELTA_DEMO_API_SECRET=", exported)
            self.assertNotIn(DUMMY_VALUES["DELTA_DEMO_API_SECRET"], output.getvalue())

    def test_rejects_existing_credentials_file_without_overwriting(self):
        with tempfile.TemporaryDirectory() as t:
            path = Path(t) / "keys.env"
            path.write_text("original")
            with patch.object(transfer, "ENV_FILE", path):
                with self.assertRaises(transfer.TransferError):
                    transfer.import_once()
            self.assertEqual(path.read_text(), "original")

    def test_missing_public_key_rejected(self):
        with self.assertRaises(transfer.TransferError):
            transfer._seal(DUMMY_VALUES, "wrongkey")

    def test_only_three_approved_secrets_expected(self):
        self.assertEqual(transfer.ENV_NAMES,
                         ("DELTA_DEMO_API_KEY", "DELTA_DEMO_API_SECRET", "TB_API_KEY"))


if __name__ == "__main__":
    unittest.main()
