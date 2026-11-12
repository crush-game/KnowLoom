import asyncio
from app.knowloom.config import KnowLoomSettings
from app.knowloom.services.block_splitter import BlockSplitter, UnitGroup, validate_groups
from app.knowloom.services.markdown_units import build_windows, parse_units

class Groups:
    async def chat_json(self, **kwargs):
        units=kwargs["user_payload"]["units"]
        return {"groups":[{"start":units[0]["id"],"end":units[-1]["id"],"anchor_entity":"学位申请","candidate_entities":[],"split_reason":"heading","anchor_confidence":.9}]}

def test_window_grouping_materializes_exact_source():
    text="第一章 总则\n第十二条 申请学位。\n第十三条 提交材料。\n"
    blocks=asyncio.run(BlockSplitter(Groups(), KnowLoomSettings(_env_file=None)).split(text))
    assert "".join(block.l1_text for block in blocks) == text
    assert blocks[0].anchor_entity == "学位申请"

def test_validate_groups_fills_gaps_and_rejects_overlap():
    units=parse_units("# 标题\n正文\n")
    assert validate_groups([], units)
    assert validate_groups([UnitGroup(units[0].unit_id, units[-1].unit_id), UnitGroup(units[0].unit_id, units[-1].unit_id)], units) is None

def test_build_windows_preserves_unit_order():
    units=parse_units("\n".join(f"第{i}条 内容" for i in range(1,20)), max_unit_chars=20)
    windows=build_windows(units, max_window_chars=80)
    assert [unit.unit_id for window in windows for unit in window] == [unit.unit_id for unit in units]
