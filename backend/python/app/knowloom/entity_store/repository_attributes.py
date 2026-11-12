import json
from typing import Any

from app.knowloom.entity_store.models import (
    AttributeDecision,
    AttributeDecisionApplyResult,
    EntityAttributeInput,
)
from app.knowloom.entity_store.normalizer import text_fingerprint
from app.knowloom.entity_store.repository_mappers import (
    attribute_event_diff,
    attribute_snapshot,
    event_summary,
    review_stats,
)


class AttributeDecisionRepositoryMixin:
    def apply_attribute_decisions(self, entity_id: int, decisions: list[AttributeDecision]) -> AttributeDecisionApplyResult:
        outcome = AttributeDecisionApplyResult()
        with self.connect() as connection:
            with connection.cursor() as cursor:
                for decision in decisions:
                    attribute = decision.incoming_attribute
                    changed_id: int | None = None
                    event_attribute_id: int | None = None
                    before_snapshot: dict[str, Any] | None = None
                    after_snapshot: dict[str, Any] | None = None
                    evidence_added = 0
                    if decision.action == "add":
                        changed_id, evidence_added = self._insert_attribute_from_input(cursor, entity_id, attribute)
                        event_attribute_id = changed_id
                        after_snapshot = attribute_snapshot(changed_id, attribute.attr_type, attribute.value_text, attribute.confidence)
                        outcome.attribute_count += 1
                        outcome.evidence_count += evidence_added
                    elif decision.action == "merge" and decision.target_attribute_id:
                        changed_id = int(decision.target_attribute_id)
                        event_attribute_id = changed_id
                        before_snapshot = attribute_snapshot(changed_id, attribute.attr_type, decision.target_value_text, attribute.confidence)
                        cursor.execute(
                            """
                            UPDATE knowloom_entity_attributes
                            SET confidence = GREATEST(confidence, %s),
                                updated_at = CURRENT_TIMESTAMP
                            WHERE id = %s AND entity_id = %s AND status = 'active'
                            """,
                            (attribute.confidence, changed_id, int(entity_id)),
                        )
                        evidence_added = self._insert_attribute_evidence(cursor, changed_id, attribute)
                        after_snapshot = attribute_snapshot(changed_id, attribute.attr_type, decision.target_value_text, attribute.confidence)
                        outcome.evidence_count += evidence_added
                    elif decision.action == "enrich" and decision.target_attribute_id:
                        changed_id = int(decision.target_attribute_id)
                        event_attribute_id = changed_id
                        new_value_text = decision.new_value_text or attribute.value_text
                        before_snapshot = attribute_snapshot(changed_id, attribute.attr_type, decision.target_value_text, attribute.confidence)
                        cursor.execute(
                            """
                            UPDATE knowloom_entity_attributes
                            SET value_text = %s,
                                value_fingerprint = %s,
                                confidence = GREATEST(confidence, %s),
                                updated_at = CURRENT_TIMESTAMP
                            WHERE id = %s AND entity_id = %s AND status = 'active'
                            """,
                            (new_value_text, text_fingerprint(new_value_text), attribute.confidence, changed_id, int(entity_id)),
                        )
                        outcome.attribute_count += 1
                        evidence_added = self._insert_attribute_evidence(cursor, changed_id, attribute)
                        after_snapshot = attribute_snapshot(changed_id, attribute.attr_type, new_value_text, attribute.confidence)
                        outcome.evidence_count += evidence_added
                    elif decision.action in {"supersede", "update"} and decision.target_attribute_id:
                        changed_id = int(decision.target_attribute_id)
                        before_snapshot = attribute_snapshot(changed_id, attribute.attr_type, decision.target_value_text, attribute.confidence)
                        new_id, evidence_added = self._insert_attribute_from_input(cursor, entity_id, attribute)
                        cursor.execute(
                            """
                            UPDATE knowloom_entity_attributes
                            SET status = 'superseded', superseded_by = %s, superseded_reason = 'replaced',
                                updated_at = CURRENT_TIMESTAMP
                            WHERE id = %s AND entity_id = %s AND status = 'active' AND manually_confirmed = 0
                            """,
                            (new_id, changed_id, int(entity_id)),
                        )
                        if getattr(cursor, "rowcount", 1) != 1:
                            raise RuntimeError(f"attribute state changed: {changed_id}")
                        event_attribute_id = new_id
                        after_snapshot = attribute_snapshot(new_id, attribute.attr_type, attribute.value_text, attribute.confidence)
                        outcome.attribute_count += 1
                        outcome.evidence_count += evidence_added
                        outcome.changed_attribute_ids.extend([new_id, changed_id])
                    elif decision.action == "archive" and decision.target_attribute_id:
                        changed_id = int(decision.target_attribute_id)
                        new_id, evidence_added = self._insert_attribute_from_input(
                            cursor, entity_id, attribute, status="superseded", superseded_by=changed_id, superseded_reason="archived"
                        )
                        event_attribute_id = new_id
                        before_snapshot = attribute_snapshot(changed_id, attribute.attr_type, decision.target_value_text, attribute.confidence)
                        after_snapshot = attribute_snapshot(new_id, attribute.attr_type, attribute.value_text, attribute.confidence)
                        outcome.attribute_count += 1
                        outcome.evidence_count += evidence_added
                        outcome.changed_attribute_ids.extend([new_id, changed_id])
                    elif decision.action == "qualify" and decision.target_attribute_id:
                        changed_id = int(decision.target_attribute_id)
                        new_id, evidence_added = self._insert_attribute_from_input(
                            cursor, entity_id, attribute, qualifier=decision.qualifier_incoming
                        )
                        cursor.execute(
                            "UPDATE knowloom_entity_attributes SET qualifier = %s WHERE id = %s AND entity_id = %s AND status = 'active' AND qualifier = ''",
                            (decision.qualifier_target, changed_id, int(entity_id)),
                        )
                        event_attribute_id = new_id
                        before_snapshot = attribute_snapshot(changed_id, attribute.attr_type, decision.target_value_text, attribute.confidence)
                        after_snapshot = attribute_snapshot(new_id, attribute.attr_type, attribute.value_text, attribute.confidence)
                        outcome.attribute_count += 1
                        outcome.evidence_count += evidence_added
                        outcome.changed_attribute_ids.extend([new_id, changed_id])
                    elif decision.action in {"queue", "conflict"} and decision.target_attribute_id:
                        event_attribute_id = int(decision.target_attribute_id)
                        before_snapshot = attribute_snapshot(event_attribute_id, attribute.attr_type, decision.target_value_text, attribute.confidence)
                        after_snapshot = before_snapshot
                        self._insert_attribute_conflict(cursor, entity_id, decision)
                        outcome.conflict_count += 1
                    self._insert_attribute_decision_audit(cursor, entity_id, decision, changed_id)
                    if event_attribute_id:
                        self._insert_attribute_event(
                            cursor,
                            entity_id=entity_id,
                            attribute_id=event_attribute_id,
                            decision=decision,
                            before_snapshot=before_snapshot,
                            after_snapshot=after_snapshot,
                            evidence_added=evidence_added,
                        )
                    if changed_id is not None and changed_id not in outcome.changed_attribute_ids:
                        outcome.changed_attribute_ids.append(changed_id)
            connection.commit()
        return outcome

    def attribute_event_summaries(self, attribute_ids: list[int], *, recent_limit: int = 3) -> dict[int, dict[str, Any]]:
        unique_ids = sorted({int(attribute_id) for attribute_id in attribute_ids if int(attribute_id) > 0})
        if not unique_ids:
            return {}
        placeholders = ", ".join(["%s"] * len(unique_ids))
        with self.connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT attribute_id, action, review_status, decision_reason,
                           confidence, source, corrected_by_event_id, created_at
                    FROM knowloom_entity_attribute_events
                    WHERE attribute_id IN ({placeholders})
                    ORDER BY attribute_id, id DESC
                    """,
                    tuple(unique_ids),
                )
                rows = cursor.fetchall()

        grouped: dict[int, list[dict[str, Any]]] = {attribute_id: [] for attribute_id in unique_ids}
        for row in rows:
            attribute_id = int(row["attribute_id"])
            grouped.setdefault(attribute_id, []).append(row)

        summaries: dict[int, dict[str, Any]] = {}
        for attribute_id, events in grouped.items():
            recent = events[: max(1, int(recent_limit))]
            corrected = [event for event in events if event.get("corrected_by_event_id")]
            summaries[attribute_id] = {
                "event_count": len(events),
                "last_actions": [str(event.get("action") or "") for event in recent],
                "review_stats": review_stats(events),
                "recent_corrections": [
                    {
                        "original_action": str(event.get("action") or ""),
                        "review_status": str(event.get("review_status") or ""),
                        "reason": str(event.get("decision_reason") or ""),
                    }
                    for event in corrected[: max(1, int(recent_limit))]
                ],
                "last_event": event_summary(recent[0]) if recent else None,
            }
        return summaries

    def _insert_attribute_from_input(
        self, cursor: Any, entity_id: int, attribute: EntityAttributeInput, *, status: str = "active", qualifier: str = "", superseded_by: int | None = None, superseded_reason: str = ""
    ) -> tuple[int, int]:
        value_fingerprint = text_fingerprint(attribute.value_text)
        cursor.execute(
            """
            INSERT INTO knowloom_entity_attributes (
                entity_id, attr_type, value_text, value_fingerprint, confidence, status, qualifier, superseded_by, superseded_reason
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                confidence = GREATEST(confidence, VALUES(confidence)),
                updated_at = CURRENT_TIMESTAMP
            """,
            (entity_id, attribute.attr_type, attribute.value_text, value_fingerprint, attribute.confidence, status, qualifier, superseded_by, superseded_reason),
        )
        cursor.execute(
            """
            SELECT id FROM knowloom_entity_attributes
            WHERE entity_id = %s AND attr_type = %s AND value_fingerprint = %s
            LIMIT 1
            """,
            (entity_id, attribute.attr_type, value_fingerprint),
        )
        row = cursor.fetchone()
        if not row:
            return 0, 0
        attribute_id = int(row["id"])
        return attribute_id, self._insert_attribute_evidence(cursor, attribute_id, attribute)

    def _insert_attribute_evidence(self, cursor: Any, attribute_id: int, attribute: EntityAttributeInput) -> int:
        evidence_text = attribute.evidence or attribute.value_text
        if not evidence_text:
            return 0
        cursor.execute(
            """
            INSERT INTO knowloom_entity_attribute_evidence (
                attribute_id, document_id, block_ref_id, note_id, block_id, block_index, evidence_text, evidence_fingerprint
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                evidence_text = VALUES(evidence_text)
            """,
            (
                int(attribute_id),
                attribute.document_id,
                attribute.block_ref_id,
                attribute.note_id,
                attribute.block_id,
                attribute.block_index,
                evidence_text,
                text_fingerprint(evidence_text),
            ),
        )
        return 1

    def _insert_attribute_conflict(self, cursor: Any, entity_id: int, decision: AttributeDecision) -> None:
        attribute = decision.incoming_attribute
        cursor.execute(
            """
            INSERT INTO knowloom_entity_attribute_conflicts (
                entity_id, attribute_id, attr_type, incoming_value_text,
                incoming_evidence, reason, confidence, kind, incoming_json, suggestion,
                qualifier_incoming, qualifier_target, status
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'pending')
            """,
            (
                int(entity_id),
                int(decision.target_attribute_id or 0),
                attribute.attr_type,
                attribute.value_text,
                attribute.evidence,
                decision.reason,
                decision.confidence,
                decision.kind,
                json.dumps({"attr_type": attribute.attr_type, "value_text": attribute.value_text, "evidence": attribute.evidence, "confidence": attribute.confidence, "document_id": attribute.document_id, "block_ref_id": attribute.block_ref_id}, ensure_ascii=False),
                decision.suggestion,
                decision.qualifier_incoming,
                decision.qualifier_target,
            ),
        )

    def _insert_attribute_decision_audit(
        self,
        cursor: Any,
        entity_id: int,
        decision: AttributeDecision,
        changed_attribute_id: int | None,
    ) -> None:
        attribute = decision.incoming_attribute
        cursor.execute(
            """
            INSERT INTO knowloom_entity_attribute_decision_audit (
                entity_id, input_index, action, attr_type, incoming_value_text,
                target_attribute_id, changed_attribute_id, new_value_text,
                confidence, reason
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                int(entity_id),
                int(decision.input_index),
                decision.action,
                attribute.attr_type,
                attribute.value_text,
                decision.target_attribute_id,
                changed_attribute_id,
                decision.new_value_text,
                decision.confidence,
                decision.reason,
            ),
        )

    def _insert_attribute_event(
        self,
        cursor: Any,
        *,
        entity_id: int,
        attribute_id: int,
        decision: AttributeDecision,
        before_snapshot: dict[str, Any] | None,
        after_snapshot: dict[str, Any] | None,
        evidence_added: int,
    ) -> None:
        attribute = decision.incoming_attribute
        incoming_snapshot = {
            "attr_type": attribute.attr_type,
            "value_text": attribute.value_text,
            "evidence": attribute.evidence,
            "confidence": attribute.confidence,
            "note_id": attribute.note_id,
            "block_id": attribute.block_id,
            "block_index": attribute.block_index,
            "document_id": attribute.document_id,
            "block_ref_id": attribute.block_ref_id,
        }
        candidate_snapshot = None
        if decision.target_attribute_id:
            candidate_snapshot = {
                "attribute_id": int(decision.target_attribute_id),
                "attr_type": attribute.attr_type,
                "value_text": decision.target_value_text,
            }
        diff = attribute_event_diff(
            action=decision.action,
            before_snapshot=before_snapshot,
            after_snapshot=after_snapshot,
            evidence_added=evidence_added,
            target_attribute_id=decision.target_attribute_id,
        )
        cursor.execute(
            """
            INSERT INTO knowloom_entity_attribute_events (
                entity_id, attribute_id, attr_type, action, review_status,
                before_json, after_json, incoming_json, candidate_json, diff_json,
                decision_reason, confidence, source,
                note_id, block_id, block_index
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                int(entity_id),
                int(attribute_id),
                attribute.attr_type,
                decision.action,
                "approved" if decision.source == "manual" else ("auto_applied" if decision.action in {"supersede", "archive", "qualify"} else "pending"),
                json.dumps(before_snapshot, ensure_ascii=False),
                json.dumps(after_snapshot, ensure_ascii=False),
                json.dumps(incoming_snapshot, ensure_ascii=False),
                json.dumps(candidate_snapshot, ensure_ascii=False),
                json.dumps(diff, ensure_ascii=False),
                decision.reason,
                decision.confidence,
                decision.source,
                attribute.note_id,
                attribute.block_id,
                attribute.block_index,
            ),
        )

    def _merge_attributes(self, cursor: Any, entity_id: int, attributes: list[EntityAttributeInput]) -> tuple[int, int]:
        attribute_count = 0
        evidence_count = 0
        for attribute in attributes:
            value_fingerprint = text_fingerprint(attribute.value_text)
            cursor.execute(
                """
                INSERT INTO knowloom_entity_attributes (
                    entity_id, attr_type, value_text, value_fingerprint, confidence
                )
                VALUES (%s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    confidence = GREATEST(confidence, VALUES(confidence)),
                    updated_at = CURRENT_TIMESTAMP
                """,
                (entity_id, attribute.attr_type, attribute.value_text, value_fingerprint, attribute.confidence),
            )
            attribute_count += 1
            cursor.execute(
                """
                SELECT id FROM knowloom_entity_attributes
                WHERE entity_id = %s AND attr_type = %s AND value_fingerprint = %s
                LIMIT 1
                """,
                (entity_id, attribute.attr_type, value_fingerprint),
            )
            row = cursor.fetchone()
            if not row:
                continue
            attribute_id = int(row["id"])
            if attribute.evidence:
                cursor.execute(
                    """
                    INSERT INTO knowloom_entity_attribute_evidence (
                        attribute_id, note_id, block_id, block_index, evidence_text, evidence_fingerprint
                    )
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        evidence_text = VALUES(evidence_text)
                    """,
                    (
                        attribute_id,
                        attribute.note_id,
                        attribute.block_id,
                        attribute.block_index,
                        attribute.evidence,
                        text_fingerprint(attribute.evidence),
                    ),
                )
                evidence_count += 1
            self._insert_attribute_event(
                cursor,
                entity_id=entity_id,
                attribute_id=attribute_id,
                decision=AttributeDecision(
                    input_index=-1,
                    action="add",
                    incoming_attribute=attribute,
                    target_attribute_id=None,
                    confidence=attribute.confidence,
                    reason="initial entity attribute add",
                ),
                before_snapshot=None,
                after_snapshot=attribute_snapshot(attribute_id, attribute.attr_type, attribute.value_text, attribute.confidence),
                evidence_added=1 if attribute.evidence else 0,
            )
        return attribute_count, evidence_count

    def list_attribute_conflicts(self, *, status: str = "pending", entity_id: int | None = None, limit: int = 50) -> list[dict[str, Any]]:
        clauses = ["status = %s"]
        values: list[Any] = [status]
        if entity_id is not None:
            clauses.append("entity_id = %s")
            values.append(int(entity_id))
        values.append(max(1, min(200, int(limit))))
        with self.connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT id, entity_id, attribute_id, attr_type, incoming_value_text, incoming_evidence,
                           reason, confidence, kind, suggestion, qualifier_incoming, qualifier_target,
                           status, resolution, resolved_by, resolved_at, created_at
                    FROM knowloom_entity_attribute_conflicts
                    WHERE {' AND '.join(clauses)}
                    ORDER BY id DESC LIMIT %s
                    """,
                    tuple(values),
                )
                return cursor.fetchall()

    def resolve_attribute_conflict(self, conflict_id: int, *, resolution: str, decided_by: str = "manual") -> bool:
        if resolution not in {"accept_incoming", "keep_existing", "keep_both", "dismiss"}:
            raise ValueError("unsupported conflict resolution")
        with self.connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT * FROM knowloom_entity_attribute_conflicts WHERE id=%s AND status='pending' FOR UPDATE", (int(conflict_id),))
                conflict = cursor.fetchone()
                if not conflict:
                    return False
                cursor.execute("""UPDATE knowloom_entity_attribute_conflicts SET status=CASE WHEN %s='dismiss' THEN 'dismissed' ELSE 'resolved' END,
                    resolution=%s, resolved_by=%s, resolved_at=CURRENT_TIMESTAMP WHERE id=%s AND status='pending'""", (resolution, resolution, decided_by[:128], int(conflict_id)))
                if getattr(cursor, "rowcount", 1) != 1:
                    return False
                target_id = int(conflict["attribute_id"])
                entity_id = int(conflict["entity_id"])
                payload = json.loads(conflict.get("incoming_json") or "{}")
                incoming = EntityAttributeInput(attr_type=str(payload.get("attr_type") or conflict.get("attr_type") or "notes"), value_text=str(payload.get("value_text") or conflict.get("incoming_value_text") or ""), evidence=str(payload.get("evidence") or conflict.get("incoming_evidence") or ""), confidence=float(payload.get("confidence") or conflict.get("confidence") or 0.7), document_id=int(payload["document_id"]) if payload.get("document_id") is not None else None, block_ref_id=int(payload["block_ref_id"]) if payload.get("block_ref_id") is not None else None)
                cursor.execute("SELECT value_text FROM knowloom_entity_attributes WHERE id=%s AND entity_id=%s FOR UPDATE", (target_id, entity_id))
                target = cursor.fetchone() or {}
                changed_attribute_id = target_id
                action = "dismiss"
                if resolution == "keep_existing":
                    cursor.execute("UPDATE knowloom_entity_attributes SET manually_confirmed=1 WHERE id=%s", (target_id,))
                    action = "keep_existing"
                elif resolution in {"accept_incoming", "keep_both"}:
                    qualifier = str(conflict.get("qualifier_incoming") or "") if resolution == "keep_both" else ""
                    new_id, evidence_added = self._insert_attribute_from_input(cursor, entity_id, incoming, qualifier=qualifier)
                    cursor.execute("UPDATE knowloom_entity_attributes SET manually_confirmed=1 WHERE id=%s", (new_id,))
                    changed_attribute_id = new_id
                    if resolution == "accept_incoming":
                        cursor.execute("UPDATE knowloom_entity_attributes SET status='superseded', superseded_by=%s, superseded_reason='replaced' WHERE id=%s", (new_id, target_id))
                        action = "accept_incoming"
                    else:
                        cursor.execute("UPDATE knowloom_entity_attributes SET manually_confirmed=1, qualifier=CASE WHEN qualifier='' THEN %s ELSE qualifier END WHERE id=%s", (str(conflict.get("qualifier_target") or ""), target_id))
                        action = "keep_both"
                    decision = AttributeDecision(input_index=-1, action="qualify" if resolution == "keep_both" else "supersede", incoming_attribute=incoming, target_attribute_id=target_id, target_value_text=str(target.get("value_text") or ""), confidence=float(conflict.get("confidence") or 0.0), reason=f"manual conflict resolution: {resolution}", source="manual")
                    self._insert_attribute_event(cursor, entity_id=entity_id, attribute_id=changed_attribute_id, decision=decision, before_snapshot=attribute_snapshot(target_id, incoming.attr_type, str(target.get("value_text") or ""), incoming.confidence), after_snapshot=attribute_snapshot(changed_attribute_id, incoming.attr_type, incoming.value_text, incoming.confidence), evidence_added=evidence_added)
                cursor.execute("UPDATE knowloom_entity_attribute_conflicts SET resolved_event_id=(SELECT MAX(id) FROM knowloom_entity_attribute_events WHERE entity_id=%s AND attribute_id=%s) WHERE id=%s", (entity_id, changed_attribute_id, int(conflict_id)))
            connection.commit()
        return True


    def revert_attribute_event(self, event_id: int, *, decided_by: str = "manual") -> dict[str, Any] | None:
        with self.connect() as connection:
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT * FROM knowloom_entity_attribute_events WHERE id=%s AND review_status IN ('auto_applied','approved') AND corrected_by_event_id IS NULL FOR UPDATE", (int(event_id),))
                    event = cursor.fetchone()
                    if not event:
                        connection.rollback()
                        return None
                    action = str(event.get("action") or "")
                    attribute_id = int(event["attribute_id"])
                    candidate = json.loads(event.get("candidate_json") or "null") or {}
                    target_id = int(candidate["attribute_id"]) if candidate.get("attribute_id") else None
                    restored_id = attribute_id
                    if action == "supersede":
                        if target_id is None:
                            raise ValueError("supersede event has no target attribute")
                        cursor.execute("UPDATE knowloom_entity_attributes SET status='active', superseded_by=NULL, superseded_reason='' WHERE id=%s", (target_id,))
                        cursor.execute("UPDATE knowloom_entity_attributes SET status='rejected' WHERE id=%s", (attribute_id,))
                        restored_id = target_id
                    elif action == "archive":
                        cursor.execute("UPDATE knowloom_entity_attributes SET status='active', superseded_by=NULL, superseded_reason='' WHERE id=%s", (attribute_id,))
                    elif action == "qualify":
                        cursor.execute("UPDATE knowloom_entity_attributes SET status='rejected', qualifier='' WHERE id=%s", (attribute_id,))
                        if target_id is not None:
                            cursor.execute("UPDATE knowloom_entity_attributes SET qualifier='' WHERE id=%s", (target_id,))
                    else:
                        raise ValueError(f"event action {action} is not revertible")
                    incoming = json.loads(event.get("incoming_json") or "{}")
                    cursor.execute("""INSERT INTO knowloom_entity_attribute_events (entity_id, attribute_id, attr_type, action, review_status, before_json, after_json, incoming_json, candidate_json, diff_json, decision_reason, confidence, source, note_id, block_id, block_index)
                        VALUES (%s,%s,%s,'revert','approved',%s,%s,%s,%s,%s,%s,1.0,'manual',%s,%s,%s)""",
                        (event["entity_id"], restored_id, event["attr_type"], event.get("after_json"), event.get("before_json"), json.dumps(incoming, ensure_ascii=False), event.get("candidate_json"), json.dumps({"reverted_event_id": int(event_id), "original_action": action}, ensure_ascii=False), f"reverted by {decided_by[:128]}", str(event.get("note_id") or ""), str(event.get("block_id") or ""), int(event.get("block_index") or -1)))
                    correction_id = int(cursor.lastrowid)
                    cursor.execute("UPDATE knowloom_entity_attribute_events SET review_status='reverted', corrected_by_event_id=%s WHERE id=%s AND corrected_by_event_id IS NULL", (correction_id, int(event_id)))
                    if getattr(cursor, "rowcount", 0) != 1:
                        raise RuntimeError("event was reverted concurrently")
                connection.commit()
                return {"event_id": int(event_id), "correction_event_id": correction_id, "restored_attribute_id": restored_id, "original_action": action, "changed_attribute_ids": sorted({restored_id, attribute_id, *([target_id] if target_id is not None else [])})}
            except Exception:
                connection.rollback()
                raise

    def mark_attribute_manually_confirmed(self, attribute_id: int) -> None:
        with self.connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute("UPDATE knowloom_entity_attributes SET manually_confirmed = 1 WHERE id = %s", (int(attribute_id),))
            connection.commit()
