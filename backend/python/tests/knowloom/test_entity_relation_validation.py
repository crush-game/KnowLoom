from app.knowloom.models import ExtractedEntity, ExtractedRelation, TextBlock
from app.knowloom.services.entity_extractor import normalize_entity_relations


def test_relation_requires_controlled_type_target_and_exact_evidence():
    block=TextBlock(block_index=0,l1_text="休学申请由研究生院受理。")
    entity=ExtractedEntity(name="休学申请",relations=[
        ExtractedRelation(type="handled_by",target="研究生院",evidence="由研究生院受理"),
        ExtractedRelation(type="requires",target="研究生院",evidence="由研究生院受理"),
        ExtractedRelation(type="handled_by",target="不存在部门",evidence="由研究生院受理"),
    ])
    warnings=normalize_entity_relations(entity,block)
    assert [(item.type,item.target) for item in entity.relations] == [("handled_by","研究生院")]
    assert len(warnings) == 2
