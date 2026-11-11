from app.knowloom.entity_store.repository_mappers import group_attribute_rows
from app.knowloom.models import DependencyGraph, RetrievedEntity, StoredAttribute, StoredAttributeEvidence
from app.knowloom.services.answer_generator import StructuredAnswerGenerator
from app.knowloom.services.doc_meta import suggest_effective_at


def test_effective_date_suggestion_is_detected_without_persisting() -> None:
    assert suggest_effective_at("附件。本细则自 2025 年 9 月 1 日起施行。") == "2025-09-01"
    assert suggest_effective_at("本文件自发布之日起施行。") == ""


def test_attribute_evidence_includes_document_source_metadata() -> None:
    attributes = group_attribute_rows(
        [
            {
                "entity_id": 7,
                "attribute_id": 11,
                "attr_type": "definition",
                "value_text": "申请前应完成规定课程。",
                "confidence": 0.9,
                "evidence_text": "第十二条：申请前应完成规定课程。",
                "note_id": "degree-rules",
                "block_id": "degree-rules:block:3",
                "block_index": 3,
                "block_ref_id": 104,
                "document_id": 9,
                "document_title": "研究生学位授予工作细则",
                "document_version": 2,
                "doc_number": "校发〔2025〕9号",
                "doc_kind": "regulation",
                "issuer": "研究生院",
                "issuer_level": "university",
                "effective_at": "2025-09-01",
                "source_url": "https://example.edu/rules",
            }
        ]
    )

    evidence = attributes[7][0].evidence[0]
    assert evidence.document_id == 9
    assert evidence.block_ref_id == 104
    assert evidence.document_title == "研究生学位授予工作细则"
    assert evidence.document_version == 2
    assert evidence.effective_at == "2025-09-01"


def test_structured_answer_uses_consistent_source_numbers() -> None:
    evidence = StoredAttributeEvidence(
        evidence_text="第十二条：申请前应完成规定课程。",
        document_id=9,
        block_ref_id=104,
        document_title="研究生学位授予工作细则",
        document_version=2,
        doc_number="校发〔2025〕9号",
        issuer="研究生院",
        effective_at="2025-09-01",
    )
    entity = RetrievedEntity(
        id=1,
        canonical_name="学位申请",
        attributes=[
            StoredAttribute(
                id=1,
                attr_type="definition",
                value_text="申请前应完成规定课程。",
                evidence=[evidence],
            )
        ],
    )

    answer = StructuredAnswerGenerator().generate(DependencyGraph(root_entity_id=1, entities=[entity], ordered_entity_ids=[1]))

    assert "申请前应完成规定课程。 [1]" in answer
    assert "[1] 研究生学位授予工作细则 · 校发〔2025〕9号 · v2 · 研究生院 · 自 2025-09-01 起施行 · block 104" in answer
