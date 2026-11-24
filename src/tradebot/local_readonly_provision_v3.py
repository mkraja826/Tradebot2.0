"""Owner-local read-only provisioning. No automatic discovery or export of secrets."""
import os
import stat
import json
import tempfile
from pathlib import Path

FILENAME="clients.json"
ROLES=("BTCUSD","XAUTUSD","parent","provider")

def config_dir():
    return Path.home()/".tradebot3-readonly"

def validate(data):
    if type(data) is not dict or set(data)!=set(ROLES):
        raise ValueError("invalid_roles")
    for role in ROLES:
        fields={"key"} if role=="provider" else {"key","secret"}
        obj=data[role]
        if type(obj) is not dict or set(obj)!=fields:
            raise ValueError("invalid_fields")
        if any(type(v) is not str or not v.strip() or len(v)>4096 or any(c in v for c in "\r\n\x00") for v in obj.values()):
            raise ValueError("invalid_input")
    return data

def directory(path,*,create=False):
    p=Path(path)
    if create:
        try: p.mkdir(mode=0o700)
        except FileExistsError: pass
    st=p.lstat()
    if not stat.S_ISDIR(st.st_mode) or st.st_uid!=os.geteuid() or stat.S_IMODE(st.st_mode)!=0o700:
        raise ValueError("unsafe_directory")
    return p

def check_file(st):
    if not stat.S_ISREG(st.st_mode) or st.st_uid!=os.geteuid() or stat.S_IMODE(st.st_mode)!=0o600 or st.st_nlink!=1 or st.st_size>65536:
        raise ValueError("unsafe_file")

def load(path):
    p=directory(path)/FILENAME
    fd=os.open(p,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    with os.fdopen(fd,"rb") as f:
        check_file(os.fstat(f.fileno()))
        raw=f.read(65537)
    if len(raw)>65536: raise ValueError("oversize")
    return validate(json.loads(raw))

def save(path,data,*,replace=False):
    validate(data)
    p=directory(path,create=True)
    dest=p/FILENAME
    if replace:
        check_file(dest.lstat())
    elif dest.exists() or dest.is_symlink():
        raise FileExistsError("already_provisioned")
    fd,tmp=tempfile.mkstemp(prefix=".new-",dir=p)
    try:
        with os.fdopen(fd,"w",encoding="utf-8") as f:
            os.fchmod(f.fileno(),0o600)
            json.dump(data,f,separators=(",",":"))
            f.flush()
            os.fsync(f.fileno())
        if replace:
            os.replace(tmp,dest)
        else:
            os.link(tmp,dest,follow_symlinks=False)
            os.unlink(tmp)
        dfd=os.open(p,os.O_DIRECTORY|os.O_NOFOLLOW)
        try: os.fsync(dfd)
        finally: os.close(dfd)
    finally:
        try: os.unlink(tmp)
        except FileNotFoundError: pass
