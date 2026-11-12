from __future__ import annotations

import json
from typing import Any

from app.knowloom.entity_store.models import AttributeDecision, EntityAttributeInput
from app.knowloom.entity_store.repository_mappers import attribute_snapshot


def compact(value: str) -> str:
    return "".join(str(value or "").split())


class AttributeSweeper:
    def __init__(self, repository: Any) -> None:
        self.repository = repository

    def sweep_completed_job(self, job_id: int) -> list[int]:
        swept: list[int] = []
        if not hasattr(self.repository, "connect"):
            return swept
        with self.repository.connect() as connection:
            try:
                with connection.cursor() as cursor:
                    cursor.execute("UPDATE knowloom_ingest_jobs SET swept_at=CURRENT_TIMESTAMP WHERE id=%s AND status='completed' AND swept_at IS NULL", (int(job_id),))
                    if getattr(cursor, "rowcount", 0) != 1:
                        connection.rollback()
                        return swept
                    cursor.execute("""SELECT d.id, d.scope_hash, d.doc_key, d.version_no, d.content_text FROM knowloom_ingest_jobs j JOIN knowloom_documents d ON d.id=j.document_id WHERE j.id=%s FOR UPDATE""", (int(job_id),))
                    current = cursor.fetchone()
                    if not current or int(current.get("version_no") or 1) <= 1:
                        connection.commit()
                        return swept
                    cursor.execute("SELECT id FROM knowloom_documents WHERE scope_hash=%s AND doc_key=%s AND version_no<%s AND status IN ('superseded','repealed')", (current["scope_hash"], current["doc_key"], current["version_no"]))
                    old_document_ids = [int(row["id"]) for row in cursor.fetchall()]
                    if not old_document_ids:
                        connection.commit()
                        return swept
                    placeholders = ", ".join(["%s"] * len(old_document_ids))
                    cursor.execute(f"""SELECT DISTINCT a.id, a.entity_id, a.attr_type, a.value_text, a.confidence, a.manually_confirmed
                        FROM knowloom_entity_attributes a JOIN knowloom_entity_attribute_evidence e ON e.attribute_id=a.id
                        WHERE a.status='active' AND e.document_id IN ({placeholders})""", tuple(old_document_ids))
                    attributes = cursor.fetchall()
                    current_text = compact(str(current.get("content_text") or ""))
                    for attribute in attributes:
                        attribute_id = int(attribute["id"])
                        cursor.execute("""SELECT e.evidence_text, e.evidence_fingerprint, e.note_id, e.block_id, e.block_index, d.status AS document_status FROM knowloom_entity_attribute_evidence e LEFT JOIN knowloom_documents d ON d.id=e.document_id WHERE e.attribute_id=%s""", (attribute_id,))
                        sources = cursor.fetchall()
                        if any(str(row.get("document_status") or "") == "active" for row in sources):
                            continue
                        evidence_present = any(compact(str(row.get("evidence_text") or "")) in current_text for row in sources if compact(str(row.get("evidence_text") or "")))
                        if evidence_present:
                            for source in sources:
                                evidence_text = str(source.get("evidence_text") or "")
                                if evidence_text and compact(evidence_text) in current_text:
                                    cursor.execute("""INSERT INTO knowloom_entity_attribute_evidence (attribute_id, document_id, block_ref_id, note_id, block_id, block_index, evidence_text, evidence_fingerprint)
                                        VALUES (%s,%s,NULL,%s,%s,%s,%s,%s) ON DUPLICATE KEY UPDATE evidence_text=VALUES(evidence_text)""",
                                        (attribute_id, int(current["id"]), str(source.get("note_id") or ""), str(source.get("block_id") or ""), int(source.get("block_index") if source.get("block_index") is not None else -1), evidence_text, source.get("evidence_fingerprint")))
                            continue
                        if bool(attribute.get("manually_confirmed")):
                            self._queue_manual_review(cursor, attribute, "removed_in_new_version")
                            continue
                        cursor.execute("UPDATE knowloom_entity_attributes SET status='superseded', superseded_by=NULL, superseded_reason='removed_in_new_version' WHERE id=%s AND status='active' AND manually_confirmed=0", (attribute_id,))
                        if getattr(cursor, "rowcount", 0) != 1:
                            continue
                        incoming = EntityAttributeInput(attr_type=str(attribute["attr_type"]), value_text=str(attribute["value_text"]), evidence="", confidence=float(attribute.get("confidence") or 0.7))
                        decision = AttributeDecision(input_index=-1, action="archive", incoming_attribute=incoming, target_attribute_id=attribute_id, target_value_text=incoming.value_text, confidence=1.0, reason="removed in new document version", source="sweeper")
                        self.repository._insert_attribute_event(cursor, entity_id=int(attribute["entity_id"]), attribute_id=attribute_id, decision=decision, before_snapshot=attribute_snapshot(attribute_id, incoming.attr_type, incoming.value_text, incoming.confidence), after_snapshot=attribute_snapshot(attribute_id, incoming.attr_type, incoming.value_text, incoming.confidence), evidence_added=0)
                        swept.append(attribute_id)
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        return swept

    @staticmethod
    def _queue_manual_review(cursor: Any, attribute: dict[str, Any], reason: str) -> None:
        payload = {"attr_type": attribute["attr_type"], "value_text": attribute["value_text"], "evidence": "", "confidence": attribute.get("confidence") or 0.7}
        cursor.execute("""INSERT INTO knowloom_entity_attribute_conflicts (entity_id, attribute_id, attr_type, incoming_value_text, incoming_evidence, reason, confidence, kind, incoming_json, suggestion, status)
            VALUES (%s,%s,%s,%s,'',%s,1.0,'temporal',%s,'keep_existing','pending')""", (attribute["entity_id"], attribute["id"], attribute["attr_type"], attribute["value_text"], reason, json.dumps(payload, ensure_ascii=False)))
