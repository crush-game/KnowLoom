from app.knowloom.services.document_relations import detect_document_relations

def test_detects_amendment_and_repeal_targets():
    relations = detect_document_relations("本通知修订《奖学金办法》第十二条，原《旧实施细则》同时废止。")
    assert {(item.relation_type, item.target_title) for item in relations} == {("amends", "奖学金办法"), ("repeals", "旧实施细则")}
