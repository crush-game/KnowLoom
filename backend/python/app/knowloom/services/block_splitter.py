import asyncio
from dataclasses import dataclass
from time import perf_counter
from typing import Any

from app.knowloom.config import KnowLoomSettings, settings
from app.knowloom.llm import KnowLoomLLMClient
from app.knowloom.models import BlockSplitResult, TextBlock
from app.knowloom.prompts import BLOCK_SPLIT_SYSTEM_PROMPT
from app.knowloom.services.markdown_units import TextUnit, build_windows, parse_units


UNIT_GROUP_SYSTEM_PROMPT = """你是学校规章制度的单元分组器。输入已经由代码切成不可修改的单元。只输出连续单元编号范围，不复制或改写原文。连续几条讲同一事项时合并；标题、定义句优先作为 anchor_entity；列表和步骤不要单独成组。只输出 JSON：{"groups":[{"start":1,"end":3,"anchor_entity":"事项","candidate_entities":[],"split_reason":"heading","anchor_confidence":0.9}]}。"""

@dataclass(slots=True)
class UnitGroup:
    start: int
    end: int
    anchor_entity: str = ""
    candidate_entities: list[str] | None = None
    split_reason: str = "entity_anchor"
    anchor_confidence: float = 0.0

class BlockSplitter:
    def __init__(self, llm_client: KnowLoomLLMClient, config: KnowLoomSettings = settings) -> None:
        self.llm = llm_client
        self.config = config

    async def split(self, text: str) -> list[TextBlock]:
        blocks, _ = await self.split_with_timings(text)
        return blocks

    async def split_with_timings(self, text: str) -> tuple[list[TextBlock], dict[str, float]]:
        started = perf_counter()
        units = parse_units(text, max_unit_chars=self.config.max_block_chars)
        windows = build_windows(units)
        semaphore = asyncio.Semaphore(max(1, int(self.config.max_concurrency)))

        async def group_one(window: list[TextUnit]) -> list[UnitGroup]:
            async with semaphore:
                return await self._group_window(window)

        grouped_windows = await asyncio.gather(*(group_one(window) for window in windows)) if windows else []
        groups: list[UnitGroup] = []
        inherited_anchor = ""
        for window_groups in grouped_windows:
            for group in window_groups:
                if not group.anchor_entity:
                    group.anchor_entity = inherited_anchor
                    if group.split_reason == "entity_anchor":
                        group.split_reason = "inherited_anchor"
                if group.anchor_entity:
                    inherited_anchor = group.anchor_entity
                groups.append(group)
        blocks = materialize_groups(text, units, groups)
        if not blocks and text:
            blocks = [fallback_source_block(text, [])]
        return blocks, {"unit_parse_and_group_ms": elapsed_ms(started)}

    async def _group_window(self, window: list[TextUnit]) -> list[UnitGroup]:
        if not window:
            return []
        try:
            data = await self.llm.chat_json(
                system_prompt=UNIT_GROUP_SYSTEM_PROMPT,
                user_payload={"heading_path": window[0].heading_path, "units": [{"id": unit.unit_id, "kind": unit.kind, "text": unit.text} for unit in window]},
                operation_name=f"KnowLoom unit grouping {window[0].unit_id}-{window[-1].unit_id}",
            )
            raw_groups = data.get("groups") if isinstance(data, dict) else None
            groups = [unit_group_from_dict(item) for item in raw_groups] if isinstance(raw_groups, list) else []
            validated = validate_groups(groups, window)
            if validated is not None:
                return validated
        except Exception:
            pass
        return fallback_groups(window)


def unit_group_from_dict(item: Any) -> UnitGroup:
    if not isinstance(item, dict):
        raise ValueError("unit group must be an object")
    return UnitGroup(start=int(item["start"]), end=int(item["end"]), anchor_entity=str(item.get("anchor_entity") or "").strip(), candidate_entities=[str(value) for value in item.get("candidate_entities", [])], split_reason=str(item.get("split_reason") or "entity_anchor"), anchor_confidence=max(0.0, min(1.0, float(item.get("anchor_confidence") or 0.0))))


def validate_groups(groups: list[UnitGroup], window: list[TextUnit]) -> list[UnitGroup] | None:
    if not window:
        return []
    first, last = window[0].unit_id, window[-1].unit_id
    result: list[UnitGroup] = []
    expected = first
    for group in sorted(groups, key=lambda item: item.start):
        if group.start < expected or group.end < group.start or group.end > last:
            return None
        if group.start > expected:
            result.extend(fill_gap(window, expected, group.start - 1))
        result.append(group)
        expected = group.end + 1
    if expected <= last:
        result.extend(fill_gap(window, expected, last))
    return result


def fill_gap(window: list[TextUnit], start: int, end: int) -> list[UnitGroup]:
    selected = [unit for unit in window if start <= unit.unit_id <= end]
    if not selected:
        return []
    groups: list[UnitGroup] = []
    group_start = selected[0].unit_id
    anchor = ""
    for index, unit in enumerate(selected):
        if unit.kind == "heading" and index > 0:
            groups.append(UnitGroup(group_start, selected[index - 1].unit_id, anchor_entity=anchor, split_reason="heading_fallback" if anchor else "inherited_anchor", anchor_confidence=0.3 if anchor else 0.0))
            group_start = unit.unit_id
        if unit.kind == "heading":
            anchor = unit.text.strip().lstrip("#").strip()
    groups.append(UnitGroup(group_start, selected[-1].unit_id, anchor_entity=anchor, split_reason="heading_fallback" if anchor else "inherited_anchor", anchor_confidence=0.3 if anchor else 0.0))
    return groups


