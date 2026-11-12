import asyncio
from types import SimpleNamespace
from app.knowloom.models import KnowLoomPreprocessResult
from app.knowloom.services import file_ingest

class Repository:
    def __init__(self, job): self.job=job; self.updates=[]
    def get_file_ingest_job(self, job_id): return self.job
    def update_file_ingest_job(self, job_id, **kwargs): self.updates.append(kwargs)
    def find_duplicate_converted_content(self, document_id, fingerprint): return None
    def find_document_by_title(self, **kwargs): return None
    def add_document_relation(self, *args, **kwargs): pass

class Processor:
    def __init__(self, **kwargs): pass
    async def preprocess(self,text): return KnowLoomPreprocessResult(input_text=text)

class Ingestor:
    def __init__(self, **kwargs): pass
    async def queue(self, *args, **kwargs):
        assert kwargs["existing_document_id"] == 8
        return SimpleNamespace(job_id=42)

def test_file_worker_transitions_preprocessing_to_queued(tmp_path, monkeypatch):
    path=tmp_path/"rules.md"; path.write_text("# 办法\n正文",encoding="utf-8")
    job={"id":1,"document_id":8,"file_name":"rules.md","file_sha256":"a"*64,"original_file_path":str(path),"workspace_id":"local","project_id":"knowloom","collection_id":"default","domain":"general","meta":{"doc_key":"rules","title":"办法"}}
    repository=Repository(job)
    monkeypatch.setattr(file_ingest,"MySQLEntityRepository",lambda config: repository)
    monkeypatch.setattr(file_ingest,"KnowLoomProcessor",Processor)
    monkeypatch.setattr(file_ingest,"EntityIngestor",Ingestor)
    asyncio.run(file_ingest._process_file_ingest_job(1,file_ingest.settings))
    assert [item["status"] for item in repository.updates] == ["preprocessing","queued"]
    assert repository.updates[-1]["ingest_job_id"] == 42
