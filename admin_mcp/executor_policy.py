"""Development policy only. No subprocesses or production access."""
import re

def validate_request(request, now, allowed_targets):
    if type(request) is not dict or set(request)!={"id","action","target","arguments","expected_revision","expires"}:
        raise ValueError("invalid request schema")
    if not isinstance(request["id"],str) or not re.fullmatch("[0-9a-f]{32}",request["id"]):
        raise ValueError("invalid request id")
    if type(now) is not int or type(request["expires"]) is not int or not now<request["expires"]<=now+300:
        raise ValueError("invalid expiry")
    if not isinstance(request["target"],str) or request["target"] not in allowed_targets:
        raise ValueError("target not allowed")
    if not isinstance(request["expected_revision"],str) or not re.fullmatch("[0-9a-f]{40}",request["expected_revision"]):
        raise ValueError("invalid revision")
    # First supported operation is a restart with no caller-controlled arguments.
    if request["action"]!="restart_service" or type(request["arguments"]) is not dict or request["arguments"]:
        raise ValueError("operation not allowed")
    return request["target"],request["expected_revision"]
