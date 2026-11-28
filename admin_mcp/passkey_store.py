"""Gateway-only storage prototype. Provision database in a private gateway directory."""
from dataclasses import dataclass
import time

@dataclass(frozen=True)
class Credential:
    operator: str
    public_key: bytes
    sign_count: int

class CredentialStore:
    def __init__(self, db):
        self.db=db
        db.execute("CREATE TABLE IF NOT EXISTS credentials (id BLOB PRIMARY KEY, operator TEXT NOT NULL, public_key BLOB NOT NULL, sign_count INTEGER NOT NULL)")
        db.execute("CREATE TABLE IF NOT EXISTS challenges (challenge BLOB PRIMARY KEY, expires INTEGER NOT NULL, consumed INTEGER NOT NULL DEFAULT 0)")
        db.commit()

    def lookup(self, credential_id):
        row=self.db.execute("SELECT operator,public_key,sign_count FROM credentials WHERE id=?", (credential_id,)).fetchone()
        return Credential(*row) if row else None

    def add_challenge(self, challenge, expires):
        now=int(time.time())
        if len(challenge)!=32 or not now < expires <= now+300:
            raise ValueError("invalid challenge")
        with self.db:
            self.db.execute("INSERT INTO challenges(challenge,expires) VALUES (?,?)",(challenge,expires))

    def consume_verified_challenge(self, challenge, credential_id, old_count, new_count):
        if type(old_count) is not int or type(new_count) is not int or not (new_count>old_count>=0 or new_count==old_count==0):
            return False
        try:
            with self.db:
                changed=self.db.execute("UPDATE challenges SET consumed=1 WHERE challenge=? AND consumed=0 AND expires>?",(challenge,int(time.time()))).rowcount
                if changed!=1:
                    raise ValueError("challenge unavailable")
                changed=self.db.execute("UPDATE credentials SET sign_count=? WHERE id=? AND sign_count=?",(new_count,credential_id,old_count)).rowcount
                if changed!=1:
                    raise ValueError("credential changed")
            return True
        except ValueError:
            return False
