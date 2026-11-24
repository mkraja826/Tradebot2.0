"""Load Tradebot secrets from Google Cloud Secret Manager on a GCE VM.

Secrets are fetched with the VM's short-lived metadata token; they are not
written to disk or printed. The child process receives them as environment
variables. The runtime enforces no demo orders while integration is unfinished.

WARNING: A trusted process/user with control of this VM can access its attached
service-account credentials and the secrets the account is authorized to read.
"""
import argparse
import base64
import binascii
import json
import os
import re
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

METADATA_BASE = "http://metadata.google.internal/computeMetadata/v1"
SECRET_BINDINGS = (
    ("DELTA_DEMO_API_KEY", "tradebot-delta-demo-api-key"),
    ("DELTA_DEMO_API_SECRET", "tradebot-delta-demo-api-secret"),
    ("TB_API_KEY", "tradebot-tb-api-key"),
)


class GCPBootstrapError(RuntimeError):
    """Safe, deliberately redacted setup error."""


def _get(request, *, timeout=8):
    try:
        with urlopen(request, timeout=timeout) as reply:
            return reply.read()
    except (HTTPError, URLError, OSError, TimeoutError) as exc:
        # Never expose token, key, HTTP body or request headers in exceptions.
        raise GCPBootstrapError("VM identity or Secret Manager access failed") from None


def get_runtime_credentials() -> dict[str, str]:
    """Get the three approved values, never logging or writing their contents."""
    project_req = Request(
        METADATA_BASE + "/project/project-id",
        headers={"Metadata-Flavor": "Google"},
    )
    try:
        project_id = _get(project_req).decode("ascii").strip()
    except UnicodeDecodeError:
        raise GCPBootstrapError("Invalid VM project metadata") from None
    if not re.fullmatch(r"[a-z][a-z0-9-]{4,61}[a-z0-9]", project_id):
        raise GCPBootstrapError("VM project ID is invalid")

    token_req = Request(
        METADATA_BASE + "/instance/service-accounts/default/token",
        headers={"Metadata-Flavor": "Google"},
    )
    try:
        token = json.loads(_get(token_req)).get("access_token")
    except (ValueError, TypeError):
        raise GCPBootstrapError("Invalid VM service-account token response") from None
    if not isinstance(token, str) or not token:
        raise GCPBootstrapError("VM has no authorized service-account token")

    values = {}
    for environment_name, secret_id in SECRET_BINDINGS:
        req = Request(
            "https://secretmanager.googleapis.com/v1/projects/"
            + project_id + "/secrets/" + secret_id + "/versions/latest:access",
            headers={"Authorization": "Bearer " + token,
                     "Accept": "application/json"},
        )
        try:
            response = json.loads(_get(req))
            payload = response["payload"]["data"]
            value = base64.b64decode(payload, validate=True).decode("utf-8")
        except (KeyError, ValueError, TypeError, UnicodeDecodeError, binascii.Error):
            raise GCPBootstrapError(
                "Missing or malformed Secret Manager version for " + secret_id
            ) from None
        if not value or "\x00" in value:
            raise GCPBootstrapError("Invalid value in " + secret_id)
        values[environment_name] = value

    return values


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run a read-only Tradebot command with secrets from GCP metadata"
    )
    parser.add_argument("command", nargs=argparse.REMAINDER,
                        help="e.g. -- python -m tradebot.delta_probe --authenticated")
    parsed = parser.parse_args()
    command = parsed.command
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        parser.error("Specify a command after --")
    # This wrapper is for supervised read-only verification ONLY. It must
    # not act as an accidental path to sending testnet exchange orders.
    if "--demo-execute" in command:
        parser.error("GCP secret bootstrap forbids demo execution")

    try:
        secure_environment = os.environ.copy()
        secure_environment.update(get_runtime_credentials())
        secure_environment["TB_MODEL"] = "tb-deepseek-v4-1-flash"
        secure_environment["ENABLE_DEMO_ORDERS"] = "false"
        # Replaces the wrapper, keeping secrets only in the child process env.
        os.execvpe(command[0], command, secure_environment)
    except GCPBootstrapError as exc:
        print("Secure Google Cloud setup failed: " + str(exc), file=sys.stderr)
        raise SystemExit(1) from None
    except OSError:
        print("Cannot launch the requested command", file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
