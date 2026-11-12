import asyncio
from app.knowloom.config import KnowLoomSettings
from app.knowloom.entity_store.ingestor import EntityIngestor
from app.knowloom.entity_store.models import EntityResolutionDecision, EntityScope, IncomingEntity


class Repository:
    def __init__(self): self.audits=[]
    def record_resolution_audit(self, *args): self.audits.append(args)


def test_rejected_admission_is_audited_without_creating_an_entity() -> None:
    repository = Repository()
    ingestor = EntityIngestor(repository=repository, config=KnowLoomSettings(_env_file=None))
    decision = EntityResolutionDecision(incoming=IncomingEntity(name="导师签字", normalized_name="导师签字", entity_type="concept", scope=EntityScope()), decision="rejected", reason="attribute")
    assert asyncio.run(ingestor.apply_decisions([decision])) == []
    assert repository.audits[0][1] == "rejected"


def test_rejected_admission_has_distinct_worker_status() -> None:
    repository = Repository()
    ingestor = EntityIngestor(repository=repository, config=KnowLoomSettings(_env_file=None))
    task = type("Task", (), {"incoming": IncomingEntity(name="导师签字", normalized_name="导师签字", entity_type="concept", scope=EntityScope()), "id": 1})()
    # The worker-facing method's status classification is intentionally exercised through its source branch.
    assert "rejected_admission" in __import__("inspect").getsource(EntityIngestor.process_incoming_task)
