import asyncio

from app.knowloom.constants import attribute_schema_payload
from app.knowloom.entity_store.attribute_decider import AttributeDecisionMaker
from app.knowloom.entity_store.models import AttributeCandidate, AttributeRetrievalResult, EntityAttributeInput
from app.knowloom.models import BlockExtractionResult, ExtractedEntity, TextBlock
from app.knowloom.services.entity_extractor import EntityExtractor


class SlotLLM:
    async def chat_json(self, **kwargs):
        return {
            "entities": [
                {
                    "name": "绩点",
                    "entity_type": "term",
                    "admission_score": {"aggregate_score": 0.9},
                    "attributes": [
                        {"slot": "deadline", "value": "每年 9 月提交", "evidence": "第十条", "confidence": 0.9},
                        {"slot": "ratio", "value": "比例为 20%", "evidence": "第十一条", "confidence": 0.9},
                    ],
                }
            ]
        }


def test_legacy_attribute_object_is_migrated_to_slot_list() -> None:
    result = BlockExtractionResult.model_validate(
        {
            "entities": [
                {
                    "name": "事项",
                    "attributes": {
                        "constraints": [{"value": "满足条件", "evidence": "条文"}],
                        "mechanism": [{"value": "旧机制", "evidence": "条文"}],
                    },
                }
            ]
        }
    )

    values = result.entities[0].attributes.iter_values()
    assert [(slot, value.value) for slot, value in values] == [("conditions", "满足条件"), ("notes", "旧机制")]


def test_term_disallowed_and_unknown_slots_are_downgraded_to_notes() -> None:
    extractor = EntityExtractor(SlotLLM(), config=None)  # type: ignore[arg-type]
    extractor.config = type("Config", (), {"max_concurrency": 1, "entity_admission_judge_enabled": False})()
    block = TextBlock(block_index=0, l1_text="第十条。", split_reason="heading")

    result = asyncio.run(extractor.extract_one(block))

    assert [slot for slot, _ in result.entities[0].attributes.iter_values()] == ["notes", "notes"]
    assert any("not allowed for term" in warning for warning in result.warnings)
    assert any("unknown slot ratio" in warning for warning in result.warnings)


def test_append_slots_only_merge_exact_duplicates() -> None:
    incoming = EntityAttributeInput(attr_type="materials", value_text="成绩单", evidence="条文")
    different = AttributeRetrievalResult(
        input_index=0,
        attr_type="materials",
        value_text="成绩单",
        mode="exact",
        group_size=2,
        candidates=[AttributeCandidate(attribute_id=7, entity_id=1, attr_type="materials", value_text="申请表", confidence=0.8)],
    )
    exact = AttributeRetrievalResult(
        input_index=0,
        attr_type="materials",
        value_text="成绩单",
        mode="exact",
        group_size=2,
        exact_match=type("Exact", (), {"id": 8, "value_text": "成绩单"})(),  # lightweight candidate shape
    )

    decisions = AttributeDecisionMaker().decide([incoming], [different])
    exact_decisions = AttributeDecisionMaker().decide([incoming], [exact])

    assert decisions[0].action == "add"
    assert exact_decisions[0].action == "merge"


def test_attribute_schema_is_registry_driven() -> None:
    schema = attribute_schema_payload()
    slots = {item["key"] for item in schema["slots"]}
    assert {"conditions", "materials", "deadline", "notes"} <= slots
    assert "deadline" not in schema["entity_types"]["term"]
