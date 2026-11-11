from app.knowloom.models import DependencyGraph, RetrievedEntity, StoredAttribute


from app.knowloom.constants import SLOT_SPECS, slot_spec



class StructuredAnswerGenerator:
    def generate(self, graph: DependencyGraph) -> str:
        if not graph.entities:
            return ""

        entity_by_id = {entity.id: entity for entity in graph.entities}
        root = entity_by_id.get(graph.root_entity_id) or graph.entities[0]
        ordered_entities = [entity_by_id[entity_id] for entity_id in graph.ordered_entity_ids if entity_id in entity_by_id]
        if root.id not in {entity.id for entity in ordered_entities}:
            ordered_entities.insert(0, root)
        sources, source_numbers = self.collect_sources(ordered_entities)

        lines = [
            f"# {root.canonical_name}",
            "",
            *self.summary_lines(root),
            "",
        ]

        for entity in ordered_entities:
            lines.extend(self.entity_section(entity, source_numbers))
            lines.append("")

        relation_lines = self.relation_section(graph, entity_by_id)
        if relation_lines:
            lines.extend(relation_lines)

        if sources:
            lines.extend(self.source_section(sources))

        return "\n".join(trim_trailing_blank_lines(lines)).strip() + "\n"

    def summary_lines(self, entity: RetrievedEntity) -> list[str]:
        summary = entity.summary or entity.identity_description or first_attribute_value(entity)
        if not summary:
            return [f"{entity.canonical_name} 是一个需要继续补充属性证据的实体。"]
        return [summary]

    def entity_section(self, entity: RetrievedEntity, source_numbers: dict[tuple[int | None, int | None, str], int]) -> list[str]:
        lines = [f"## {entity.canonical_name}"]
        if entity.identity_description:
            lines.extend(["", entity.identity_description])

        for spec in SLOT_SPECS:
            attributes = [attribute for attribute in entity.attributes if attribute.attr_type == spec.key]
            if not attributes:
                continue
            lines.extend(["", f"### {spec.title}"])
            for attribute in attributes[:6]:
                lines.append(f"- {attribute.value_text}{self.citations_for(attribute, source_numbers)}")
        if len(lines) == 1:
            lines.extend(["", entity.summary or entity.identity_description or "暂无可用属性。"])
        return lines

    def collect_sources(self, entities: list[RetrievedEntity]) -> tuple[list[object], dict[tuple[int | None, int | None, str], int]]:
        sources: list[object] = []
        numbers: dict[tuple[int | None, int | None, str], int] = {}
        for entity in entities:
            for attribute in entity.attributes:
                for evidence in attribute.evidence:
                    key = (evidence.document_id, evidence.block_ref_id, evidence.evidence_text)
                    if key not in numbers:
                        numbers[key] = len(sources) + 1
                        sources.append(evidence)
        return sources, numbers

    def citations_for(self, attribute: StoredAttribute, source_numbers: dict[tuple[int | None, int | None, str], int]) -> str:
        numbers = [
            source_numbers[(evidence.document_id, evidence.block_ref_id, evidence.evidence_text)]
            for evidence in attribute.evidence
            if (evidence.document_id, evidence.block_ref_id, evidence.evidence_text) in source_numbers
        ]
        return "".join(f" [{number}]" for number in numbers)

    def source_section(self, sources: list[object]) -> list[str]:
        lines = ["## 来源"]
        for index, evidence in enumerate(sources, start=1):
            title = evidence.document_title or evidence.note_id or "未命名文件"
            details = [title]
            if evidence.doc_number:
                details.append(evidence.doc_number)
            if evidence.document_version:
                details.append(f"v{evidence.document_version}")
            if evidence.issuer:
                details.append(evidence.issuer)
            if evidence.effective_at:
                details.append(f"自 {evidence.effective_at} 起施行")
            if evidence.block_ref_id:
                details.append(f"block {evidence.block_ref_id}")
            lines.append(f"[{index}] {' · '.join(details)}")
        return lines

    def relation_section(self, graph: DependencyGraph, entity_by_id: dict[int, RetrievedEntity]) -> list[str]:
        lines: list[str] = []
        edges = [*graph.semantic_edges, *graph.conditional_edges]
        if edges:
            lines.extend(["## 依赖关系"])
            for edge in edges:
                source = entity_by_id.get(edge.source_id)
                target = entity_by_id.get(edge.target_id)
                if source is None or target is None:
                    continue
                relation = slot_spec(edge.relation).title
                graph_label = "条件依赖" if edge.graph_type == "conditional" else "语义依赖"
                lines.append(f"- {source.canonical_name} -> {target.canonical_name}：{graph_label} / {relation}")
        if graph.cycles:
            if not lines:
                lines.append("## 依赖关系")
            lines.append("")
            lines.append("### 环处理")
            for cycle in graph.cycles:
                names = [entity_by_id[entity_id].canonical_name for entity_id in cycle if entity_id in entity_by_id]
                if names:
                    lines.append(f"- {' -> '.join(names)} 构成循环依赖，生成时按检索顺序展开并避免重复展开。")
        return lines


def first_attribute_value(entity: RetrievedEntity) -> str:
    for attribute in entity.attributes:
        if attribute.value_text:
            return attribute.value_text
    return ""


def trim_trailing_blank_lines(lines: list[str]) -> list[str]:
    while lines and not lines[-1]:
        lines.pop()
    return lines
