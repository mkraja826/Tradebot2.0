"""Standalone enrollment service; not a trading or deployment executor."""
import json
import logging
import os
import sqlite3
import stat
import sys
from pathlib import Path

# Python isolated mode excludes the script directory. Only load installed,
# administrator-owned application modules from the verified installation.
ROOT = Path(__file__).resolve().parent
if ROOT.stat().st_uid != 0 or ROOT.stat().st_mode & 0o022:
    raise RuntimeError("Untrusted application directory")
sys.path.insert(0, str(ROOT))

from enrollment_web import application
from enrollment_ingress import protect
from enrollment_key_cache import load_keys
from waitress import serve

CONFIG = Path("/etc/recover-approval/enrollment.json")
DATABASE = Path("/var/lib/recover-approval/passkeys.sqlite")

def main():
    if os.geteuid() == 0:
        raise RuntimeError("Root execution forbidden")
    info = CONFIG.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
        raise RuntimeError("Untrusted policy")
    config = json.loads(CONFIG.read_text())
    info = DATABASE.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
        raise RuntimeError("Invalid database ownership or permissions")
    def connect():
        return sqlite3.connect(DATABASE.as_uri()+"?mode=rw",uri=True,timeout=5)
    policy = config["policy"]
    access = config["access"]
    app = protect(application(connect,policy),access["issuer"],access["audience"],load_keys,access["allowed_subjects"])
    logging.basicConfig(level=logging.INFO,format="%(asctime)s %(name)s %(message)s")
    serve(app,host="127.0.0.1",port=18767,threads=4,max_request_body_size=131072,max_request_header_size=32768,channel_timeout=15,clear_untrusted_proxy_headers=True)

if __name__ == "__main__":
    main()
