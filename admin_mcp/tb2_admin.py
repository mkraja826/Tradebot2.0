"""Separate TB2 admin MCP. No broker imports or order methods.
Read operations inspect the host or a separate public-source checkout.
Write operations create explicit requests; a local operator must approve them.
No arbitrary shell, secret-file reader, root endpoint or live checkout writes.
"""
import json
import os
import re
import shutil
import sqlite3
import subprocess
import time
import uuid
from pathlib import Path

VERSION = "tb2-admin-v2-dev"
SOURCE = Path(os.environ.get("TB2_ADMIN_SOURCE", "/opt/tb2-admin-source")).resolve()
QUEUE = Path(os.environ.get("TB2_ADMIN_QUEUE", "/var/lib/tb2-admin/requests")).resolve()
SNAPSHOTS = Path(os.environ.get("TB2_ADMIN_SNAPSHOTS", "/var/lib/recover-mcp-snapshots")).resolve()
SERVICES = tuple(x for x in os.environ.get("TB2_ADMIN_SERVICES", "").split(",") if re.fullmatch(r"[a-zA-Z0-9_.@-]+\.service", x))
DB_NAMES = {"market.sqlite", "orders.sqlite", "decisions.sqlite", "signal_research.sqlite"}
SOURCE_SUFFIXES = {".py", ".md", ".toml", ".js", ".ts", ".tsx", ".css", ".html"}
DENY = re.compile(r"secret|credential|token|password|private|\.env|\.pem|\.key", re.I)
IDENT = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,79}")
GIT = "/usr/bin/git"

def command(args, cwd=None, seconds=15):
    # All callers use fixed argv and bounded input. Never invoke a shell.
    p = subprocess.run(args, cwd=cwd, text=True, stdout=subprocess.PIPE,
                       stderr=subprocess.PIPE, timeout=seconds,
                       env={"PATH":"/usr/bin:/bin","LANG":"C","GIT_CONFIG_NOSYSTEM":"1",
                            "GIT_CONFIG_GLOBAL":"/dev/null","GIT_TERMINAL_PROMPT":"0",
                            "GIT_OPTIONAL_LOCKS":"0","GIT_PAGER":"cat"})
    return {"exit_code":p.returncode,"stdout":p.stdout[:24000],
            "stderr":p.stderr[:2000]}

def service(name):
    if name not in SERVICES:
        raise ValueError("service not configured by VM administrator")
    return name

def ref(value):
    if not re.fullmatch(r"[0-9a-f]{40}",value):
        raise ValueError("use exact 40-character commit SHA")
    return value

def identifier(value):
    if not IDENT.fullmatch(value):
        raise ValueError("invalid identifier")
    return value

def source_path(value):
    p=Path(value)
    if p.is_absolute() or ".." in p.parts or not p.parts or any(x.startswith(".") for x in p.parts):
        raise ValueError("invalid source path")
    if DENY.search(value) or p.suffix not in SOURCE_SUFFIXES:
        raise ValueError("only non-sensitive source extensions")
    return p.as_posix()

def database(relative):
    p=Path(relative)
    if p.is_absolute() or ".." in p.parts or p.name not in DB_NAMES:
        raise ValueError("only configured snapshot database names")
    q=SNAPSHOTS/p
    if q.resolve()!=q or not q.is_file():
        raise ValueError("snapshot unavailable or symlink")
    return q

def stage(action, args):
    # Queue must be provisioned by the VM operator and kept private.
    if not QUEUE.is_dir() or QUEUE.stat().st_mode & 0o077:
        raise RuntimeError("private approval queue not configured")
    request_id=uuid.uuid4().hex
    record={"id":request_id,"version":VERSION,"created":int(time.time()),
            "action":action,"arguments":args,"status":"pending_local_approval"}
    path=QUEUE/(request_id+".json")
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,"w") as f:
        json.dump(record,f,sort_keys=True);f.flush();os.fsync(f.fileno())
    return {"request_id":request_id,"status":"pending_local_approval",
            "action":action,"execution_effect":"none"}

