"""Append-only offline management journal, with one instruction per snapshot."""
from contextlib import closing
import sqlite3
from tradebot.management_instructions_v3 import validate
from tradebot.opportunity_journal_v3 import canonical

class ManagementJournal:
    def __init__(self,path):
        self.path=path
        with closing(self.connect()) as db,db:
            db.execute("""CREATE TABLE IF NOT EXISTS instructions(
              context_id TEXT PRIMARY KEY,instruction_id TEXT UNIQUE NOT NULL,
              symbol TEXT NOT NULL,payload TEXT NOT NULL)""")
    def connect(self): return sqlite3.connect(self.path,timeout=10)
    def record(self,request,response,*,now):
        item=validate(request,response)
        if not 0<=now-request["payload"]["observation"]["observed_us"]/1e6<=60:
            raise ValueError("stale_instruction")
        key=request["context_id"]; body=canonical(item)
        with closing(self.connect()) as db,db:
            db.execute("BEGIN IMMEDIATE")
            row=db.execute("SELECT payload FROM instructions WHERE context_id=?",(key,)).fetchone()
            if row:
                if row[0]!=body: raise ValueError("conflicting_instruction")
                return "duplicate"
            db.execute("INSERT INTO instructions VALUES(?,?,?,?)",(key,item["instruction_id"],response["symbol"],body))
        return "recorded_offline"
