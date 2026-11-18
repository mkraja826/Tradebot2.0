"""One-time GitHub Actions -> VM encrypted demo secret transfer.

The VM creates an X25519 key pair and shares ONLY the 44-character base64
public key. GitHub Actions seals the three repository secrets using an
ephemeral X25519 key, HKDF-SHA256 and AES-256-GCM. The resulting ciphertext is
stored in the public repository; it cannot be opened without the VM private
key. This is a *one-time bootstrap*, not a general key management service.

After decryption, only the user's 0600 ~/.config/tradebot2/keys.env contains
plaintext credentials. The transfer private key is deleted after a successful
import. Never log keys, plaintext or decrypted environment.
"""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import secrets
import shlex
import sys

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import x25519
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

PREFIX = "tbx1:"
FORMAT = "tradebot2-demo-sealed-v1"
CONTEXT = b"Tradebot2.0 GitHub Actions to demo VM bootstrap v1"
ENV_NAMES = ("DELTA_DEMO_API_KEY", "DELTA_DEMO_API_SECRET", "TB_API_KEY")
PUBLIC_KEY_FILE = Path("ops/recipient-public-key.txt")
SEALED_FILE = Path("ops/sealed/tradebot-demo-credentials.enc.json")
PRIVATE_KEY_FILE = Path.home() / ".config/tradebot2/transfer-x25519.key"
ENV_FILE = Path.home() / ".config/tradebot2/keys.env"


class TransferError(RuntimeError):
    """Generic errors that don't contain credentials."""


def _encode(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def _decode(encoded: str, expected_size: int) -> bytes:
    try:
        output = base64.b64decode(encoded, validate=True)
    except (ValueError, TypeError):
        raise TransferError("Invalid base64 transfer data") from None
    if len(output) != expected_size:
        raise TransferError("Unexpected transfer data length")
    return output


def _read_pubkey(text: str) -> bytes:
    text = text.strip()
    if not text.startswith(PREFIX):
        raise TransferError("Transfer public key has an invalid prefix")
    return _decode(text[len(PREFIX):], 32)


def _key_from_shared(shared: bytes, salt: bytes) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=32,
                salt=salt, info=CONTEXT).derive(shared)


def _seal(secrets_map: dict[str, str], public_key_text: str) -> dict:
    """Only returns encrypted data. Never return plaintext in exception text."""
    pub_bytes = _read_pubkey(public_key_text)
    recipient = x25519.X25519PublicKey.from_public_bytes(pub_bytes)
    ephemeral = x25519.X25519PrivateKey.generate()
    shared = ephemeral.exchange(recipient)
    salt = secrets.token_bytes(16)
    nonce = secrets.token_bytes(12)
    key = _key_from_shared(shared, salt)
    payload = json.dumps(secrets_map, separators=(",", ":")).encode("utf-8")
    encrypted = AESGCM(key).encrypt(nonce, payload, CONTEXT)
    return {
        "format": FORMAT,
        "recipient_fingerprint": hashlib.sha256(pub_bytes).hexdigest()[:16],
        "ephemeral_public_key": _encode(ephemeral.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw)),
        "salt": _encode(salt),
        "nonce": _encode(nonce),
        "ciphertext": _encode(encrypted),
    }


def _unseal(envelope: dict, private_key_bytes: bytes) -> dict[str, str]:
    if not isinstance(envelope, dict) or envelope.get("format") != FORMAT:
        raise TransferError("Unexpected transfer envelope")
    if len(private_key_bytes) != 32:
        raise TransferError("Invalid VM private transfer key")
    try:
        private = x25519.X25519PrivateKey.from_private_bytes(private_key_bytes)
        pub_bytes = private.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw)
        if hashlib.sha256(pub_bytes).hexdigest()[:16] != envelope.get("recipient_fingerprint"):
            raise TransferError("Encrypted package targets a different VM key")
        ephemeral_pub = x25519.X25519PublicKey.from_public_bytes(
            _decode(envelope["ephemeral_public_key"], 32))
        salt = _decode(envelope["salt"], 16)
        nonce = _decode(envelope["nonce"], 12)
        encrypted = _decode(envelope["ciphertext"], len(_decode_any(envelope["ciphertext"])))
        shared = private.exchange(ephemeral_pub)
        decrypted = AESGCM(_key_from_shared(shared, salt)).decrypt(
            nonce, encrypted, CONTEXT)
        body = json.loads(decrypted)
    except (InvalidTag, ValueError, TypeError, KeyError, UnicodeDecodeError,
            json.JSONDecodeError):
        raise TransferError("Decryption failed; verify your VM key and encrypted package") from None
    if not isinstance(body, dict) or set(body) != set(ENV_NAMES):
        raise TransferError("Unexpected secret names in transfer payload")
    for name in ENV_NAMES:
        value = body[name]
        if not isinstance(value, str) or not value or "\x00" in value or len(value) > 4096:
            raise TransferError("Invalid transferred secret value")
    return body