def server_health():
    """Read disk, memory, load and uptime. No secrets or process arguments."""
    d=shutil.disk_usage("/")
    memory={}
    for row in Path("/proc/meminfo").read_text().splitlines():
        k,_,v=row.partition(":")
        if k in {"MemTotal","MemAvailable","SwapTotal","SwapFree"}:memory[k]=v.strip()
    return {"version":VERSION,"disk_total":d.total,"disk_free":d.free,
            "load_average":os.getloadavg(),"memory":memory,
            "uptime_seconds":float(Path("/proc/uptime").read_text().split()[0]),
            "execution_effect":"none"}

def disk_usage():
    """Report filesystem usage and bounded top-level directory sizes."""
    return {"filesystems":command(["/usr/bin/df","-h","-x","tmpfs","-x","devtmpfs"]),
            "directories":command(["/usr/bin/du","-x","-d1","/opt","/var/log"],seconds=30),
            "note":"directory totals reflect MCP account permissions"}

def disk_cleanup(profile: str="package_cache_and_old_journal"):
    """Request approved cache and archived journal cleanup. Never delete project data."""
    if profile!="package_cache_and_old_journal":raise ValueError("unsupported cleanup profile")
    return stage("disk_cleanup",{"profile":profile})

def list_files():
    """List tracked non-sensitive source paths from the separate checkout."""
    r=command([GIT,"ls-files"],SOURCE)
    if r["exit_code"]:return {"status":"source_unavailable"}
    paths=[]
    for line in r["stdout"].splitlines():
        try:paths.append(source_path(line))
        except ValueError:pass
    return {"paths":paths,"note":"bounded tracked-source listing; no VM configuration"}

def read_file(path: str):
    """Read a tracked non-sensitive file from committed source, not the live VM tree."""
    p=source_path(path)
    r=command([GIT,"show","HEAD:"+p],SOURCE)
    if r["exit_code"]:return {"status":"unavailable"}
    if re.search(r"(?i)(api[_-]?key|password|secret|access[_-]?token)\s*[:=]\s*['\"][^'\"]{8,}",r["stdout"]):
        return {"status":"potential_secret_detected"}
    return {"path":p,"content":r["stdout"],"note":"bounded committed-source excerpt"}

def apply_patch(patch: str):
    """Stage a bounded source patch for human review in a separate checkout."""
    if not patch.startswith("diff --git ") or len(patch)>60000 or "\x00" in patch:
        raise ValueError("expected unified git diff, up to 60KB")
    return stage("apply_patch",{"patch":patch})

def service_status():
    """Read status of VM-operator-allowlisted units only."""
    return {s:command(["/usr/bin/systemctl","show",s,"--property=ActiveState,SubState,MainPID,ExecMainStatus"]) for s in SERVICES}

def service_logs(name: str, minutes: int=60):
    """Read aggregate service error counts, not raw log content or secrets."""
    service(name)
    if not 1<=minutes<=1440:raise ValueError("minutes must be 1..1440")
    r=command(["/usr/bin/journalctl","--no-pager","-u",name,"--since",f"{minutes} minutes ago","-n","3000","-o","cat"])
    lines=r["stdout"].splitlines()
    return {"service":name,"observed_lines":len(lines),"exit_code":r["exit_code"],
            "counts":{k:sum(k in s.lower() for s in lines) for k in ("error","exception","timeout","http_402","failed","disk full")},
            "note":"bounded aggregate only; verify journal permission locally"}

def restart_service(name: str):
    """Request restart of an allowlisted service after local approval."""
    return stage("restart_service",{"service":service(name)})

def git_status():
    """Read separate source checkout status."""
    return command([GIT,"status","--short","--branch","--untracked-files=no"],SOURCE)

def git_diff():
    """Read changed-file names and line counts; no secret-bearing raw working diff."""
    return command([GIT,"diff","--stat","--no-ext-diff","--no-textconv","HEAD"],SOURCE)

def git_commit(message: str):
    """Request committing reviewed changes in the separate source checkout."""
    if not 1<=len(message)<=200 or any(ord(c)<32 for c in message):raise ValueError("invalid message")
    return stage("git_commit",{"message":message})

def run_tests():
    """Request tests in an isolated test environment with no broker credentials."""
    return stage("run_tests",{"profile":"unittest"})

