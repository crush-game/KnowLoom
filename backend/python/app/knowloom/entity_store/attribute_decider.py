from __future__ import annotations

from typing import Any

from app.knowloom.config import KnowLoomSettings, settings
from app.knowloom.constants import slot_spec
from app.knowloom.entity_store.conflict_gate import AttributeWithSources, NoDocumentRelations, SourceInfo, contextual_outcome, temporal_outcome
from app.knowloom.entity_store.models import AttributeDecision, AttributeRetrievalResult, EntityAttributeInput
from app.knowloom.llm.client import KnowLoomLLMClient

MAX_ATTRIBUTE_DECISION_CANDIDATES = 5
ATTRIBUTE_DECISION_SYSTEM_PROMPT = """
你是 KnowLoom 的学校规章制度属性合并裁判。判断新属性和候选属性的关系，不能根据常识编造来源。

动作：
- add：新知识点；
- merge：同一事实，仅合并证据；
- enrich：同一规定的更完整表述，new_value_text 必须给出完整替换文本；
- update：新规定取代曾经有效的旧规定；
- conflict：两条说法冲突，必须给出 kind；
- review：信息不足，人工审核。

kind 只能是 temporal、contextual、factual：
- temporal 是版本、修订或施行时间造成的新旧替代；
- contextual 是年级、学生类别、学院等适用范围不同，两条都可成立；
- factual 是至少一条可能错误或无法从材料判断。

严格规则：attr_type 相同或语义相关不等于同一事实；target_attribute_id 必须来自该属性提供的 candidates；不确定就 review。只输出 JSON：{"decisions":[...]}。
""".strip()


