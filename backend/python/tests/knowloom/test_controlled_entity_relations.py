from app.knowloom.models import RetrievedEntity, StoredEntityRelation
from app.knowloom.services.dependency_graph import build_dependency_graph

def test_stored_relation_precedes_attribute_fallback_and_non_dependency_does_not_order():
    office=RetrievedEntity(id=2,canonical_name="研究生院")
    leave=RetrievedEntity(id=1,canonical_name="休学",relations=[StoredEntityRelation(source_entity_id=1,target_name="研究生院",target_entity_id=2,relation_type="handled_by",dependency=False,evidence="由研究生院受理")])
    graph=build_dependency_graph([leave,office],root_entity_id=1)
    assert graph.conditional_edges[0].relation == "handled_by"
    assert graph.cycles == []