def deploy_version(commit_sha: str):
    """Request deployment of an exact tested commit, subject to local review."""
    return stage("deploy_version",{"commit_sha":ref(commit_sha)})

def install_dependency(package: str, version: str):
    """Request a pinned dependency; never install directly from tool input."""
    identifier(package);identifier(version)
    return stage("install_dependency",{"package":package,"version":version})

def database_inspect(relative: str):
    """Read table names from a configured snapshot only; never query live DBs."""
    q=database(relative)
    with sqlite3.connect(q.as_uri()+"?mode=ro",uri=True,timeout=2) as db:
        db.execute("PRAGMA query_only=ON")
        rows=db.execute("SELECT name,type FROM sqlite_master WHERE type IN ('table','view') ORDER BY name LIMIT 100").fetchall()
    return {"snapshot":relative,"objects":rows,"bytes":q.stat().st_size}

def database_backup(relative: str):
    """Request a consistent SQLite backup of an allowlisted snapshot."""
    database(relative)
    return stage("database_backup",{"relative":relative})

def create_snapshot(label: str):
    """Request a VM-operator-reviewed recovery snapshot."""
    return stage("create_snapshot",{"label":identifier(label)})

def rollback_version(commit_sha: str):
    """Request rollback to an exact previously verified revision."""
    return stage("rollback_version",{"commit_sha":ref(commit_sha)})

def audit_history():
    """Read bounded request metadata only. Arguments and sensitive data are omitted."""
    if not QUEUE.is_dir():return {"status":"queue_unavailable"}
    out=[]
    for p in sorted(QUEUE.glob("*.json"),key=lambda x:x.name)[:2000]:
        try:
            if p.is_symlink() or p.stat().st_size>100000:continue
            r=json.loads(p.read_text())
            out.append({k:r.get(k) for k in ("id","created","action","status")})
        except (OSError,ValueError):continue
    return {"requests":sorted(out,key=lambda x:x.get("created") or 0,reverse=True)[:50],
            "note":"local request journal, not proof of completed operations"}


def admin_capabilities():
    """Report registered tools and actual approval model without exposing secrets."""
    return {"version": VERSION, "tools": [t.__name__ for t in TOOLS],
            "tool_count": len(TOOLS), "approval_mode": "pending_local_approval",
            "remote_execution": False, "execution_effect": "none"}

def service_diagnostics(name: str, minutes: int=60):
    """Distinguish unavailable journal access from an empty or readable journal."""
    service(name)
    if not 1 <= minutes <= 1440:
        raise ValueError("minutes must be 1..1440")
    r = command(["/usr/bin/journalctl", "--no-pager", "-u", name,
                 "--since", f"{minutes} minutes ago", "-n", "1000", "-o", "cat"])
    denied = any(x in r["stderr"].lower() for x in ("permission", "access denied", "not seeing messages"))
    lines = r["stdout"].splitlines()
    state = "permission_limited" if denied else ("unavailable" if r["exit_code"] else ("readable" if lines else "empty_or_not_visible"))
    return {"service": name, "minutes": minutes, "journal_status": state,
            "exit_code": r["exit_code"], "observed_lines": len(lines),
            "counts": {k: sum(k in line.lower() for line in lines) for k in ("error","exception","timeout","failed")} if state == "readable" else None,
            "execution_effect": "none"}


