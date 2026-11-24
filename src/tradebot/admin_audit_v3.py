"""Local tamper-evident review log. No approval, activation or rollback authority."""
import argparse,json,os,sqlite3,time
from pathlib import Path
from contextlib import closing
from tradebot.admin_v3 import STATE
from tradebot.admin_release_v3 import canonical,sha,verify
ZERO='0'*64
def valid_id(i):
    return isinstance(i,str) and len(i)==64 and all(c in '0123456789abcdef' for c in i)
def chain(db):
    prev=ZERO;n=0
    for seq,raw,h in db.execute('SELECT seq,body,sha FROM events ORDER BY seq'):
        v=json.loads(raw)
        n+=1
        if seq!=n or v['seq']!=n or v['previous_sha']!=prev or canonical(v)!=raw or sha(raw)!=h:
            raise ValueError('audit_integrity')
        if v['kind']!='candidate_verified' or v['activation_authorized'] is not False or not valid_id(v['release_id']):
            raise ValueError('audit_scope')
        prev=h
    return n,prev
def record(root,release_id):
    if not valid_id(release_id):raise ValueError('release_id')
    root=Path(root)
    verify(root/'policy-review-candidates'/(release_id+'.zip'),expected_id=release_id)
    path=root/'admin-review-audit.sqlite'
    if path.is_symlink():raise ValueError('unsafe_path')
    fd=os.open(path,os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600);os.close(fd)
    if path.stat().st_mode&0o077:raise ValueError('unsafe_permissions')
    with closing(sqlite3.connect(path,timeout=5)) as db,db:
        db.execute('PRAGMA synchronous=FULL')
        db.execute('BEGIN IMMEDIATE')
        db.execute('CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY,body BLOB NOT NULL,sha TEXT NOT NULL)')
        n,prev=chain(db)
        v=dict(seq=n+1,previous_sha=prev,kind='candidate_verified',release_id=release_id,
            recorded_at_us=time.time_ns()//1000,activation_authorized=False)
        raw=canonical(v);h=sha(raw)
        db.execute('INSERT INTO events VALUES(?,?,?)',(n+1,raw,h))
    return dict(events=n+1,head_sha=h,activation_authorized=False)
def inspect(root):
    p=Path(root)/'admin-review-audit.sqlite'
    if p.is_symlink():raise ValueError('unsafe_path')
    with closing(sqlite3.connect(p.resolve().as_uri()+'?mode=ro',uri=True)) as db:
        db.execute('PRAGMA query_only=ON')
        db.execute('BEGIN')
        n,h=chain(db)
    return dict(events=n,head_sha=h,activation_authorized=False,independent_rollback_witness=False)
def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('action',choices=['record-verification','inspect']);p.add_argument('--id')
    a=p.parse_args()
    r=record(STATE.parent,a.id) if a.action=='record-verification' else inspect(STATE.parent)
    print(json.dumps(r))
if __name__=='__main__':main()
