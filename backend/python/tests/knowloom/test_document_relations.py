from app.knowloom.entity_store.conflict_gate import AttributeWithSources, SourceInfo, temporal_outcome
from datetime import date
class Relations:
 def amends(self, incoming_doc_key, target_doc_key): return (incoming_doc_key,target_doc_key)==("new","old")
def test_amendment_relation_unlocks_temporal_replacement():
 assert temporal_outcome(SourceInfo(doc_key="new", effective_at=date(2024,1,1)), AttributeWithSources(attribute_id=1, sources=(SourceInfo(doc_key="old", effective_at=date(2025,1,1)),)), .9, Relations()) == "supersede_target"
