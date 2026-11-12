from contextlib import contextmanager
from app.knowloom.config import KnowLoomSettings
from app.knowloom.entity_store.attribute_sweeper import AttributeSweeper
from app.knowloom.entity_store.repository import MySQLEntityRepository

class Cursor:
    def __init__(self): self.rowcount=1; self.row=None; self.lastrowid=99; self.statements=[]
    def __enter__(self): return self
    def __exit__(self,*args): pass
    def execute(self,sql,params=None):
        self.statements.append((sql,params)); self.row=None; self.rows=[]; self.rowcount=1
        if "JOIN knowloom_documents d" in sql and "WHERE j.id" in sql:
            self.row={"id":3,"doc_key":"rules","version_no":1,"content_text":"正文"}
        elif "FROM knowloom_entity_attribute_events" in sql:
            self.row={"id":5,"entity_id":7,"attribute_id":20,"attr_type":"conditions","action":"supersede","review_status":"auto_applied","candidate_json":'{"attribute_id": 10}',"incoming_json":"{}","before_json":"{}","after_json":"{}","note_id":"","block_id":"","block_index":-1}
    def fetchone(self): return self.row
    def fetchall(self): return self.rows

class Connection:
    def __init__(self,cursor): self.c=cursor; self.committed=False; self.rolled_back=False
    def __enter__(self): return self
    def __exit__(self,*args): pass
    def cursor(self): return self.c
    def commit(self): self.committed=True
    def rollback(self): self.rolled_back=True

def repository_with_cursor():
    repository=MySQLEntityRepository(KnowLoomSettings(_env_file=None)); cursor=Cursor(); connection=Connection(cursor)
    @contextmanager
    def connect(): yield connection
    repository.connect=connect
    return repository,cursor,connection

def test_first_document_version_marks_job_swept_without_changing_attributes():
    repository,cursor,connection=repository_with_cursor()
    assert AttributeSweeper(repository).sweep_completed_job(4) == []
    assert connection.committed
    assert not any("UPDATE knowloom_entity_attributes" in sql for sql,_ in cursor.statements)

def test_revert_supersede_restores_old_and_rejects_new_attribute():
    repository,cursor,connection=repository_with_cursor()
    result=repository.revert_attribute_event(5)
    assert result["restored_attribute_id"] == 10
    statements="\n".join(sql for sql,_ in cursor.statements)
    assert "SET status='active'" in statements
    assert "SET status='rejected'" in statements
    assert connection.committed

class RemovedCursor(Cursor):
    def execute(self,sql,params=None):
        self.statements.append((sql,params)); self.row=None; self.rows=[]; self.rowcount=1
        if "JOIN knowloom_documents d" in sql and "WHERE j.id" in sql:
            self.row={"id":3,"scope_hash":"scope","doc_key":"rules","version_no":2,"content_text":"新版仅保留其他条款"}
        elif "SELECT id FROM knowloom_documents" in sql:
            self.rows=[{"id":1}]
        elif "SELECT DISTINCT a.id" in sql:
            self.rows=[{"id":10,"entity_id":7,"attr_type":"conditions","value_text":"旧条款","confidence":.9,"manually_confirmed":0}]
        elif "SELECT e.evidence_text" in sql:
            self.rows=[{"evidence_text":"已删除的原句","evidence_fingerprint":"fp","note_id":"rules","block_id":"b1","block_index":1,"document_status":"superseded"}]

def test_new_version_sweeper_supersedes_removed_unconfirmed_attribute():
    repository=MySQLEntityRepository(KnowLoomSettings(_env_file=None)); cursor=RemovedCursor(); connection=Connection(cursor)
    @contextmanager
    def connect(): yield connection
    repository.connect=connect
    assert AttributeSweeper(repository).sweep_completed_job(4) == [10]
    assert any("superseded_reason='removed_in_new_version'" in sql for sql,_ in cursor.statements)
