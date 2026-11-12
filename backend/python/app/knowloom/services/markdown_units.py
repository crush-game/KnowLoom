from __future__ import annotations

from dataclasses import dataclass
import re


@dataclass(slots=True, frozen=True)
class TextUnit:
    unit_id: int
    kind: str
    heading_level: int
    heading_path: list[str]
    char_start: int
    char_end: int
    text: str


MARKDOWN_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
CHAPTER_HEADING = re.compile(r"^第[一二三四五六七八九十百零〇0-9]+[编章节]\s*.*$")
ARTICLE = re.compile(r"^第[一二三四五六七八九十百零〇0-9]+条(?:\s*.*)?$")
NOTICE_HEADING = re.compile(r"^[一二三四五六七八九十]+、\s*.+$")
LIST = re.compile(r"^\s*(?:[-*+]\s+|\d+[.)]\s+)")


def parse_units(content: str, *, max_unit_chars: int = 1800) -> list[TextUnit]:
    if not content:
        return []
    lines = content.splitlines(keepends=True)
    units: list[TextUnit] = []
    path: list[str] = []
    index = 0
    offset = 0
    while index < len(lines):
        start = offset
        line = lines[index]
        stripped = line.strip()
        if not stripped:
            offset += len(line); index += 1; continue
        match = MARKDOWN_HEADING.match(stripped)
        if match or CHAPTER_HEADING.match(stripped) or (NOTICE_HEADING.match(stripped) and not ARTICLE.match(stripped)):
            level = len(match.group(1)) if match else (2 if CHAPTER_HEADING.match(stripped) else 3)
            title = match.group(2).strip() if match else stripped
            path = path[: level - 1] + [title]
            units.append(TextUnit(len(units), "heading", level, list(path), start, start + len(line), line))
            offset += len(line); index += 1; continue
        if ARTICLE.match(stripped):
            parts = [line]; offset += len(line); index += 1
            while index < len(lines):
                nxt = lines[index]; nxts = nxt.strip()
                if ARTICLE.match(nxts) or MARKDOWN_HEADING.match(nxts) or CHAPTER_HEADING.match(nxts): break
                parts.append(nxt); offset += len(nxt); index += 1
            text = "".join(parts); article = stripped.split()[0]
            units.extend(_split_unit(len(units), "article", path + [article], start, text, max_unit_chars)); continue
        if stripped.startswith("```"):
            parts=[line]; offset += len(line); index += 1
            while index < len(lines):
                nxt=lines[index]; parts.append(nxt); offset += len(nxt); index += 1
                if nxt.strip().startswith("```"): break
            units.extend(_split_unit(len(units), "code", path, start, "".join(parts), max_unit_chars)); continue
        if stripped.startswith("|"):
            parts=[]
            while index < len(lines) and lines[index].strip().startswith("|"):
                parts.append(lines[index]); offset += len(lines[index]); index += 1
            units.extend(_split_unit(len(units), "table", path, start, "".join(parts), max_unit_chars)); continue
        if stripped.startswith(">"):
            parts=[]
            while index < len(lines) and lines[index].strip().startswith(">"):
                parts.append(lines[index]); offset += len(lines[index]); index += 1
            units.extend(_split_unit(len(units), "quote", path, start, "".join(parts), max_unit_chars)); continue
        if LIST.match(line):
            parts=[]
            while index < len(lines) and (LIST.match(lines[index]) or lines[index].startswith((" ", "\t"))):
                parts.append(lines[index]); offset += len(lines[index]); index += 1
            units.extend(_split_unit(len(units), "list", path, start, "".join(parts), max_unit_chars)); continue
        parts=[]
        while index < len(lines) and lines[index].strip():
            if ARTICLE.match(lines[index].strip()) or MARKDOWN_HEADING.match(lines[index].strip()) or CHAPTER_HEADING.match(lines[index].strip()): break
            parts.append(lines[index]); offset += len(lines[index]); index += 1
        if not parts:
            parts=[line]; offset += len(line); index += 1
        units.extend(_split_unit(len(units), "paragraph", path, start, "".join(parts), max_unit_chars))
    return units


def _split_unit(unit_id: int, kind: str, path: list[str], start: int, text: str, limit: int) -> list[TextUnit]:
    if limit <= 0 or len(text) <= limit:
        return [TextUnit(unit_id, kind, 0, list(path), start, start + len(text), text)]
    result=[]; cursor=0
    while cursor < len(text):
        end=min(cursor+limit, len(text)); end=find_natural_split(text, cursor, end) if end < len(text) else end
        result.append(TextUnit(unit_id+len(result), kind, 0, list(path), start+cursor, start+end, text[cursor:end])); cursor=end
    return result


def find_natural_split(text: str, start: int, hard_end: int) -> int:
    min_end = start + max(1, int((hard_end - start) * 0.6))
    for separator in ("\n\n", "\n", "。", "；", ";", "，", ",", " "):
        position = text.rfind(separator, start, hard_end)
        if position >= min_end:
            return position + len(separator)
    return hard_end
