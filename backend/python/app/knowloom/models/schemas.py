from typing import Any, Literal

from pydantic import BaseModel, Field, RootModel, field_validator, model_validator

from app.knowloom.constants import ATTRIBUTE_TYPES, FALLBACK_SLOT, SLOTS


AttributeType = str


class AttributeValue(BaseModel):
    slot: str = ""
    value: str = Field(default="", description="Attribute value extracted from the block.")
    evidence: str = Field(default="", description="Evidence copied from the block text.")
    confidence: float = Field(default=0.7, ge=0.0, le=1.0)

    @model_validator(mode="before")
    @classmethod
    def normalize_legacy_evidence(cls, data: Any) -> Any:
        if isinstance(data, dict) and "evidence" not in data and "source_text" in data:
            data = {**data, "evidence": data.get("source_text", "")}
        return data

    @field_validator("slot", mode="before")
    @classmethod
    def clean_slot(cls, value: str) -> str:
        return "_".join(str(value or "").strip().lower().split())

    @field_validator("value", "evidence")
    @classmethod
    def clean_text(cls, value: str) -> str:
        return " ".join(str(value or "").split())


class AttributeBucket(RootModel[list[AttributeValue]]):
    root: list[AttributeValue] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def migrate_legacy_bucket(cls, data: Any) -> Any:
        if isinstance(data, list):
            return data
        if not isinstance(data, dict):
            return []
        if "root" in data:
            return data["root"]
        if "items" in data:
            return data["items"]
        legacy_mapping = {
            "definition": "definition",
            "purpose": "purpose",
            "constraints": "conditions",
            "related": "related",
            "core_idea": FALLBACK_SLOT,
            "mechanism": FALLBACK_SLOT,
            "components": FALLBACK_SLOT,
        }
        values: list[dict[str, Any]] = []
        for key, raw_values in data.items():
            slot = legacy_mapping.get(key, FALLBACK_SLOT)
            for raw_value in raw_values if isinstance(raw_values, list) else []:
                if isinstance(raw_value, dict):
                    values.append({"slot": slot, **raw_value})
        return values

    def iter_values(self) -> list[tuple[AttributeType, AttributeValue]]:
        return [(item.slot or FALLBACK_SLOT, item) for item in self.root]




class EntityAdmissionScore(BaseModel):
    definable: float = Field(default=1.0, ge=0.0, le=1.0)
    query_entry: float = Field(default=1.0, ge=0.0, le=1.0)
    independent_scope: float = Field(default=1.0, ge=0.0, le=1.0)
    stable_relations: float = Field(default=1.0, ge=0.0, le=1.0)
    key_sentence: float = Field(default=1.0, ge=0.0, le=1.0)
    aggregate_score: float = Field(default=1.0, ge=0.0, le=1.0)
    rationale: str = ""

    @model_validator(mode="before")
    @classmethod
    def fill_missing_dimensions_from_aggregate(cls, data: Any) -> Any:
        if not isinstance(data, dict) or "aggregate_score" not in data:
            return data

        aggregate_score = data.get("aggregate_score")
        return {
            "definable": aggregate_score,
            "query_entry": aggregate_score,
            "independent_scope": aggregate_score,
            "stable_relations": aggregate_score,
            "key_sentence": aggregate_score,
            **data,
        }

    @field_validator("rationale")
    @classmethod
    def clean_rationale(cls, value: str) -> str:
        return " ".join(str(value or "").split())

    @model_validator(mode="after")
    def recompute_aggregate_score(self) -> "EntityAdmissionScore":
        scores = [
            self.definable,
            self.query_entry,
            self.independent_scope,
            self.stable_relations,
            self.key_sentence,
        ]
        self.aggregate_score = round(sum(scores) / len(scores), 4)
        return self


class EntityAdmissionJudgeScore(BaseModel):
    decision: str = Field(default="entity")
    entity_score: float = Field(default=1.0, ge=0.0, le=1.0)
    positive_scores: dict[str, float] = Field(default_factory=dict)
    deductions: dict[str, float] = Field(default_factory=dict)
    parent_entity: str = ""
    attribute_type: str = ""
    reason: str = ""

    @field_validator("decision", "parent_entity", "attribute_type", "reason", mode="before")
    @classmethod
    def clean_judge_text(cls, value: Any) -> str:
        return " ".join(str(value or "").split())


class ExtractedEntity(BaseModel):
    name: str
    entity_type: str = Field(default="concept")
    aliases: list[str] = Field(default_factory=list)
    identity_description: str = Field(
        default="",
        description="Short model-generated description used only for entity identity resolution.",
    )
    identity_source: str = "model_prior"
    identity_user_text: str = ""
    admission_score: EntityAdmissionScore = Field(default_factory=EntityAdmissionScore)
    admission_judge: EntityAdmissionJudgeScore | None = None
    attributes: AttributeBucket = Field(default_factory=AttributeBucket)

    @field_validator("name", "entity_type", "identity_description")
    @classmethod
    def clean_required_text(cls, value: str) -> str:
        return " ".join(str(value or "").split())

    @field_validator("aliases")
    @classmethod
    def clean_aliases(cls, values: list[str]) -> list[str]:
        cleaned: list[str] = []
        seen: set[str] = set()
        for item in values:
            alias = " ".join(str(item or "").split())
            if alias and alias not in seen:
                seen.add(alias)
                cleaned.append(alias)
        return cleaned


