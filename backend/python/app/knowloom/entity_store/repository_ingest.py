import json
from dataclasses import asdict
from typing import Any

from app.knowloom.entity_store.alias_cache import scope_hash
from app.knowloom.entity_store.models import DocumentMetadata, EntityIngestQueueResult, EntityScope, IncomingEntity
from app.knowloom.entity_store.normalizer import normalize_name, text_fingerprint
from app.knowloom.entity_store.repository_helpers import incoming_entity_key
from app.knowloom.entity_store.repository_mappers import (
    build_job_progress,
    incoming_status_row_to_dict,
    job_row_to_dict,
)
from app.knowloom.models import BlockExtractionFailure, KnowLoomPreprocessResult


class IngestJobRepositoryMixin:
    def create_ingest_job(
        self,
        *,
        input_text: str,
        preprocess: KnowLoomPreprocessResult,
        scope: EntityScope,
        incoming_entities: list[IncomingEntity],
        source_blocks_by_key: dict[str, list[dict[str, Any]],],
        source_note_id: str = "",
        task_name: str = "",
        document_metadata: DocumentMetadata | None = None,
        existing_document_id: int | None = None,
    ) -> EntityIngestQueueResult:
        metadata = document_metadata or DocumentMetadata(doc_key=str(source_note_id or text_fingerprint(input_text)))
        if not metadata.doc_key:
            metadata.doc_key = text_fingerprint(input_text)
        with self.connect() as connection:
            try:
                with connection.cursor() as cursor:
                    if existing_document_id is not None:
                        document_id = int(existing_document_id)
                        self._finalize_processing_document(cursor, document_id, scope, metadata, input_text)
                    else:
                        document_id = self._insert_document(cursor, scope, metadata, input_text)
                    block_ids = self._insert_blocks(cursor, document_id, preprocess)
                    self._attach_document_references(incoming_entities, document_id, block_ids)
                    self._attach_document_references_to_source_blocks(source_blocks_by_key, document_id, block_ids)
                    cursor.execute(
                        """
                        INSERT INTO knowloom_ingest_jobs (
                            workspace_id, project_id, collection_id, domain,
                            source_note_id, document_id, task_name,
                            input_fingerprint, input_text, preprocess_json,
                            block_count, entity_count, queued_count, status
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'queued')
                        """,
                        (
                            scope.workspace_id, scope.project_id, scope.collection_id, scope.domain,
                            str(source_note_id or ""), document_id, str(task_name or "")[:255],
                            text_fingerprint(input_text), input_text, preprocess.model_dump_json(),
                            len(preprocess.blocks), preprocess.entity_count, len(incoming_entities),
                        ),
                    )
                    job_id = int(cursor.lastrowid)
                    incoming_ids = self._insert_incoming_entities(cursor, job_id, incoming_entities, source_blocks_by_key)
                    self._insert_extraction_failures(cursor, job_id, scope, source_note_id, preprocess.extraction_failures)
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        return EntityIngestQueueResult(
            job_id=job_id,
            status="queued",
            queued_count=len(incoming_ids),
            incoming_entity_ids=incoming_ids,
            document_id=document_id,
        )

    def check_file_upload(self, *, scope: EntityScope, file_sha256: str, normalized_title: str) -> dict[str, Any]:
        with self.connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute("""SELECT id, doc_key, version_no, title, doc_number FROM knowloom_documents WHERE scope_hash=%s AND file_sha256=%s AND status='active' LIMIT 1""", (scope_hash(scope), file_sha256))
                duplicate = cursor.fetchone()
                same_title: list[dict[str, Any]] = []
                if normalized_title:
                    cursor.execute("""SELECT id, doc_key, version_no, title, doc_number FROM knowloom_documents WHERE scope_hash=%s AND normalized_title=%s AND status='active' ORDER BY version_no DESC""", (scope_hash(scope), normalized_title))
                    same_title = cursor.fetchall()
        return {"duplicate_of": duplicate, "same_title_documents": same_title}

    def create_file_ingest_job(self, *, scope: EntityScope, file_name: str, file_sha256: str, original_file_path: str, metadata: DocumentMetadata, extra_meta: dict[str, Any] | None = None) -> dict[str, Any]:
        key = str(metadata.doc_key or file_sha256)[:128]
        with self.connect() as connection:
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT COALESCE(MAX(version_no),0) AS version_no FROM knowloom_documents WHERE scope_hash=%s AND doc_key=%s FOR UPDATE", (scope_hash(scope), key))
                    version_no = int((cursor.fetchone() or {}).get("version_no") or 0) + 1
                    cursor.execute("""INSERT INTO knowloom_documents (workspace_id,project_id,collection_id,domain,scope_hash,doc_key,version_no,title,normalized_title,doc_number,doc_kind,issuer,issuer_level,audience,source_url,published_at,effective_at,content_text,content_fingerprint,original_file_path,file_sha256,status)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NULLIF(%s,''),NULLIF(%s,''),'','',%s,%s,'processing')""",
                        (scope.workspace_id,scope.project_id,scope.collection_id,scope.domain,scope_hash(scope),key,version_no,metadata.title[:255],metadata.normalized_title[:255],metadata.doc_number[:64],metadata.doc_kind[:32],metadata.issuer[:128],metadata.issuer_level[:16],metadata.audience[:128],metadata.source_url[:1024],metadata.published_at,metadata.effective_at,original_file_path[:1024],file_sha256[:64]))
                    document_id = int(cursor.lastrowid)
                    cursor.execute("""INSERT INTO knowloom_file_ingest_jobs (workspace_id,project_id,collection_id,domain,document_id,file_name,file_sha256,original_file_path,meta_json,status,attempt_count,last_error)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,'converting',0,'')""", (scope.workspace_id,scope.project_id,scope.collection_id,scope.domain,document_id,file_name[:255],file_sha256[:64],original_file_path[:1024],json.dumps({**asdict(metadata), **(extra_meta or {})},ensure_ascii=False)))
                    job_id = int(cursor.lastrowid)
                connection.commit()
            except Exception:
                connection.rollback(); raise
        return {"job_id":job_id,"document_id":document_id,"status":"converting"}

    def get_file_ingest_job(self, job_id: int) -> dict[str, Any] | None:
        with self.connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT * FROM knowloom_file_ingest_jobs WHERE id=%s", (int(job_id),))
                row = cursor.fetchone()
        if row and isinstance(row.get("meta_json"), str):
            row["meta"] = json.loads(row["meta_json"] or "{}")
        elif row:
            row["meta"] = row.get("meta_json") or {}
        return row

    def update_file_ingest_job(self, job_id: int, *, status: str, ingest_job_id: int | None = None, error: str = "") -> None:
        with self.connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute("UPDATE knowloom_file_ingest_jobs SET status=%s, ingest_job_id=COALESCE(%s,ingest_job_id), last_error=%s WHERE id=%s", (status,ingest_job_id,error,int(job_id)))
            connection.commit()

    def claim_file_ingest_retry(self, job_id: int) -> bool:
        with self.connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute("UPDATE knowloom_file_ingest_jobs SET status='converting', attempt_count=attempt_count+1, last_error='' WHERE id=%s AND status='failed'", (int(job_id),))
                changed = getattr(cursor,"rowcount",0)==1
                if changed:
                    cursor.execute("UPDATE knowloom_documents SET status='processing' WHERE id=(SELECT document_id FROM knowloom_file_ingest_jobs WHERE id=%s)", (int(job_id),))
            connection.commit()
        return changed

    def recover_interrupted_file_jobs(self) -> int:
        with self.connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute("UPDATE knowloom_file_ingest_jobs SET status='failed', last_error='interrupted by process restart' WHERE status IN ('converting','preprocessing')")
                changed=int(getattr(cursor,'rowcount',0))
            connection.commit()
        return changed

    def find_duplicate_converted_content(self, document_id: int, content_fingerprint: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute("""SELECT old.id, old.doc_key, old.version_no FROM knowloom_documents pending JOIN knowloom_documents old ON old.scope_hash=pending.scope_hash AND old.doc_key=pending.doc_key WHERE pending.id=%s AND old.id<>pending.id AND old.status='active' AND old.content_fingerprint=%s LIMIT 1""", (int(document_id),content_fingerprint))
                return cursor.fetchone()

    def mark_file_ingest_duplicate(self, job_id: int) -> None:
        with self.connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute("UPDATE knowloom_file_ingest_jobs SET status='duplicate', last_error='' WHERE id=%s", (int(job_id),))
                cursor.execute("UPDATE knowloom_documents SET status='duplicate' WHERE id=(SELECT document_id FROM knowloom_file_ingest_jobs WHERE id=%s)", (int(job_id),))
            connection.commit()

    def find_duplicate_document(self, *, scope: EntityScope, doc_key: str, content_fingerprint: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id, doc_key, version_no, title, status
                    FROM knowloom_documents
                    WHERE scope_hash = %s AND doc_key = %s AND status = 'active'
                      AND content_fingerprint = %s
                    LIMIT 1
                    """,
                    (scope_hash(scope), str(doc_key or ""), content_fingerprint),
                )
                return cursor.fetchone()

    def find_document_by_title(self, *, scope: EntityScope, title: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute("""SELECT id, doc_key, version_no, title, status FROM knowloom_documents
                    WHERE workspace_id=%s AND project_id=%s AND collection_id=%s AND domain=%s AND title=%s AND status='active'
                    ORDER BY version_no DESC LIMIT 1""", (scope.workspace_id, scope.project_id, scope.collection_id, scope.domain, title))
                return cursor.fetchone()

    def get_block_with_context(self, block_id: int, *, context: bool = True) -> dict[str, Any] | None:
        with self.connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT b.id, b.document_id, b.block_index, b.heading, b.anchor_entity, b.l1_text,
                           b.split_reason, b.parent_block_index, b.chunk_index, b.chunk_count,
                           d.doc_key, d.version_no, d.title, d.status
                    FROM knowloom_blocks b
                    INNER JOIN knowloom_documents d ON d.id = b.document_id
                    WHERE b.id = %s
                    LIMIT 1
                    """,
                    (int(block_id),),
                )
                block = cursor.fetchone()
                if not block:
                    return None
                if context:
                    cursor.execute(
                        """
                        SELECT id, document_id, block_index, heading, anchor_entity, l1_text,
                               split_reason, parent_block_index, chunk_index, chunk_count
                        FROM knowloom_blocks
                        WHERE document_id = %s AND block_index BETWEEN %s AND %s
                        ORDER BY block_index, chunk_index
                        """,
                        (int(block["document_id"]), int(block["block_index"]) - 1, int(block["block_index"]) + 1),
                    )
                    block["context_blocks"] = cursor.fetchall()
                return block

    def list_document_versions(self, *, scope: EntityScope, doc_key: str) -> list[dict[str, Any]]:
        with self.connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id, doc_key, version_no, title, doc_number, doc_kind, issuer,
                           issuer_level, audience, source_url, published_at, effective_at,
                           status, created_at
                    FROM knowloom_documents
                    WHERE scope_hash = %s AND doc_key = %s
                    ORDER BY version_no DESC
                    """,
                    (scope_hash(scope), str(doc_key or "")),
                )
                return cursor.fetchall()

    def _finalize_processing_document(self, cursor: Any, document_id: int, scope: EntityScope, metadata: DocumentMetadata, input_text: str) -> None:
        fingerprint = text_fingerprint(input_text)
        cursor.execute("SELECT doc_key FROM knowloom_documents WHERE id=%s AND status='processing' FOR UPDATE", (int(document_id),))
        row = cursor.fetchone()
        if not row:
            raise ValueError("processing document not found")
        doc_key = str(row["doc_key"])
        cursor.execute("""UPDATE knowloom_documents SET status='superseded' WHERE scope_hash=%s AND doc_key=%s AND status='active' AND id<>%s""", (scope_hash(scope), doc_key, int(document_id)))
        cursor.execute("""UPDATE knowloom_documents SET title=%s, normalized_title=%s, doc_number=%s, doc_kind=%s, issuer=%s, issuer_level=%s, audience=%s, source_url=%s,
            published_at=NULLIF(%s,''), effective_at=NULLIF(%s,''), content_text=%s, content_fingerprint=%s, original_file_path=%s, page_map_json=%s, file_sha256=%s, status='active' WHERE id=%s""",
            (metadata.title[:255], metadata.normalized_title[:255], metadata.doc_number[:64], metadata.doc_kind[:32], metadata.issuer[:128], metadata.issuer_level[:16], metadata.audience[:128], metadata.source_url[:1024], metadata.published_at, metadata.effective_at, input_text, fingerprint, metadata.original_file_path[:1024], json.dumps(metadata.page_map, ensure_ascii=False) if metadata.page_map else None, metadata.file_sha256[:64], int(document_id)))

    def _insert_document(self, cursor: Any, scope: EntityScope, metadata: DocumentMetadata, input_text: str) -> int:
        key = str(metadata.doc_key or text_fingerprint(input_text))[:128]
        fingerprint = text_fingerprint(input_text)
        cursor.execute(
            """
            SELECT id, version_no
            FROM knowloom_documents
            WHERE scope_hash = %s AND doc_key = %s AND status = 'active'
            ORDER BY version_no DESC
            LIMIT 1
            FOR UPDATE
            """,
            (scope_hash(scope), key),
        )
        current = cursor.fetchone()
        version_no = int(current["version_no"]) + 1 if current else 1
        if current:
            cursor.execute("UPDATE knowloom_documents SET status = 'superseded' WHERE id = %s", (int(current["id"]),))
        cursor.execute(
            """
            INSERT INTO knowloom_documents (
                workspace_id, project_id, collection_id, domain, scope_hash, doc_key, version_no,
                title, doc_number, doc_kind, issuer, issuer_level, audience, source_url,
                published_at, effective_at, content_text, content_fingerprint, original_file_path, page_map_json, file_sha256, normalized_title, status
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    NULLIF(%s, ''), NULLIF(%s, ''), %s, %s, %s, %s, %s, %s, 'active')
            """,
            (
                scope.workspace_id, scope.project_id, scope.collection_id, scope.domain,
                scope_hash(scope), key, version_no, metadata.title[:255], metadata.doc_number[:64],
                metadata.doc_kind[:32] or 'regulation', metadata.issuer[:128],
                metadata.issuer_level[:16] or 'university', metadata.audience[:128], metadata.source_url[:1024],
                metadata.published_at, metadata.effective_at, input_text, fingerprint, metadata.original_file_path[:1024], json.dumps(metadata.page_map, ensure_ascii=False) if metadata.page_map else None, metadata.file_sha256[:64], metadata.normalized_title[:255],
            ),
        )
        return int(cursor.lastrowid)

    def _insert_blocks(self, cursor: Any, document_id: int, preprocess: KnowLoomPreprocessResult) -> dict[int, int]:
        block_ids: dict[int, int] = {}
        for extraction in preprocess.blocks:
            block = extraction.block
            cursor.execute(
                """
                INSERT INTO knowloom_blocks (
                    document_id, block_index, heading, anchor_entity, l1_text, split_reason,
                    parent_block_index, chunk_index, chunk_count, text_fingerprint
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    int(document_id), int(block.block_index), block.heading[:255], block.anchor_entity[:255],
                    block.l1_text, block.split_reason[:32], block.parent_block_index,
                    int(block.chunk_index), int(block.chunk_count), text_fingerprint(block.l1_text),
                ),
            )
            block_ids[int(block.block_index)] = int(cursor.lastrowid)
        return block_ids

    @staticmethod
    def _attach_document_references(incoming_entities: list[IncomingEntity], document_id: int, block_ids: dict[int, int]) -> None:
        for incoming in incoming_entities:
            for attribute in incoming.attributes:
                attribute.document_id = int(document_id)
                attribute.block_ref_id = block_ids.get(int(attribute.block_index))
            for relation in incoming.relations:
                relation.document_id = int(document_id)
                relation.block_ref_id = block_ids.get(int(relation.block_index))

    @staticmethod
    def _attach_document_references_to_source_blocks(source_blocks_by_key: dict[str, list[dict[str, Any]]], document_id: int, block_ids: dict[int, int]) -> None:
        for blocks in source_blocks_by_key.values():
            for block in blocks:
                block["document_id"] = int(document_id)
                block["block_ref_id"] = block_ids.get(int(block.get("block_index") or -1))

    def list_ingest_jobs(self, *, limit: int = 20) -> list[dict[str, Any]]:
        with self.connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id
                    FROM knowloom_ingest_jobs
                    ORDER BY id DESC
                    LIMIT %s
                    """,
                    (max(1, min(100, int(limit))),),
                )
                rows = cursor.fetchall()
        return [
            job
            for row in rows
            if (job := self.get_ingest_job_status(int(row["id"]))) is not None
        ]

    def get_ingest_job_status(self, job_id: int) -> dict[str, Any] | None:
        with self.connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id, workspace_id, project_id, collection_id, domain,
                           source_note_id, document_id, task_name,
                           block_count, entity_count, queued_count, status,
                           created_at, updated_at
                    FROM knowloom_ingest_jobs
                    WHERE id = %s
                    LIMIT 1
                    """,
                    (int(job_id),),
                )
                job = cursor.fetchone()
                if not job:
                    return None

                cursor.execute(
                    """
                    SELECT status, COUNT(*) AS count
                    FROM knowloom_incoming_entities
                    WHERE job_id = %s
                    GROUP BY status
                    """,
                    (int(job_id),),
                )
                status_rows = cursor.fetchall()
                cursor.execute(
                    """
                    SELECT
                        i.id,
                        i.name,
                        i.normalized_name,
                        i.entity_type,
                        i.status,
                        i.attempt_count,
                        i.matched_entity_id,
                        i.decision,
                        i.decision_score,
                        i.decision_reason,
                        i.last_error,
                        i.locked_by,
                        i.locked_until,
                        i.created_at,
                        i.updated_at,
                        r.id AS review_task_id,
                        r.status AS review_status
                    FROM knowloom_incoming_entities i
                    LEFT JOIN knowloom_entity_review_tasks r
                      ON r.incoming_entity_id = i.id AND r.status = 'pending'
                    WHERE i.job_id = %s
                    ORDER BY i.id
                    """,
                    (int(job_id),),
                )
                incoming_rows = cursor.fetchall()

        item = job_row_to_dict(job)
        item["status_counts"] = {str(row["status"]): int(row["count"]) for row in status_rows}
        item["incoming_entities"] = [incoming_status_row_to_dict(row) for row in incoming_rows]
        item["progress"] = build_job_progress(item["status_counts"], len(incoming_rows))
        return item

    def ingest_observability_summary(self) -> dict[str, Any]:
        with self.connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT status, COUNT(*) AS count
                    FROM knowloom_incoming_entities
                    GROUP BY status
                    """
                )
                status_rows = cursor.fetchall()
                cursor.execute(
                    """
                    SELECT
                        COALESCE(AVG(TIMESTAMPDIFF(MICROSECOND, created_at, updated_at)) / 1000, 0) AS avg_ms
                    FROM knowloom_incoming_entities
                    WHERE status IN ('auto_merged', 'manual_merged', 'new_created', 'completed')
                    """
                )
                avg_row = cursor.fetchone() or {}
                cursor.execute(
                    """
                    SELECT
                        COALESCE(SUM(GREATEST(attempt_count - 1, 0)), 0) AS retry_count,
                        COALESCE(SUM(CASE WHEN status IN ('failed', 'dead_letter') THEN 1 ELSE 0 END), 0) AS failed_count
                    FROM knowloom_incoming_entities
                    """
                )
                error_row = cursor.fetchone() or {}
        return {
            "status_counts": {str(row["status"]): int(row["count"]) for row in status_rows},
            "average_completed_ms": float(avg_row.get("avg_ms") or 0),
            "retry_count": int(error_row.get("retry_count") or 0),
            "failed_count": int(error_row.get("failed_count") or 0),
        }

    def _insert_incoming_entities(
        self,
        cursor: Any,
        job_id: int,
        incoming_entities: list[IncomingEntity],
        source_blocks_by_key: dict[str, list[dict[str, Any]]],
    ) -> list[int]:
        incoming_ids: list[int] = []
        for incoming in incoming_entities:
            key = incoming_entity_key(incoming)
            dedupe_key = text_fingerprint(f"{job_id}:{key}")
            cursor.execute(
                """
                INSERT INTO knowloom_incoming_entities (
                    job_id, workspace_id, project_id, collection_id, domain,
                    dedupe_key, name, normalized_name, entity_type, aliases_json,
                    identity_description, identity_source, identity_user_text, description_for_match, attributes_json, relations_json,
                    source_blocks_json, source_count, status, decision_reason, last_error
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'pending', '', '')
                ON DUPLICATE KEY UPDATE
                    updated_at = CURRENT_TIMESTAMP,
                    id = LAST_INSERT_ID(id)
                """,
                (
                    job_id,
                    incoming.scope.workspace_id,
                    incoming.scope.project_id,
                    incoming.scope.collection_id,
                    incoming.scope.domain,
                    dedupe_key,
                    incoming.name,
                    incoming.normalized_name or normalize_name(incoming.name),
                    incoming.entity_type or "concept",
                    json.dumps(incoming.aliases, ensure_ascii=False),
                    incoming.identity_description,
                    incoming.identity_source,
                    incoming.identity_user_text or None,
                    incoming.description_for_match,
                    json.dumps([asdict(attribute) for attribute in incoming.attributes], ensure_ascii=False),
                    json.dumps([asdict(relation) for relation in incoming.relations], ensure_ascii=False),
                    json.dumps(source_blocks_by_key.get(key, []), ensure_ascii=False),
                    incoming.source_count,
                ),
            )
            incoming_ids.append(int(cursor.lastrowid))
        return incoming_ids

    def _insert_extraction_failures(
        self,
        cursor: Any,
        job_id: int,
        scope: EntityScope,
        source_note_id: str,
        failures: list[BlockExtractionFailure],
    ) -> None:
        for failure in failures:
            cursor.execute(
                """
                INSERT INTO knowloom_entity_extraction_failures (
                    job_id, workspace_id, project_id, collection_id, domain,
                    source_note_id, block_index, heading, anchor_entity,
                    l1_text, error, status
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'pending')
                """,
                (
                    int(job_id),
                    scope.workspace_id,
                    scope.project_id,
                    scope.collection_id,
                    scope.domain,
                    str(source_note_id or ""),
                    int(failure.block_index),
                    failure.heading[:255],
                    failure.anchor_entity[:255],
                    failure.l1_text,
                    failure.error,
                ),
            )
