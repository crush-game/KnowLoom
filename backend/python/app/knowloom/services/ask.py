from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from time import perf_counter
from typing import Any

from app.knowloom.entity_store.models import EntityScope
from app.knowloom.entity_store.repository import MySQLEntityRepository
from app.knowloom.llm import KnowLoomLLMClient
from app.knowloom.services.query import KnowLoomQueryService

PERSONAL_PATTERNS = ("我能", "我是否", "我可不可以", "我可以", "我符合")
ASK_ANSWER_SYSTEM_PROMPT = """你是学校制度助手。只依据提供的材料回答；每个事实句末必须引用一个或多个 [n]。不要判断用户个人是否符合资格。材料不足时明确回答材料不足。只输出 JSON：{"answer":"..."}。"""

@dataclass(slots=True)
class AskResult:
    question: str
    answer: str
    insufficient: bool
    personal_case: bool
    citations: list[dict[str, Any]]
    entities: list[dict[str, Any]]
    warnings: list[str]
    timings: dict[str, float]

class KnowLoomAskService:
    def __init__(self, query_service: KnowLoomQueryService | None = None, repository: Any | None = None, llm_client: Any | None = None, *, scope: EntityScope | None = None) -> None:
        self.scope = scope or EntityScope()
        self.query_service = query_service or KnowLoomQueryService(scope=self.scope)
        self.repository = repository or MySQLEntityRepository()
        self.llm_client = llm_client or KnowLoomLLMClient()

    async def ask(self, question: str, *, top_k_entities: int = 3, top_k_blocks: int = 8, include_history: bool = False) -> AskResult:
        started = perf_counter()
        query = normalize_question(question)
        result = await self.query_service.query(query, top_k=top_k_entities)
        citations, fallback_lines = build_materials(result.retrieved_entities)
        search_blocks = getattr(self.repository, "search_blocks", None)
        block_rows = await asyncio.to_thread(search_blocks, self.scope, query, limit=top_k_blocks) if search_blocks is not None else []
        for block in block_rows:
            number = len(citations) + 1
            quote = str(block.get("l1_text") or "")[:400]
            citations.append({"n": number, "kind": "block", "attribute_id": None, "block_ref_id": block.get("block_ref_id"), "document_title": block.get("document_title") or "", "document_version": block.get("document_version") or 0, "doc_number": block.get("doc_number") or "", "doc_kind": block.get("doc_kind") or "", "issuer": block.get("issuer") or "", "effective_at": str(block.get("effective_at") or ""), "quote": quote})
            fallback_lines.append(f"- {quote} [{number}]")
        personal_case = any(pattern in question for pattern in PERSONAL_PATTERNS)
        insufficient = not citations
        answer = "现有材料不足以回答这个问题；请补充相关制度文件或换一个更具体的事项。" if insufficient else await self._generate_answer(question, citations, fallback_lines)
        if personal_case:
            answer = "我可以说明制度材料，但不能据此判断你个人是否符合资格。\n" + answer
        return AskResult(question=question, answer=answer, insufficient=insufficient, personal_case=personal_case, citations=citations, entities=[{"id": entity.id, "name": entity.canonical_name} for entity in result.retrieved_entities], warnings=result.warnings, timings={"total_ms": round((perf_counter() - started) * 1000, 2)})

    async def _generate_answer(self, question: str, citations: list[dict[str, Any]], fallback_lines: list[str]) -> str:
        try:
            response = await self.llm_client.chat_json(system_prompt=ASK_ANSWER_SYSTEM_PROMPT, user_payload={"question": question, "materials": citations}, operation_name="KnowLoom cited answer")
            answer = str(response.get("answer") or "").strip()
            if answer and citations_are_valid(answer, citations):
                return answer
        except Exception:
            pass
        return "\n".join(fallback_lines)

def build_materials(entities: list[Any]) -> tuple[list[dict[str, Any]], list[str]]:
    citations: list[dict[str, Any]] = []
    lines: list[str] = []
    for entity in entities:
        for attribute in entity.attributes:
            if not attribute.evidence:
                continue
            evidence = attribute.evidence[0]
            number = len(citations) + 1
            citations.append({"n": number, "kind": "attribute", "attribute_id": attribute.id, "block_ref_id": evidence.block_ref_id, "document_title": evidence.document_title, "document_version": evidence.document_version, "doc_number": evidence.doc_number, "doc_kind": evidence.doc_kind, "issuer": evidence.issuer, "effective_at": evidence.effective_at, "quote": evidence.evidence_text})
            lines.append(f"- {attribute.value_text} [{number}]")
    return citations, lines

def citations_are_valid(answer: str, citations: list[dict[str, Any]]) -> bool:
    numbers = {int(value) for value in re.findall(r"\[(\d+)\]", answer)}
    available = {int(item["n"]) for item in citations}
    return bool(numbers) and numbers <= available

def normalize_question(question: str) -> str:
    value = re.sub(r"[？?。！!]+$", "", question.strip())
    for prefix in ("请问", "请", "我想问", "我想了解"):
        if value.startswith(prefix):
            value = value[len(prefix):].strip()
    return value
