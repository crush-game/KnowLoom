from app.knowloom.config import KnowLoomSettings, settings
from app.knowloom.entity_store.models import EntityScope
from app.knowloom.models import KnowLoomQueryResult
from app.knowloom.services.answer_generator import StructuredAnswerGenerator
from app.knowloom.services.dependency_graph import build_dependency_graph
from app.knowloom.services.retriever import KnowLoomRetriever


class KnowLoomQueryService:
    def __init__(
        self,
        retriever: KnowLoomRetriever | None = None,
        answer_generator: StructuredAnswerGenerator | None = None,
        config: KnowLoomSettings = settings,
        scope: EntityScope | None = None,
    ) -> None:
        self.config = config
        self.retriever = retriever or KnowLoomRetriever(config=config, scope=scope)
        self.answer_generator = answer_generator or StructuredAnswerGenerator()

    async def query(self, entity_name: str, *, top_k: int | None = None) -> KnowLoomQueryResult:
        entities, warnings = await self.retriever.retrieve(entity_name, top_k=top_k)
        if not entities:
            return KnowLoomQueryResult(query=entity_name, warnings=warnings)

        root = entities[0]
        graph = build_dependency_graph(entities, root_entity_id=root.id)
        answer = self.answer_generator.generate(graph)
        return KnowLoomQueryResult(
            query=entity_name,
            root_entity=root,
            retrieved_entities=entities,
            graph=graph,
            answer=answer,
            warnings=warnings,
        )
