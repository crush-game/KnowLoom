from __future__ import annotations

from typing import Any

from app.knowloom.constants import RELATIONS
from app.knowloom.entity_store.alias_cache import scope_hash
from app.knowloom.entity_store.models import EntityRelationInput, EntityScope, StoredEntity
from app.knowloom.entity_store.normalizer import normalize_name, text_fingerprint


class EntityRelationStore:
    def __init__(self, repository: Any) -> None:
        self.repository = repository

    def upsert_relations(self, source_entity_id: int, scope: EntityScope, relations: list[EntityRelationInput]) -> list[int]:
        if not relations or not hasattr(self.repository, "connect"):
            return []
        prepared = [(relation, self.repository.find_by_alias(relation.target_name, scope)) for relation in relations if relation.relation_type in RELATIONS]
        relation_ids: list[int] = []
        with self.repository.connect() as connection:
            with connection.cursor() as cursor:
                for relation, target in prepared:
                    target_id = target.id if target is not None and target.id != source_entity_id else None
                    normalized = normalize_name(relation.target_name)
                    if not normalized:
                        continue
                    cursor.execute("""INSERT INTO knowloom_entity_relations (scope_hash, source_entity_id, target_name, target_normalized_name, target_entity_id, relation_type, confidence)
                        VALUES (%s,%s,%s,%s,%s,%s,%s) ON DUPLICATE KEY UPDATE id=LAST_INSERT_ID(id), target_entity_id=COALESCE(target_entity_id, VALUES(target_entity_id)), confidence=GREATEST(confidence, VALUES(confidence)), status='active'""",
                        (scope_hash(scope), int(source_entity_id), relation.target_name[:255], normalized[:255], target_id, relation.relation_type, relation.confidence))
                    relation_id = int(cursor.lastrowid)
                    relation_ids.append(relation_id)
                    cursor.execute("""INSERT INTO knowloom_entity_relation_evidence (relation_id, document_id, block_ref_id, evidence_text, evidence_fingerprint)
                        VALUES (%s,%s,%s,%s,%s) ON DUPLICATE KEY UPDATE block_ref_id=VALUES(block_ref_id)""",
                        (relation_id, relation.document_id, relation.block_ref_id, relation.evidence, text_fingerprint(relation.evidence)))
            connection.commit()
        return relation_ids

    def resolve_pending_for_entity(self, entity: StoredEntity) -> int:
        if not hasattr(self.repository, "connect"):
            return 0
        names = sorted({normalize_name(entity.canonical_name), *(normalize_name(alias) for alias in entity.aliases)} - {""})
        if not names:
            return 0
        placeholders = ", ".join(["%s"] * len(names))
        with self.repository.connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(f"UPDATE knowloom_entity_relations SET target_entity_id=%s WHERE scope_hash=%s AND target_entity_id IS NULL AND target_normalized_name IN ({placeholders})", (entity.id, scope_hash(entity.scope), *names))
                changed = int(getattr(cursor, "rowcount", 0))
            connection.commit()
        return changed
