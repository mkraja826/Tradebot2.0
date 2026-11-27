#!/usr/bin/env python3
"""Local-only cleanup approval. Review and install root-owned before use.
Never invoke this script automatically from MCP or add it to broad sudoers.
"""
import json
import os
import re
import stat
import subprocess
import sys
from pathlib import Path

QUEUE=Path("/var/lib/tb2-admin/requests")
def main():
    if os.geteuid()!=0 or len(sys.argv)!=2 or not re.fullmatch("[a-f0-9]{32}",sys.argv[1]):
        raise SystemExit("usage: sudo <reviewed-root-owned-script> REQUEST_ID")
    rid=sys.argv[1]
    fd=os.open(QUEUE/(rid+".json"),os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    with os.fdopen(fd,"rb") as f:
        st=os.fstat(f.fileno())
        if not stat.S_ISREG(st.st_mode) or st.st_size>4096:
            raise SystemExit("invalid request")
        r=json.loads(f.read(4097))
    if (r.get("id")!=rid or r.get("action")!="disk_cleanup" or
        r.get("status")!="pending_local_approval" or
        r.get("arguments")!={"profile":"package_cache_and_old_journal"}):
        raise SystemExit("not an approved cleanup profile")
    print("Before:",flush=True)
    subprocess.run(["/usr/bin/df","-h","/"],check=True)
    subprocess.run(["/usr/bin/apt-get","clean"],check=True,timeout=120)
    subprocess.run(["/usr/bin/journalctl","--vacuum-time=7d"],check=True,timeout=120)
    print("After:",flush=True)
    subprocess.run(["/usr/bin/df","-h","/"],check=True)
    subprocess.run(["/usr/bin/logger","-t","tb2-admin","cleanup completed request "+rid],check=True)
    print("Cleanup complete. No trading service restarted.")
if __name__=="__main__":main()
