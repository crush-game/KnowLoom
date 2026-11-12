from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class SlotSpec:
    key: str
    title: str
    hint: str
    merge_policy: Literal["fact", "append"]
    graph: Literal["semantic", "conditional", "none"]


SLOT_SPECS = (
    SlotSpec("definition", "定义", "它是什么", "fact", "semantic"),
    SlotSpec("purpose", "目的", "为什么设立、要解决什么问题", "fact", "semantic"),
    SlotSpec("applicable_to", "适用对象", "对哪些人或情形适用，例如年级、学生类别、学院", "fact", "conditional"),
    SlotSpec("conditions", "条件与标准", "需要满足的条件、标准、数量要求；每个条件单独一条", "fact", "conditional"),
    SlotSpec("exceptions", "例外与特殊情况", "不适用、从宽、从严的特殊情形", "append", "conditional"),
    SlotSpec("version_changes", "修订与废止说明", "修订或废止涉及的内容", "append", "none"),
    SlotSpec("related", "相关事项", "相关但独立的其他事项", "append", "semantic"),
    SlotSpec("notes", "其他", "以上都放不下的一句话短事实", "append", "none"),
    SlotSpec("procedure", "办理流程", "申请、审核、审批的步骤", "fact", "semantic"),
    SlotSpec("deadline", "时限与时间节点", "截止时间、办理时限、有效期", "fact", "none"),
    SlotSpec("materials", "所需材料", "要提交的表格、证明或材料", "append", "none"),
    SlotSpec("authority", "受理与审批部门", "向谁申请、由谁审核或决定", "fact", "semantic"),
    SlotSpec("amount", "金额、比例与名额", "奖助金额、评定比例或名额分配", "fact", "none"),
    SlotSpec("consequences", "后果与处理", "违反后的处分或预警后的处理", "fact", "conditional"),
    SlotSpec("appeal", "申诉与救济", "对结果不服时的申诉方式与期限", "fact", "none"),
    SlotSpec("duties", "职责", "机构或岗位负责的事项", "append", "none"),
    SlotSpec("composition", "组成", "机构由哪些成员组成或如何产生", "fact", "none"),
)
SLOTS = {spec.key: spec for spec in SLOT_SPECS}
ATTRIBUTE_TYPES = tuple(SLOTS)
FALLBACK_SLOT = "notes"
DEFAULT_ENTITY_TYPE = "procedure"

COMMON_SLOTS = ("definition", "purpose", "applicable_to", "conditions", "exceptions", "version_changes", "related", "notes")
HANDLING_SLOTS = ("procedure", "deadline", "materials", "authority")
TYPE_SLOTS = {
    "procedure": (*COMMON_SLOTS, *HANDLING_SLOTS),
    "benefit": (*COMMON_SLOTS, *HANDLING_SLOTS, "amount"),
    "sanction": (*COMMON_SLOTS, "consequences", "procedure", "appeal"),
    "requirement": (*COMMON_SLOTS, "deadline"),
    "organization": ("definition", "duties", "composition", "related", "notes"),
    "term": ("definition", "applicable_to", "related", "notes"),
}
ENTITY_TYPES = tuple(TYPE_SLOTS)


def slots_for(entity_type: str) -> tuple[str, ...]:
    return tuple(TYPE_SLOTS.get(str(entity_type or "").strip(), TYPE_SLOTS[DEFAULT_ENTITY_TYPE]))


def slot_spec(key: str) -> SlotSpec:
    return SLOTS.get(str(key or "").strip(), SLOTS[FALLBACK_SLOT])


def attribute_schema_payload() -> dict[str, object]:
    return {
        "default_entity_type": DEFAULT_ENTITY_TYPE,
        "fallback_slot": FALLBACK_SLOT,
        "slots": [
            {
                "key": spec.key,
                "title": spec.title,
                "hint": spec.hint,
                "merge_policy": spec.merge_policy,
                "graph": spec.graph,
            }
            for spec in SLOT_SPECS
        ],
        "entity_types": {entity_type: list(slots_for(entity_type)) for entity_type in ENTITY_TYPES},
    }

ISSUER_LEVEL = {"national": 3, "university": 2, "department": 1}
AUTO_TEMPORAL_MIN_CONFIDENCE = 0.8
AUTO_CONTEXTUAL_MIN_CONFIDENCE = 0.7
