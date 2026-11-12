from app.knowloom.entity_store.normalizer import apply_glossary, dedupe_extracted_entities
from app.knowloom.models import BlockEntityExtraction, ExtractedEntity, TextBlock

def test_glossary_overrides_identity_and_reports_unmatched():
    extraction = BlockEntityExtraction(block=TextBlock(block_index=0, l1_text="学业预警"), entities=[ExtractedEntity(name="学业预警")])
    unmatched = apply_glossary([extraction], [{"name":"学业预警","aliases":["预警"],"definition":"学校发出的书面警示"},{"name":"不存在术语","definition":"x"}])
    incoming = dedupe_extracted_entities([extraction])[0]
    assert incoming.identity_source == "user"
    assert incoming.identity_user_text == "学校发出的书面警示"
    assert unmatched == ["不存在术语"]
