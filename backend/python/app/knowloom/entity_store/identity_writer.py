from __future__ import annotations

from dataclasses import dataclass

from app.knowloom.entity_store.models import EntityAttributeInput

CORE_IDENTITY_SLOTS = frozenset({"definition", "purpose"})


@dataclass(frozen=True)
class IdentityDraft:
    text: str
    source: str
    user_text: str = ""
    trigger_reason: str = ""


def should_rewrite_identity(current_source: str, attributes: list[EntityAttributeInput]) -> bool:
    return current_source != "user" and any(attribute.attr_type in CORE_IDENTITY_SLOTS for attribute in attributes)


def build_derived_identity(entity_name: str, attributes: list[EntityAttributeInput]) -> IdentityDraft | None:
    core = [attribute.value_text.strip() for attribute in attributes if attribute.attr_type in CORE_IDENTITY_SLOTS and attribute.value_text.strip()]
    if not core:
        return None
    return IdentityDraft(text="；".join(dict.fromkeys(core))[:1000], source="derived", trigger_reason="core_slot_changed")


def build_user_identity(user_text: str) -> IdentityDraft:
    return IdentityDraft(text=user_text.strip()[:1000], source="user", user_text=user_text.strip()[:1000], trigger_reason="user_edit")
