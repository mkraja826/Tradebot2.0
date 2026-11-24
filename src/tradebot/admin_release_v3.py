"""Archive and verify V3 policy review candidates, never activate them."""
import argparse,hashlib,json,os,tempfile,zipfile
from pathlib import Path
from tradebot.admin_review_v3 import review
from tradebot.admin_v3 import STATE
FILES=('equity_policy_v3.py','equity_policy_reference_v3.py')
SRC=Path(__file__).parent
def sha(b):return hashlib.sha256(b).hexdigest()
def canonical(v):return json.dumps(v,sort_keys=True,separators=(',',':')).encode()
def archive(root):
    root=Path(root)
    evidence=review(root)
    bodies={f:(SRC/f).read_bytes() for f in FILES}
    if {f:sha(b) for f,b in bodies.items()}!=evidence['policy_source_hashes']:
        raise ValueError('source_changed_during_review')
    manifest=dict(schema='v3-review-candidate-1',evidence=evidence,
                  activation_authorized=False,files={f:sha(b) for f,b in bodies.items()})
    raw=canonical(manifest);release_id=sha(raw)
    dest=root/'policy-review-candidates'
    dest.mkdir(mode=0o700,exist_ok=True)
    if dest.is_symlink() or dest.stat().st_mode&0o077:raise ValueError('unsafe_directory')
    target=dest/(release_id+'.zip')
    fd,tmp=tempfile.mkstemp(dir=dest)
    try:
        with os.fdopen(fd,'w+b') as h:
            with zipfile.ZipFile(h,'w',compression=zipfile.ZIP_DEFLATED) as z:
                z.writestr('manifest.json',raw)
                for f,b in bodies.items():z.writestr(f,b)
            h.flush();os.fsync(h.fileno())
        verify(Path(tmp),expected_id=release_id)
        os.link(tmp,target)
        dfd=os.open(dest,os.O_DIRECTORY)
        try:os.fsync(dfd)
        finally:os.close(dfd)
    finally:os.unlink(tmp)
    return dict(release_id=release_id,archive_verified=True,activation_authorized=False)
def verify(path,*,expected_id):
    if path.is_symlink():raise ValueError('symlink')
    with zipfile.ZipFile(path) as z:
        names=z.namelist()
        if sorted(names)!=sorted(('manifest.json',)+FILES):raise ValueError('members')
        if any(i.file_size>1000000 for i in z.infolist()):raise ValueError('size')
        raw=z.read('manifest.json');m=json.loads(raw)
        if sha(raw)!=expected_id or raw!=canonical(m):raise ValueError('manifest_integrity')
        if m['schema']!='v3-review-candidate-1' or m['activation_authorized'] is not False:raise ValueError('scope')
        if m['evidence']['execution_authorized'] is not False:raise ValueError('scope')
        if m['files']!={f:sha(z.read(f)) for f in FILES}:raise ValueError('file_integrity')
        if m['files']!=m['evidence']['policy_source_hashes']:raise ValueError('review_binding')
    return True
def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('action',choices=['archive','verify']);p.add_argument('--id')
    a=p.parse_args()
    if a.action=='archive':r=archive(STATE.parent)
    else:
        if not a.id or len(a.id)!=64 or any(c not in '0123456789abcdef' for c in a.id):p.error('invalid release id')
        r=dict(release_id=a.id,archive_verified=verify(STATE.parent/'policy-review-candidates'/(a.id+'.zip'),expected_id=a.id),activation_authorized=False)
    print(json.dumps(r))
if __name__=='__main__':main()