class AttributeDecisionMaker:
    """Run only deterministic prefilters locally; delegate semantic relationships to the judge."""

    def __init__(self, *, llm_client: Any | None = None, config: KnowLoomSettings = settings) -> None:
        self.config = config
        self.llm_client = llm_client or KnowLoomLLMClient(config)

    def prefilter(
        self,
        incoming_attributes: list[EntityAttributeInput],
        retrieval_results: list[AttributeRetrievalResult],
    ) -> tuple[list[AttributeDecision], list[tuple[int, EntityAttributeInput, AttributeRetrievalResult]]]:
        results_by_index = {result.input_index: result for result in retrieval_results}
        resolved: list[AttributeDecision] = []
        pending: list[tuple[int, EntityAttributeInput, AttributeRetrievalResult]] = []
        for input_index, attribute in enumerate(incoming_attributes):
            result = results_by_index.get(input_index)
            if result is None or (not result.candidates and result.exact_match is None):
                resolved.append(AttributeDecision(input_index=input_index, action="add", incoming_attribute=attribute, confidence=attribute.confidence, reason="no attribute candidate found"))
                continue
            if result.exact_match is not None and getattr(result.exact_match, "status", "active") == "active":
                resolved.append(
                    AttributeDecision(
                        input_index=input_index,
                        action="merge",
                        incoming_attribute=attribute,
                        target_attribute_id=result.exact_match.id,
                        target_value_text=result.exact_match.value_text,
                        confidence=1.0,
                        reason="exact fingerprint match",
                    )
                )
                continue
            if result.exact_match is not None and getattr(result.exact_match, "status", "active") != "active":
                pending.append((input_index, attribute, result))
                continue
            if slot_spec(attribute.attr_type).merge_policy == "append":
                resolved.append(AttributeDecision(input_index=input_index, action="add", incoming_attribute=attribute, confidence=attribute.confidence, reason="append slot keeps distinct values without adjudication"))
                continue
            pending.append((input_index, attribute, result))
        return resolved, pending

    def decide(self, incoming_attributes: list[EntityAttributeInput], retrieval_results: list[AttributeRetrievalResult]) -> list[AttributeDecision]:
        """Safe synchronous fallback retained for integrations that cannot await a judge.

        It deliberately never uses the removed Chinese token-overlap heuristics.
        """
        resolved, pending = self.prefilter(incoming_attributes, retrieval_results)
        resolved.extend(
            AttributeDecision(
                input_index=index,
                action="add",
                incoming_attribute=attribute,
                confidence=attribute.confidence,
                reason="semantic adjudication deferred",
                source="rule_fallback",
            )
            for index, attribute, _ in pending
        )
        return sorted(resolved, key=lambda decision: decision.input_index)

    async def decide_async(
        self,
        incoming_attributes: list[EntityAttributeInput],
        retrieval_results: list[AttributeRetrievalResult],
        *,
        source_contexts: dict[int, tuple[SourceInfo | None, AttributeWithSources | None]] | None = None,
        relations: Any | None = None,
    ) -> list[AttributeDecision]:
        resolved, pending = self.prefilter(incoming_attributes, retrieval_results)
        if not pending:
            return sorted(resolved, key=lambda decision: decision.input_index)
        if not self.config.attribute_decision_judge_enabled:
            return self._with_fallback(resolved, pending)
        try:
            payload = {
                "attributes": [build_attribute_decision_payload(attribute, result) | {"input_index": index} for index, attribute, result in pending],
                "instructions": "Return exactly one decision for every input_index.",
            }
            response = await self.llm_client.chat_json(
                system_prompt=ATTRIBUTE_DECISION_SYSTEM_PROMPT,
                user_payload=payload,
                operation_name="KnowLoom attribute decision judge",
                model=self.config.attribute_decision_judge_model or None,
            )
            judged = self._normalize_judgment(response, pending, source_contexts or {}, relations or NoDocumentRelations())
        except Exception:
            return self._with_fallback(resolved, pending)
        return sorted([*resolved, *judged], key=lambda decision: decision.input_index)

    def _with_fallback(self, resolved: list[AttributeDecision], pending: list[tuple[int, EntityAttributeInput, AttributeRetrievalResult]]) -> list[AttributeDecision]:
        return sorted(
            [
                *resolved,
                *[
                    AttributeDecision(input_index=index, action="add", incoming_attribute=attribute, confidence=attribute.confidence, reason="attribute judge unavailable; stored without rewriting an existing attribute", source="rule_fallback")
                    for index, attribute, _ in pending
                ],
            ],
            key=lambda decision: decision.input_index,
        )

    def _normalize_judgment(
        self,
        response: dict[str, Any],
        pending: list[tuple[int, EntityAttributeInput, AttributeRetrievalResult]],
        source_contexts: dict[int, tuple[SourceInfo | None, AttributeWithSources | None]],
        relations: Any,
    ) -> list[AttributeDecision]:
        by_index = {index: (attribute, result) for index, attribute, result in pending}
        payloads = response.get("decisions") if isinstance(response, dict) else None
        if not isinstance(payloads, list):
            raise ValueError("attribute judge response must contain decisions")
        raw_by_index = {item.get("input_index"): item for item in payloads if isinstance(item, dict) and isinstance(item.get("input_index"), int)}
        decisions: list[AttributeDecision] = []
        for index, (attribute, result) in by_index.items():
            raw = raw_by_index.get(index)
            if raw is None:
                raise ValueError(f"attribute judge omitted input_index {index}")
            decisions.append(self._decision_from_judgment(index, attribute, result, raw, source_contexts.get(index), relations))
        return decisions

    def _decision_from_judgment(
        self,
        input_index: int,
        attribute: EntityAttributeInput,
        result: AttributeRetrievalResult,
        raw: dict[str, Any],
        source_context: tuple[SourceInfo | None, AttributeWithSources | None] | None,
        relations: Any,
    ) -> AttributeDecision:
        action = str(raw.get("action") or "review")
        kind = str(raw.get("kind") or "review")
        target_id = raw.get("target_attribute_id")
        valid_targets = {candidate.attribute_id: candidate for candidate in result.candidates[:MAX_ATTRIBUTE_DECISION_CANDIDATES]}
        if action not in {"add", "merge", "enrich", "update", "conflict", "review"}:
            return self._queue(input_index, attribute, reason="attribute judge returned an unsupported action")
        if action not in {"add", "review"} and (not isinstance(target_id, int) or target_id not in valid_targets):
            return self._queue(input_index, attribute, reason="attribute judge selected a target outside the retrieved candidates")
        confidence = clamp_confidence(raw.get("confidence"), attribute.confidence)
        reason = str(raw.get("reason") or "attribute judge decision")
        candidate = valid_targets.get(target_id) if isinstance(target_id, int) else None
        if action == "add":
            return AttributeDecision(input_index=input_index, action="add", incoming_attribute=attribute, confidence=confidence, reason=reason)
        if action == "merge":
            return AttributeDecision(input_index=input_index, action="merge", incoming_attribute=attribute, target_attribute_id=int(target_id), target_value_text=candidate.value_text if candidate else "", confidence=confidence, reason=reason)
        if action == "enrich":
            complete_value = str(raw.get("new_value_text") or "").strip()
            if not complete_value:
                return self._queue(input_index, attribute, target_id, candidate, confidence, "attribute judge omitted complete enrich text")
            return AttributeDecision(input_index=input_index, action="enrich", incoming_attribute=attribute, target_attribute_id=int(target_id), target_value_text=candidate.value_text if candidate else "", new_value_text=complete_value, confidence=confidence, reason=reason)
        if action == "update" or kind == "temporal":
            incoming_source, target = source_context or (None, None)
            outcome = temporal_outcome(incoming_source, target, confidence, relations) if incoming_source and target else "review"
            if outcome == "supersede_target":
                return AttributeDecision(input_index=input_index, action="supersede", incoming_attribute=attribute, target_attribute_id=int(target_id), target_value_text=candidate.value_text if candidate else "", confidence=confidence, reason=reason, kind="temporal")
            if outcome == "archive_incoming":
                return AttributeDecision(input_index=input_index, action="archive", incoming_attribute=attribute, target_attribute_id=int(target_id), target_value_text=candidate.value_text if candidate else "", confidence=confidence, reason=reason, kind="temporal")
            return self._queue(input_index, attribute, target_id, candidate, confidence, reason, kind="temporal", suggestion=str(raw.get("suggestion") or ""))
        if kind == "contextual":
            incoming_source, target = source_context or (None, None)
            outcome, incoming_qualifier, target_qualifier = contextual_outcome(target, confidence, str(raw.get("qualifier_incoming") or ""), str(raw.get("qualifier_target") or ""), incoming_source) if target else ("review", "", "")
            if outcome == "qualify":
                return AttributeDecision(input_index=input_index, action="qualify", incoming_attribute=attribute, target_attribute_id=int(target_id), target_value_text=candidate.value_text if candidate else "", confidence=confidence, reason=reason, kind="contextual", qualifier_incoming=incoming_qualifier, qualifier_target=target_qualifier)
            return self._queue(input_index, attribute, target_id, candidate, confidence, reason, kind="contextual", suggestion=str(raw.get("suggestion") or ""))
        return self._queue(input_index, attribute, target_id, candidate, confidence, reason, kind="factual" if kind == "factual" else "review", suggestion=str(raw.get("suggestion") or ""))

    @staticmethod
    def _queue(input_index: int, attribute: EntityAttributeInput, target_id: int | None = None, candidate: Any | None = None, confidence: float = 0.0, reason: str = "requires manual review", *, kind: str = "review", suggestion: str = "") -> AttributeDecision:
        return AttributeDecision(input_index=input_index, action="queue", incoming_attribute=attribute, target_attribute_id=int(target_id) if isinstance(target_id, int) else None, target_value_text=str(getattr(candidate, "value_text", "") or ""), confidence=confidence or attribute.confidence, reason=reason, kind=kind, suggestion=suggestion)


