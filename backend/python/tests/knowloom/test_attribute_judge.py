import asyncio
from datetime import date

from app.knowloom.config import KnowLoomSettings
from app.knowloom.entity_store.attribute_decider import AttributeDecisionMaker
from app.knowloom.entity_store.conflict_gate import AttributeWithSources, NoDocumentRelations, SourceInfo
from app.knowloom.entity_store.models import AttributeCandidate, AttributeRetrievalResult, EntityAttributeInput


class ScriptedJudge:
    def __init__(self, response):
        self.response = response
        self.calls = []

    async def chat_json(self, **kwargs):
        self.calls.append(kwargs)
        return self.response


def retrieval(attribute: EntityAttributeInput) -> AttributeRetrievalResult:
    return AttributeRetrievalResult(
        input_index=0,
        attr_type=attribute.attr_type,
        value_text=attribute.value_text,
        mode="full_scan",
        group_size=1,
        candidates=[AttributeCandidate(attribute_id=52, entity_id=1, attr_type=attribute.attr_type, value_text="一等学业奖学金比例为 20%", confidence=0.9)],
    )


def source(**values) -> SourceInfo:
    defaults = {"doc_key": "scholarship", "version_no": 1, "issuer_level": "university", "effective_at": date(2024, 9, 1)}
    defaults.update(values)
    return SourceInfo(**defaults)


def test_judge_temporal_conflict_is_gated_then_superseded() -> None:
    attribute = EntityAttributeInput(attr_type="conditions", value_text="一等学业奖学金比例调整为 15%", evidence="第十二条")
    judge = ScriptedJudge({"decisions": [{"input_index": 0, "action": "conflict", "kind": "temporal", "target_attribute_id": 52, "confidence": 0.9, "reason": "2025 修订"}]})
    decider = AttributeDecisionMaker(llm_client=judge, config=KnowLoomSettings(_env_file=None))
    decisions = asyncio.run(decider.decide_async([attribute], [retrieval(attribute)], source_contexts={0: (source(version_no=2, effective_at=date(2025, 9, 1)), AttributeWithSources(attribute_id=52, sources=(source(),)))}, relations=NoDocumentRelations()))
    assert decisions[0].action == "supersede"
    assert decisions[0].target_attribute_id == 52
    assert len(judge.calls) == 1


def test_judge_contextual_conflict_keeps_both_with_qualifiers() -> None:
    attribute = EntityAttributeInput(attr_type="conditions", value_text="2024 级起不再要求发表论文", evidence="第十五条")
    judge = ScriptedJudge({"decisions": [{"input_index": 0, "action": "conflict", "kind": "contextual", "target_attribute_id": 52, "confidence": 0.8, "qualifier_incoming": "2024 级起", "qualifier_target": "2023 级及以前", "reason": "入学年级不同"}]})
    decider = AttributeDecisionMaker(llm_client=judge, config=KnowLoomSettings(_env_file=None))
    decisions = asyncio.run(decider.decide_async([attribute], [retrieval(attribute)], source_contexts={0: (source(doc_key="degree-rules-2024", version_no=2, effective_at=date(2025, 9, 1)), AttributeWithSources(attribute_id=52, sources=(source(audience="2023 级及以前"),))) }))
    assert decisions[0].action == "qualify"
    assert decisions[0].qualifier_incoming == "2024 级起"


def test_invalid_judge_target_is_queued_for_manual_review() -> None:
    attribute = EntityAttributeInput(attr_type="conditions", value_text="休学期间不保留学籍", evidence="问答页")
    judge = ScriptedJudge({"decisions": [{"input_index": 0, "action": "conflict", "kind": "factual", "target_attribute_id": 99, "confidence": 0.9}]})
    decider = AttributeDecisionMaker(llm_client=judge, config=KnowLoomSettings(_env_file=None))
    decisions = asyncio.run(decider.decide_async([attribute], [retrieval(attribute)]))
    assert decisions[0].action == "queue"


def test_judge_failure_falls_back_to_add_without_rewriting() -> None:
    attribute = EntityAttributeInput(attr_type="conditions", value_text="请假 3 天以内由副书记审批", evidence="手册")
    judge = ScriptedJudge({"unexpected": []})
    decider = AttributeDecisionMaker(llm_client=judge, config=KnowLoomSettings(_env_file=None))
    decisions = asyncio.run(decider.decide_async([attribute], [retrieval(attribute)]))
    assert decisions[0].action == "add"
    assert decisions[0].source == "rule_fallback"
