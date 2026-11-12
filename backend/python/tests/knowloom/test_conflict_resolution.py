from contextlib import contextmanager
from app.knowloom.config import KnowLoomSettings
from app.knowloom.entity_store.repository import MySQLEntityRepository

class Cursor:
    def __init__(self): self.rowcount=1; self.row=None; self.statements=[]
    def __enter__(self): return self
    def __exit__(self,*args): pass
    def execute(self, sql, params=None):
        self.statements.append((sql,params))
        if "FROM knowloom_entity_attribute_conflicts" in sql:
            self.row={"id":1,"attribute_id":2,"entity_id":3,"attr_type":"conditions","incoming_json":"{}","incoming_value_text":"新值","incoming_evidence":"证据","confidence":.8}
        elif "SELECT value_text" in sql:
            self.row={"value_text":"旧值"}
        else: self.row=None
    def fetchone(self): return self.row

class Connection:
    def __init__(self,cursor): self.cursor_value=cursor; self.committed=False
    def __enter__(self): return self
    def __exit__(self,*args): pass
    def cursor(self): return self.cursor_value
    def commit(self): self.committed=True

def test_dismiss_claims_pending_conflict_without_changing_attributes():
    repository=MySQLEntityRepository(KnowLoomSettings(_env_file=None)); cursor=Cursor(); connection=Connection(cursor)
    @contextmanager
    def connect(): yield connection
    repository.connect=connect
    assert repository.resolve_attribute_conflict(1,resolution="dismiss") is True
    assert connection.committed
    assert not any("SET manually_confirmed" in sql or "SET status='superseded'" in sql for sql,_ in cursor.statements)