def _decode_any(text: str) -> bytes:
    if not isinstance(text, str) or len(text) > 100000:
        raise TransferError("Encrypted package is invalid or too large")
    try:
        return base64.b64decode(text, validate=True)
    except (ValueError, TypeError):
        raise TransferError("Encrypted package base64 is invalid") from None


def generate() -> None:
    PRIVATE_KEY_FILE.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(PRIVATE_KEY_FILE.parent, 0o700)
    if PRIVATE_KEY_FILE.exists():
        # Prevent accidental overwrite/re-keying before an encrypted workflow completes.
        with PRIVATE_KEY_FILE.open("rb") as handle:
            private_data = handle.read()
        if len(private_data) != 32:
            raise TransferError("Existing transfer key is invalid; do not overwrite it")
        private = x25519.X25519PrivateKey.from_private_bytes(private_data)
    elif ENV_FILE.exists():
        raise TransferError("An existing credentials file is already configured")
    else:
        private = x25519.X25519PrivateKey.generate()
        private_data = private.private_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PrivateFormat.Raw,
            encryption_algorithm=serialization.NoEncryption())
        fd = os.open(PRIVATE_KEY_FILE, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(private_data)
        except BaseException:
            PRIVATE_KEY_FILE.unlink(missing_ok=True)
            raise
    os.chmod(PRIVATE_KEY_FILE, 0o600)
    public = private.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw)
    print("VM PUBLIC KEY (safe to share; NOT the private key):")
    print(PREFIX + _encode(public))
    print("Keep the private key on this VM. Never send or screenshot its file.")


def encrypt() -> None:
    if not PUBLIC_KEY_FILE.is_file():
        raise TransferError("The VM recipient public key is not installed in GitHub yet")
    recipient = PUBLIC_KEY_FILE.read_text(encoding="ascii")
    supplied = {}
    for name in ENV_NAMES:
        val = os.environ.get(name)
        if not val or "\x00" in val or len(val) > 4096:
            raise TransferError("Required GitHub Actions secret is missing or invalid: " + name)
        supplied[name] = val
    sealed = _seal(supplied, recipient)
    SEALED_FILE.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
    SEALED_FILE.write_text(json.dumps(sealed, sort_keys=True, indent=2) + "\n",
                           encoding="utf-8")
    print("Encrypted package created: three keys, no plaintext output.")


def import_once() -> None:
    if ENV_FILE.exists():
        raise TransferError("Private credentials file already exists; refusing to overwrite")
    if not PRIVATE_KEY_FILE.is_file():
        raise TransferError("VM private transfer key not found; generate it on this VM first")
    if not SEALED_FILE.is_file():
        raise TransferError("Encrypted package missing; wait for GitHub Action, then git pull")
    if SEALED_FILE.stat().st_size > 100000:
        raise TransferError("Encrypted transfer package unexpectedly large")
    private_bytes = PRIVATE_KEY_FILE.read_bytes()
    try:
        envelope = json.loads(SEALED_FILE.read_text(encoding="utf-8"))
    except (ValueError, UnicodeDecodeError):
        raise TransferError("Encrypted transfer package is malformed") from None
    values = _unseal(envelope, private_bytes)
    ENV_FILE.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(ENV_FILE.parent, 0o700)
    fd = os.open(ENV_FILE, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            for name in ENV_NAMES:
                handle.write("export " + name + "=" + shlex.quote(values[name]) + "\n")
            handle.write("export ENABLE_DEMO_ORDERS=false\n")
            handle.write("export TB_MODEL=tb-deepseek-v4-1-flash\n")
        os.chmod(ENV_FILE, 0o600)
    except BaseException:
        ENV_FILE.unlink(missing_ok=True)
        raise
    # Destroy the one-time decryption key once the local private env is written.
    PRIVATE_KEY_FILE.unlink()
    print("SUCCESS: Three credentials saved to ~/.config/tradebot2/keys.env (0600).")
    print("The one-time VM decryption key was removed.")
    print("Demo order execution is disabled. No trades or paid AI calls made.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="One-time encrypted GitHub Actions to Tradebot demo VM credential transfer")
    parser.add_argument("action", choices=["generate", "encrypt", "import"])
    args = parser.parse_args()
    try:
        {"generate": generate, "encrypt": encrypt, "import": import_once}[args.action]()
    except (TransferError, OSError) as exc:
        # OSError may expose a pathname, but must never contain credential values.
        print("Transfer setup error: " + str(exc), file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
