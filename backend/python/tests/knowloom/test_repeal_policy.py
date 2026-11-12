from app.knowloom.services.document_relations import detect_document_relations

def test_repeal_detection_does_not_cross_previous_clause():
    relations=detect_document_relations("修订《新办法》，原《旧办法》同时废止。")
    assert [(item.relation_type,item.target_title) for item in relations if item.relation_type=="repeals"] == [("repeals","旧办法")]
