from app.knowloom.models import EntityAdmissionJudgeScore, ExtractedEntity, TextBlock
from app.knowloom.services.entity_extractor import demote_to_parent

def test_condition_is_demoted_to_accepted_parent_slot():
    parent = ExtractedEntity(name="推免", entity_type="procedure")
    child = ExtractedEntity(name="思想政治表现良好")
    outcome = demote_to_parent(child, EntityAdmissionJudgeScore(decision="condition", entity_score=.4, parent_entity="推免"), [parent], TextBlock(block_index=0, l1_text="条件"))
    assert outcome["action"] == "demoted"
    assert parent.attributes.root[0].slot == "conditions"
