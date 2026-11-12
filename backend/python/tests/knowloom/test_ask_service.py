import asyncio
from app.knowloom.models import KnowLoomQueryResult, RetrievedEntity, StoredAttribute, StoredAttributeEvidence
from app.knowloom.services.ask import KnowLoomAskService

class Query:
    async def query(self, name, *, top_k=None):
        evidence=StoredAttributeEvidence(evidence_text="第十二条：应完成规定课程。", document_title="细则", document_version=2, block_ref_id=9)
        return KnowLoomQueryResult(query=name, retrieved_entities=[RetrievedEntity(id=1, canonical_name="学位申请", attributes=[StoredAttribute(id=3, attr_type="conditions", value_text="应完成规定课程。", evidence=[evidence])])])

class Blocks:
    def search_blocks(self, scope, query, *, limit): return []

def test_ask_returns_cited_evidence_and_personal_boundary():
    answer=asyncio.run(KnowLoomAskService(query_service=Query(), repository=Blocks()).ask("我能申请学位吗"))
    assert answer.personal_case is True
    assert "[1]" in answer.answer
    assert answer.citations[0]["block_ref_id"] == 9

class CitedAnswer:
    async def chat_json(self, **kwargs): return {"answer": "应完成规定课程。 [1]"}

def test_ask_uses_valid_cited_llm_answer():
    answer=asyncio.run(KnowLoomAskService(query_service=Query(), repository=Blocks(), llm_client=CitedAnswer()).ask("学位申请条件"))
    assert answer.answer == "应完成规定课程。 [1]"

from app.knowloom.services.ask import asks_for_handling

def test_handling_questions_request_relation_expansion():
    assert asks_for_handling("休学找谁办理")
    assert not asks_for_handling("休学的定义是什么")