def clamp_confidence(value: Any, default: float) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return max(0.0, min(1.0, float(default)))


def build_attribute_decision_payload(incoming_attribute: EntityAttributeInput, retrieval_result: AttributeRetrievalResult, *, history_summaries: dict[int, dict[str, Any]] | None = None) -> dict[str, Any]:
    history_summaries = history_summaries if history_summaries is not None else retrieval_result.history_summaries
    candidates = [
        {
            "attribute_id": candidate.attribute_id,
            "attr_type": candidate.attr_type,
            "value_text": candidate.value_text,
            "confidence": candidate.confidence,
            "retrieval": {"rank": candidate.rank, "source": candidate.source, "es_score": candidate.es_score, "vector_score": candidate.vector_score, "fused_score": candidate.fused_score},
            "history_summary": strip_evidence(history_summaries.get(candidate.attribute_id, {})),
        }
        for candidate in retrieval_result.candidates[:MAX_ATTRIBUTE_DECISION_CANDIDATES]
    ]
    return {
        "incoming": {"attr_type": incoming_attribute.attr_type, "value_text": incoming_attribute.value_text, "note_id": incoming_attribute.note_id, "block_id": incoming_attribute.block_id, "block_index": incoming_attribute.block_index},
        "slot": {"name": incoming_attribute.attr_type, "description": slot_spec(incoming_attribute.attr_type).hint},
        "retrieval": {"mode": retrieval_result.mode, "group_size": retrieval_result.group_size},
        "candidates": candidates,
        "allowed_actions": ["add", "merge", "enrich", "update", "conflict", "review"],
    }


def strip_evidence(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: strip_evidence(item) for key, item in value.items() if "evidence" not in str(key).lower()}
    if isinstance(value, list):
        return [strip_evidence(item) for item in value]
    return value
