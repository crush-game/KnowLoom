from datetime import date

from app.knowloom.entity_store.conflict_gate import AttributeWithSources, NoDocumentRelations, SourceInfo, contextual_outcome, temporal_outcome


def source(**overrides):
    values = {"doc_key": "rules", "version_no": 1, "effective_at": date(2024, 9, 1)}
    values.update(overrides)
    return SourceInfo(**values)


def test_newer_version_of_same_document_supersedes() -> None:
    outcome = temporal_outcome(source(version_no=2), AttributeWithSources(attribute_id=1, sources=(source(),)), 0.9, NoDocumentRelations())
    assert outcome == "supersede_target"


def test_older_document_is_archived() -> None:
    outcome = temporal_outcome(source(effective_at=date(2023, 9, 1)), AttributeWithSources(attribute_id=1, sources=(source(),)), 0.9, NoDocumentRelations())
    assert outcome == "archive_incoming"


def test_guide_never_automatically_supersedes_regulation() -> None:
    outcome = temporal_outcome(source(doc_kind="guide", effective_at=date(2025, 9, 1)), AttributeWithSources(attribute_id=1, sources=(source(),)), 0.9, NoDocumentRelations())
    assert outcome == "review"


def test_contextual_conflict_uses_audience_as_fallback_qualifiers() -> None:
    outcome, incoming_qualifier, target_qualifier = contextual_outcome(
        AttributeWithSources(attribute_id=1, sources=(source(audience="旧范围"),)),
        0.8,
        "",
        "",
        source(audience="新范围"),
    )
    assert outcome == "qualify"
    assert (incoming_qualifier, target_qualifier) == ("新范围", "旧范围")


def test_temporal_gate_never_replaces_a_manual_confirmation() -> None:
    outcome = temporal_outcome(
        source(version_no=2),
        AttributeWithSources(attribute_id=1, manually_confirmed=True, sources=(source(),)),
        0.95,
        NoDocumentRelations(),
    )
    assert outcome == "review"


def test_temporal_gate_rejects_a_lower_level_newer_document() -> None:
    outcome = temporal_outcome(
        source(doc_key="department-rules", issuer_level="department", effective_at=date(2025, 9, 1)),
        AttributeWithSources(attribute_id=1, sources=(source(doc_key="university-rules", issuer_level="university"),)),
        0.95,
        NoDocumentRelations(),
    )
    assert outcome == "review"