def fallback_groups(window: list[TextUnit]) -> list[UnitGroup]:
    return fill_gap(window, window[0].unit_id, window[-1].unit_id) if window else []


def materialize_groups(content: str, units: list[TextUnit], groups: list[UnitGroup]) -> list[TextBlock]:
    by_id = {unit.unit_id: unit for unit in units}
    blocks: list[TextBlock] = []
    for group in groups:
        first, last = by_id.get(group.start), by_id.get(group.end)
        if first is None or last is None:
            continue
        blocks.append(TextBlock(block_index=len(blocks), heading=" / ".join(last.heading_path or first.heading_path), anchor_entity=group.anchor_entity, candidate_entities=group.candidate_entities or [], l1_text=content[first.char_start:last.char_end], split_reason=group.split_reason, anchor_confidence=group.anchor_confidence, parent_block_index=None, chunk_index=0, chunk_count=1, char_start=first.char_start, char_end=last.char_end))
    return blocks


def normalize_blocks(
    blocks: list[TextBlock],
    *,
    max_blocks: int,
    max_block_chars: int,
    source_text: str = "",
) -> list[TextBlock]:
    normalized: list[TextBlock] = []
    selected_blocks = blocks[: max(1, max_blocks)]
    if not source_coverage_is_valid(selected_blocks, source_text):
        selected_blocks = [fallback_source_block(source_text, selected_blocks)]
    for index, block in enumerate(selected_blocks):
        l1_text = block.l1_text.strip()
        if not l1_text:
            continue
        chunks = split_text_by_max_chars(l1_text, max_block_chars=max_block_chars)
        parent_output_index = len(normalized)
        chunk_count = len(chunks)
        for chunk_index, chunk in enumerate(chunks):
            if not chunk:
                continue
            heading = block.heading or block.anchor_entity or f"Block {index + 1}"
            if chunk_count > 1:
                heading = f"{heading} - chunk {chunk_index + 1}"
            char_start, char_end = chunk_char_range(block, l1_text, chunk, chunk_index, max_block_chars)
            normalized.append(
                TextBlock(
                    block_index=len(normalized),
                    heading=heading,
                    anchor_entity=block.anchor_entity,
                    candidate_entities=block.candidate_entities,
                    l1_text=chunk,
                    split_reason="max_chars_chunk" if chunk_count > 1 else block.split_reason or "entity_anchor",
                    anchor_confidence=block.anchor_confidence,
                    parent_block_index=parent_output_index if chunk_count > 1 else block.parent_block_index,
                    chunk_index=chunk_index,
                    chunk_count=chunk_count,
                    char_start=char_start,
                    char_end=char_end,
                )
            )
    return normalized


def validate_source_coverage(blocks: list[TextBlock], source_text: str) -> None:
    if source_coverage_is_valid(blocks, source_text):
        return

    raise ValueError("block split l1_text does not cover original text")


def source_coverage_is_valid(blocks: list[TextBlock], source_text: str) -> bool:
    expected = coverage_text(source_text)
    if not expected:
        return True

    actual = "".join(coverage_text(block.l1_text) for block in blocks)
    return expected in actual


def fallback_source_block(source_text: str, blocks: list[TextBlock]) -> TextBlock:
    first_block = blocks[0] if blocks else None
    return TextBlock(
        block_index=0,
        heading=(first_block.heading if first_block else "") or (first_block.anchor_entity if first_block else "") or "Original input",
        anchor_entity=(first_block.anchor_entity if first_block else ""),
        candidate_entities=(first_block.candidate_entities if first_block else []),
        l1_text=source_text,
        split_reason="fallback",
        anchor_confidence=0.0,
        parent_block_index=None,
        chunk_index=0,
        chunk_count=1,
        char_start=0,
        char_end=len(source_text),
    )


def coverage_text(value: str) -> str:
    return "".join(str(value or "").split())


def split_text_by_max_chars(text: str, *, max_block_chars: int) -> list[str]:
    clean = text.strip()
    if max_block_chars <= 0 or len(clean) <= max_block_chars:
        return [clean]

    chunks: list[str] = []
    cursor = 0
    while cursor < len(clean):
        end = min(cursor + max_block_chars, len(clean))
        if end < len(clean):
            natural_end = find_natural_split(clean, cursor, end)
            if natural_end > cursor:
                end = natural_end
        chunk = clean[cursor:end].strip()
        if chunk:
            chunks.append(chunk)
        cursor = end
        while cursor < len(clean) and clean[cursor].isspace():
            cursor += 1
    return chunks or [clean[:max_block_chars].strip()]


def find_natural_split(text: str, start: int, hard_end: int) -> int:
    min_end = start + max(1, int((hard_end - start) * 0.6))
    for separator in ("\n\n", "\n", "。", "；", ";", "，", ",", " "):
        position = text.rfind(separator, start, hard_end)
        if position >= min_end:
            return position + len(separator)
    return hard_end


def chunk_char_range(block: TextBlock, full_text: str, chunk: str, chunk_index: int, max_block_chars: int) -> tuple[int, int]:
    if block.char_start < 0:
        return -1, -1

    if max_block_chars <= 0:
        return block.char_start, block.char_start + len(chunk)

    approximate_start = min(chunk_index * max_block_chars, len(full_text))
    found_at = full_text.find(chunk, max(0, approximate_start - max_block_chars))
    if found_at < 0:
        found_at = approximate_start
    char_start = block.char_start + found_at
    return char_start, char_start + len(chunk)


def elapsed_ms(started_at: float) -> float:
    return round((perf_counter() - started_at) * 1000, 2)
