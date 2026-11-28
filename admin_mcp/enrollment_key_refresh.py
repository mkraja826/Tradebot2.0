"""Run separately from the network-isolated enrollment service."""
import json
import os
import tempfile
import time
import urllib.request
from pathlib import Path
import jwt

URL = "https://karthikraja826.cloudflareaccess.com/cdn-cgi/access/certs"
DEST = Path("/etc/recover-approval/access-keys.json")

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("Unexpected redirect")

def refresh():
    opener = urllib.request.build_opener(NoRedirect())
    with opener.open(URL, timeout=10) as response:
        raw = response.read(65537)
    if len(raw) > 65536:
        raise ValueError("Oversized key set")
    data = json.loads(raw)
    keys = data["keys"]
    if not 1 <= len(keys) <= 16:
        raise ValueError("Invalid key count")
    ids = set()
    for key in keys:
        parsed = jwt.PyJWK.from_dict(key)
        if not parsed.key_id or parsed.key_id in ids or parsed.algorithm_name != "RS256" or parsed.key.key_size < 2048 or any(x in key for x in ("d","p","q","dp","dq","qi")):
            raise ValueError("Invalid public key")
        ids.add(parsed.key_id)
    fd, name = tempfile.mkstemp(dir=DEST.parent)
    try:
        with os.fdopen(fd,"w") as out:
            json.dump({"fetched_at":int(time.time()),"jwks":{"keys":keys}},out)
            out.flush()
            os.fchmod(out.fileno(),0o644)
            os.fsync(out.fileno())
        os.replace(name,DEST)
    finally:
        if os.path.exists(name):
            os.unlink(name)

if __name__ == "__main__":
    refresh()