def gold_v2_qa_report(limit: int=40):
    """Read a dedicated sanitized Gold V2 QA export, never raw trading databases."""
    if not 1 <= limit <= 240:
        raise ValueError("limit must be 1..240")
    path = Path("/var/lib/tb2-admin/gold-v2-qa.json")
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as f:
            import stat
            if not stat.S_ISREG(os.fstat(f.fileno()).st_mode):
                return {"status":"invalid_export"}
            raw = f.read(1048577)
        if len(raw) > 1048576:
            return {"status":"export_too_large"}
        data = json.loads(raw)
        if not isinstance(data, dict) or data.get("schema_version") != 1 or not isinstance(data.get("scans"), list):
            return {"status":"invalid_export"}
        scans = []
        for row in data["scans"]:
            if not isinstance(row, dict):
                continue
            ts = row.get("timestamp")
            if type(ts) not in (int,float) or not 0 < ts <= time.time()+5:
                continue
            conditions = row.get("conditions", {})
            if not isinstance(conditions, dict):
                continue
            clean = {k:v for k,v in conditions.items() if re.fullmatch(r"[a-zA-Z0-9_]{1,64}",k) and type(v) is bool}
            scans.append({"timestamp":ts,"conditions":clean})
        scans.sort(key=lambda x:x["timestamp"])
        age = round(time.time()-scans[-1]["timestamp"],1) if scans else None
        gaps = [b["timestamp"]-a["timestamp"] for a,b in zip(scans,scans[1:])]
        return {"status":"fresh" if age is not None and age <= 45 else ("stale" if scans else "no_valid_scans"),
                "expected_interval_seconds":15,"latest_scan_age_seconds":age,
                "observed_scan_count":len(scans),"largest_observed_gap_seconds":max(gaps) if gaps else None,
                "scans":scans[-limit:],"execution_effect":"none"}
    except FileNotFoundError:
        return {"status":"export_not_configured","execution_effect":"none"}
    except (OSError,ValueError):
        return {"status":"export_unavailable_or_invalid","execution_effect":"none"}


def gold_v2_entry_journal(limit: int=10):
    """Read a provisioned QA snapshot; never create or mutate a database."""
    if not 1 <= limit <= 40:
        raise ValueError("limit must be 1..40")
    path = SNAPSHOTS / "gold-v2" / "entry_qa.sqlite"
    if path.resolve() != path or not path.is_file():
        return {"status":"snapshot_unavailable"}
    from contextlib import closing
    try:
        with closing(sqlite3.connect(path.as_uri()+"?mode=ro",uri=True,timeout=2)) as db:
            db.execute("PRAGMA query_only=ON")
            rows = db.execute("SELECT boundary,started,finished,CASE WHEN length(detail)<=262144 THEN detail END FROM scans ORDER BY boundary DESC,started DESC LIMIT ?",(limit,)).fetchall()
        out = []
        for boundary,started,finished,detail in rows:
            event = json.loads(detail) if detail else {}
            scan = event.get("scan") or {}
            setups = {}
            for direction in ("LONG","SHORT"):
                setups[direction] = {}
                for family, conditions in scan.get("setups",{}).get(direction,{}).items():
                    if not re.fullmatch(r"mark_[a-z_]{1,50}",family):
                        continue
                    setups[direction][family] = {}
                    for name,c in conditions.items():
                        if not re.fullmatch(r"[a-z_0-9]{1,64}",name):
                            continue
                        setups[direction][family][name] = {k:c.get(k) for k in ("value","operator","threshold","passed") if c.get(k) is None or type(c.get(k)) in (int,float,bool) or c.get(k) in ("==",">",">=","<","<=","higher_highs_lows","lower_highs_lows")}
            out.append({"boundary":boundary,"started":started,"finished":finished,
                        "observed":scan.get("data_status")=="observed",
                        "matches_engine":scan.get("matches_engine") if type(scan.get("matches_engine")) is bool else None,
                        "setups":setups})
        return {"status":"observed" if out else "empty","records":out,
                "latest_record_age_seconds":round(time.time()-out[0]["finished"],1) if out else None,
                "note":"entry boundary records, not proof of 15-second scan cadence"}
    except (sqlite3.Error,ValueError,TypeError,AttributeError):
        return {"status":"snapshot_invalid_or_unreadable"}

TOOLS=(gold_v2_entry_journal,gold_v2_qa_report,admin_capabilities,service_diagnostics,server_health,disk_usage,disk_cleanup,list_files,read_file,apply_patch,
       service_status,service_logs,restart_service,git_status,git_diff,git_commit,
       run_tests,deploy_version,install_dependency,database_inspect,database_backup,
       create_snapshot,rollback_version,audit_history)

def register(server):
    for tool in TOOLS:server.tool()(tool)

if __name__=="__main__":
    from mcp.server.fastmcp import FastMCP
    server=FastMCP("TB2.0 Admin")
    register(server)
    server.run(transport="stdio")
