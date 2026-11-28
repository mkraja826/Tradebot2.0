import json
import os
import stat
import time
from pathlib import Path
import jwt

def load_keys(path=Path("/etc/recover-approval/access-keys.json"), clock=time.time):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as source:
        info = os.fstat(source.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise ValueError("Untrusted key cache")
        raw = source.read(65537)
    if len(raw) > 65536:
        raise ValueError("Oversized cache")
    data = json.loads(raw)
    age = clock() - data["fetched_at"]
    if not 0 <= age <= 86400:
        raise ValueError("Stale key cache")
    keys = jwt.PyJWKSet.from_dict(data["jwks"])
    if not 1 <= len(keys.keys) <= 16:
        raise ValueError("Invalid key count")
    ids = set()
    for key in keys.keys:
        if not key.key_id or key.key_id in ids or key.algorithm_name != "RS256" or key.key.key_size < 2048:
            raise ValueError("Invalid key")
        ids.add(key.key_id)
    return keys
