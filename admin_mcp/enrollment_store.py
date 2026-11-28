"""Trusted provisioning only; no public endpoint or MCP registration."""
import time

def initialize_enrollment(db):
    db.execute("CREATE TABLE IF NOT EXISTS enrollment_challenges (challenge BLOB PRIMARY KEY, operator TEXT NOT NULL, expires INTEGER NOT NULL)")
    db.commit()

def add_enrollment_challenge(db, challenge, operator, expires):
    now=int(time.time())
    if not isinstance(challenge,bytes) or len(challenge)!=32 or not operator or not now<expires<=now+300:
        raise ValueError("invalid enrollment challenge")
    with db:
        db.execute("INSERT INTO enrollment_challenges VALUES (?,?,?)",(challenge,operator,expires))

def register_verified(db, challenge, record):
    """Internal trusted caller must first cryptographically verify registration."""
    with db:
        count=db.execute("DELETE FROM enrollment_challenges WHERE challenge=? AND operator=? AND expires>?",(challenge,record["operator"],int(time.time()))).rowcount
        if count!=1:
            raise ValueError("enrollment challenge unavailable")
        db.execute("INSERT INTO credentials(id,operator,public_key,sign_count) VALUES (?,?,?,?)",(record["id"],record["operator"],record["public_key"],record["sign_count"]))