class TextBlock(BaseModel):
    block_index: int = Field(ge=0)
    heading: str = ""
    anchor_entity: str = ""
    candidate_entities: list[str] = Field(default_factory=list)
    l1_text: str
    split_reason: str = ""
    anchor_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    parent_block_index: int | None = None
    chunk_index: int = Field(default=0, ge=0)
    chunk_count: int = Field(default=1, ge=1)
    char_start: int = Field(default=-1)
    char_end: int = Field(default=-1)

    @field_validator("heading", "anchor_entity", "l1_text", "split_reason")
    @classmethod
    def clean_block_text(cls, value: str) -> str:
        return str(value or "").strip()

    @field_validator("candidate_entities")
    @classmethod
    def clean_candidate_entities(cls, values: list[str]) -> list[str]:
        cleaned: list[str] = []
        seen: set[str] = set()
        for item in values:
            candidate = " ".join(str(item or "").split())
            if candidate and candidate not in seen:
                seen.add(candidate)
                cleaned.append(candidate)
        return cleaned


class BlockSplitResult(BaseModel):
    blocks: list[TextBlock] = Field(default_factory=list)


class BlockEntityExtraction(BaseModel):
    block: TextBlock
    entities: list[ExtractedEntity] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    dropped_candidates: list[dict[str, Any]] = Field(default_factory=list)


class BlockExtractionFailure(BaseModel):
    block_index: int = Field(ge=0)
    heading: str = ""
    anchor_entity: str = ""
    l1_text: str = Field(default="", exclude=True)
    error: str = ""

    @field_validator("heading", "anchor_entity", "l1_text", "error")
    @classmethod
    def clean_failure_text(cls, value: str) -> str:
        return str(value or "").strip()


class BlockExtractionResult(BaseModel):
    entities: list[ExtractedEntity] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class KnowLoomPreprocessResult(BaseModel):
    input_text: str
    blocks: list[BlockEntityExtraction] = Field(default_factory=list)
    timings: dict[str, float] = Field(default_factory=dict)
    extraction_failures: list[BlockExtractionFailure] = Field(default_factory=list, exclude=True)

    @property
    def entity_count(self) -> int:
        return sum(len(block.entities) for block in self.blocks)


class StoredAttributeEvidence(BaseModel):
    evidence_text: str = ""
    note_id: str = ""
    block_id: str = ""
    block_index: int = -1
    block_ref_id: int | None = None
    document_id: int | None = None
    document_title: str = ""
    document_version: int = 0
    doc_number: str = ""
    doc_kind: str = ""
    issuer: str = ""
    issuer_level: str = ""
    effective_at: str = ""
    source_url: str = ""


class StoredAttribute(BaseModel):
    id: int = 0
    attr_type: str
    value_text: str
    confidence: float = Field(default=0.7, ge=0.0, le=1.0)
    evidence: list[StoredAttributeEvidence] = Field(default_factory=list)

    @field_validator("attr_type", mode="before")
    @classmethod
    def normalize_stored_slot(cls, value: str) -> str:
        key = str(value or "").strip()
        return key if key in SLOTS else FALLBACK_SLOT


class RetrievedEntity(BaseModel):
    id: int
    canonical_name: str
    normalized_name: str = ""
    entity_type: str = "concept"
    aliases: list[str] = Field(default_factory=list)
    identity_description: str = ""
    summary: str = ""
    description_for_match: str = ""
    score: float = 0.0
    rank: int = 0
    source: str = ""
    attributes: list[StoredAttribute] = Field(default_factory=list)

    def attributes_by_type(self, attr_type: str) -> list[StoredAttribute]:
        return [attribute for attribute in self.attributes if attribute.attr_type == attr_type]


class DependencyEdge(BaseModel):
    source_id: int
    target_id: int
    relation: str
    graph_type: Literal["semantic", "conditional"]
    evidence: str = ""
    weight: float = Field(default=1.0, ge=0.0)


class DependencyGraph(BaseModel):
    root_entity_id: int
    entities: list[RetrievedEntity] = Field(default_factory=list)
    semantic_edges: list[DependencyEdge] = Field(default_factory=list)
    conditional_edges: list[DependencyEdge] = Field(default_factory=list)
    ordered_entity_ids: list[int] = Field(default_factory=list)
    cycles: list[list[int]] = Field(default_factory=list)


class KnowLoomQueryResult(BaseModel):
    query: str
    root_entity: RetrievedEntity | None = None
    retrieved_entities: list[RetrievedEntity] = Field(default_factory=list)
    graph: DependencyGraph | None = None
    answer: str = ""
    warnings: list[str] = Field(default_factory=list)


class KnowLoomIndexSearchResult(BaseModel):
    query: str
    backend_status: dict[str, Any] = Field(default_factory=dict)
    timings: dict[str, float] = Field(default_factory=dict)
    elasticsearch_results: list[RetrievedEntity] = Field(default_factory=list)
    milvus_results: list[RetrievedEntity] = Field(default_factory=list)
    fused_results: list[RetrievedEntity] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
