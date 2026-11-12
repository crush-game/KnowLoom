from typing import Any


def ensure_entity_table_columns(cursor: Any) -> None:
    cursor.execute("SHOW COLUMNS FROM knowloom_entities")
    existing_columns = {str(row["Field"]) for row in cursor.fetchall()}
    scope_columns = {
        "workspace_id": "ALTER TABLE knowloom_entities ADD COLUMN workspace_id VARCHAR(128) NOT NULL DEFAULT 'local' AFTER id",
        "project_id": "ALTER TABLE knowloom_entities ADD COLUMN project_id VARCHAR(128) NOT NULL DEFAULT 'knowloom' AFTER workspace_id",
        "collection_id": "ALTER TABLE knowloom_entities ADD COLUMN collection_id VARCHAR(128) NOT NULL DEFAULT 'default' AFTER project_id",
        "domain": "ALTER TABLE knowloom_entities ADD COLUMN domain VARCHAR(128) NOT NULL DEFAULT 'general' AFTER collection_id",
    }
    for column, statement in scope_columns.items():
        if column not in existing_columns:
            cursor.execute(statement)
    if "identity_description" not in existing_columns:
        cursor.execute(
            """
            ALTER TABLE knowloom_entities
            ADD COLUMN identity_description TEXT NOT NULL AFTER aliases_json
            """
        )
    ensure_index(cursor, "knowloom_entities", "idx_knowloom_entities_scope", "workspace_id, project_id, collection_id, domain")
    ensure_index(cursor, "knowloom_entities", "idx_knowloom_entities_scope_name", "workspace_id, project_id, collection_id, domain, normalized_name")
    ensure_resolution_audit_scope_columns(cursor)
    ensure_ingest_job_columns(cursor)
    ensure_attribute_state_columns(cursor)
    ensure_attribute_conflict_columns(cursor)
    ensure_document_layer_schema(cursor)
    ensure_identity_schema(cursor)
    ensure_document_relation_schema(cursor)
    ensure_entity_relation_schema(cursor)
    ensure_file_ingest_schema(cursor)
    ensure_incoming_entity_columns(cursor)
    ensure_review_table_indexes(cursor)
    ensure_attribute_decision_tables(cursor)


def ensure_resolution_audit_scope_columns(cursor: Any) -> None:
    cursor.execute("SHOW COLUMNS FROM knowloom_entity_resolution_audit")
    existing_columns = {str(row["Field"]) for row in cursor.fetchall()}
    scope_columns = {
        "workspace_id": "ALTER TABLE knowloom_entity_resolution_audit ADD COLUMN workspace_id VARCHAR(128) NOT NULL DEFAULT 'local' AFTER id",
        "project_id": "ALTER TABLE knowloom_entity_resolution_audit ADD COLUMN project_id VARCHAR(128) NOT NULL DEFAULT 'knowloom' AFTER workspace_id",
        "collection_id": "ALTER TABLE knowloom_entity_resolution_audit ADD COLUMN collection_id VARCHAR(128) NOT NULL DEFAULT 'default' AFTER project_id",
        "domain": "ALTER TABLE knowloom_entity_resolution_audit ADD COLUMN domain VARCHAR(128) NOT NULL DEFAULT 'general' AFTER collection_id",
    }
    for column, statement in scope_columns.items():
        if column not in existing_columns:
            cursor.execute(statement)
    ensure_index(cursor, "knowloom_entity_resolution_audit", "idx_knowloom_resolution_audit_scope", "workspace_id, project_id, collection_id, domain")


def ensure_ingest_job_columns(cursor: Any) -> None:
    cursor.execute("SHOW TABLES LIKE 'knowloom_ingest_jobs'")
    if not cursor.fetchone():
        return
    cursor.execute("SHOW COLUMNS FROM knowloom_ingest_jobs")
    existing_columns = {str(row["Field"]) for row in cursor.fetchall()}
    columns = {
        "source_note_id": "ALTER TABLE knowloom_ingest_jobs ADD COLUMN source_note_id VARCHAR(128) NOT NULL DEFAULT '' AFTER domain",
        "document_id": "ALTER TABLE knowloom_ingest_jobs ADD COLUMN document_id BIGINT NULL AFTER source_note_id",
        "task_name": "ALTER TABLE knowloom_ingest_jobs ADD COLUMN task_name VARCHAR(255) NOT NULL DEFAULT '' AFTER document_id",
        "swept_at": "ALTER TABLE knowloom_ingest_jobs ADD COLUMN swept_at TIMESTAMP NULL AFTER status",
    }
    for column, statement in columns.items():
        if column not in existing_columns:
            cursor.execute(statement)




def ensure_attribute_state_columns(cursor: Any) -> None:
    cursor.execute("SHOW COLUMNS FROM knowloom_entity_attributes")
    columns = {str(row["Field"]) for row in cursor.fetchall()}
    additions = {
        "qualifier": "ALTER TABLE knowloom_entity_attributes ADD COLUMN qualifier VARCHAR(255) NOT NULL DEFAULT '' AFTER status",
        "superseded_by": "ALTER TABLE knowloom_entity_attributes ADD COLUMN superseded_by BIGINT NULL AFTER qualifier",
        "superseded_reason": "ALTER TABLE knowloom_entity_attributes ADD COLUMN superseded_reason VARCHAR(32) NOT NULL DEFAULT '' AFTER superseded_by",
        "manually_confirmed": "ALTER TABLE knowloom_entity_attributes ADD COLUMN manually_confirmed TINYINT(1) NOT NULL DEFAULT 0 AFTER superseded_reason",
    }
    for name, statement in additions.items():
        if name not in columns:
            cursor.execute(statement)
    ensure_index(cursor, "knowloom_entity_attributes", "idx_knowloom_entity_attributes_entity_type_status", "entity_id, attr_type, status")



def ensure_attribute_conflict_columns(cursor: Any) -> None:
    cursor.execute("SHOW TABLES LIKE 'knowloom_entity_attribute_conflicts'")
    if not cursor.fetchone():
        return
    cursor.execute("SHOW COLUMNS FROM knowloom_entity_attribute_conflicts")
    columns = {str(row["Field"]) for row in cursor.fetchall()}
    additions = {
        "kind": "ALTER TABLE knowloom_entity_attribute_conflicts ADD COLUMN kind VARCHAR(16) NOT NULL DEFAULT 'factual' AFTER confidence",
        "incoming_json": "ALTER TABLE knowloom_entity_attribute_conflicts ADD COLUMN incoming_json JSON NULL AFTER kind",
        "suggestion": "ALTER TABLE knowloom_entity_attribute_conflicts ADD COLUMN suggestion VARCHAR(32) NOT NULL DEFAULT '' AFTER incoming_json",
        "qualifier_incoming": "ALTER TABLE knowloom_entity_attribute_conflicts ADD COLUMN qualifier_incoming VARCHAR(255) NOT NULL DEFAULT '' AFTER suggestion",
        "qualifier_target": "ALTER TABLE knowloom_entity_attribute_conflicts ADD COLUMN qualifier_target VARCHAR(255) NOT NULL DEFAULT '' AFTER qualifier_incoming",
        "resolution": "ALTER TABLE knowloom_entity_attribute_conflicts ADD COLUMN resolution VARCHAR(32) NOT NULL DEFAULT '' AFTER qualifier_target",
        "resolved_by": "ALTER TABLE knowloom_entity_attribute_conflicts ADD COLUMN resolved_by VARCHAR(128) NOT NULL DEFAULT '' AFTER resolution",
        "resolved_at": "ALTER TABLE knowloom_entity_attribute_conflicts ADD COLUMN resolved_at TIMESTAMP NULL AFTER resolved_by",
        "resolved_event_id": "ALTER TABLE knowloom_entity_attribute_conflicts ADD COLUMN resolved_event_id BIGINT NULL AFTER resolved_at",
    }
    for name, statement in additions.items():
        if name not in columns:
            cursor.execute(statement)


def ensure_document_layer_schema(cursor: Any) -> None:
    """Backfill the D-002 document-layer columns for databases created before this release."""
    cursor.execute("SHOW TABLES LIKE 'knowloom_documents'")
    if cursor.fetchone():
        cursor.execute("SHOW COLUMNS FROM knowloom_documents")
        document_columns = {str(row["Field"]) for row in cursor.fetchall()}
        if "original_file_path" not in document_columns:
            cursor.execute("ALTER TABLE knowloom_documents ADD COLUMN original_file_path VARCHAR(1024) NOT NULL DEFAULT '' AFTER content_fingerprint")
        if "page_map_json" not in document_columns:
            cursor.execute("ALTER TABLE knowloom_documents ADD COLUMN page_map_json JSON NULL AFTER original_file_path")
        if "file_sha256" not in document_columns:
            cursor.execute("ALTER TABLE knowloom_documents ADD COLUMN file_sha256 CHAR(64) NOT NULL DEFAULT '' AFTER page_map_json")
        if "normalized_title" not in document_columns:
            cursor.execute("ALTER TABLE knowloom_documents ADD COLUMN normalized_title VARCHAR(255) NOT NULL DEFAULT '' AFTER file_sha256")
    cursor.execute("SHOW TABLES LIKE 'knowloom_entity_attribute_evidence'")
    if cursor.fetchone():
        cursor.execute("SHOW COLUMNS FROM knowloom_entity_attribute_evidence")
        columns = {str(row["Field"]) for row in cursor.fetchall()}
        additions = {
            "document_id": "ALTER TABLE knowloom_entity_attribute_evidence ADD COLUMN document_id BIGINT NULL AFTER attribute_id",
            "block_ref_id": "ALTER TABLE knowloom_entity_attribute_evidence ADD COLUMN block_ref_id BIGINT NULL AFTER document_id",
        }
        for name, statement in additions.items():
            if name not in columns:
                cursor.execute(statement)
        cursor.execute("SHOW INDEX FROM knowloom_entity_attribute_evidence WHERE Key_name='uk_knowloom_attr_evidence_fingerprint'")
        unique_rows = cursor.fetchall()
        unique_columns = [str(row.get("Column_name") or "") for row in sorted(unique_rows, key=lambda row: int(row.get("Seq_in_index") or 0))]
        if unique_columns != ["attribute_id", "document_id", "evidence_fingerprint"]:
            if unique_rows:
                cursor.execute("ALTER TABLE knowloom_entity_attribute_evidence DROP INDEX uk_knowloom_attr_evidence_fingerprint")
            cursor.execute("ALTER TABLE knowloom_entity_attribute_evidence ADD UNIQUE KEY uk_knowloom_attr_evidence_fingerprint (attribute_id, document_id, evidence_fingerprint)")
        ensure_index(cursor, "knowloom_entity_attribute_evidence", "idx_knowloom_evidence_block_ref", "block_ref_id")


def ensure_index(cursor: Any, table_name: str, index_name: str, columns_sql: str) -> None:
    cursor.execute("SHOW INDEX FROM {table_name} WHERE Key_name = %s".format(table_name=table_name), (index_name,))
    if not cursor.fetchone():
        cursor.execute(f"ALTER TABLE {table_name} ADD INDEX {index_name} ({columns_sql})")


def ensure_incoming_entity_columns(cursor: Any) -> None:
    cursor.execute("SHOW TABLES LIKE 'knowloom_incoming_entities'")
    if not cursor.fetchone():
        return
    cursor.execute("SHOW COLUMNS FROM knowloom_incoming_entities")
    existing_columns = {str(row["Field"]) for row in cursor.fetchall()}
    columns = {
        "matched_entity_id": "ALTER TABLE knowloom_incoming_entities ADD COLUMN matched_entity_id BIGINT NULL AFTER attempt_count",
        "decision": "ALTER TABLE knowloom_incoming_entities ADD COLUMN decision VARCHAR(32) NOT NULL DEFAULT '' AFTER matched_entity_id",
        "decision_score": "ALTER TABLE knowloom_incoming_entities ADD COLUMN decision_score DOUBLE NOT NULL DEFAULT 0 AFTER decision",
        "decision_reason": "ALTER TABLE knowloom_incoming_entities ADD COLUMN decision_reason TEXT NOT NULL AFTER decision_score",
        "relations_json": "ALTER TABLE knowloom_incoming_entities ADD COLUMN relations_json JSON NULL AFTER attributes_json",
    }
    for column, statement in columns.items():
        if column not in existing_columns:
            cursor.execute(statement)


def ensure_review_table_indexes(cursor: Any) -> None:
    cursor.execute("SHOW TABLES LIKE 'knowloom_entity_review_tasks'")
    if not cursor.fetchone():
        return
    ensure_index(cursor, "knowloom_entity_review_tasks", "idx_knowloom_review_incoming_status", "incoming_entity_id, status")
    cursor.execute("SHOW INDEX FROM knowloom_entity_review_tasks WHERE Key_name = 'uk_knowloom_review_incoming_active'")
    if cursor.fetchone():
        try:
            cursor.execute("ALTER TABLE knowloom_entity_review_tasks DROP INDEX uk_knowloom_review_incoming_active")
        except Exception as exc:
            if not is_mysql_foreign_key_index_drop_error(exc):
                raise


def is_mysql_foreign_key_index_drop_error(exc: Exception) -> bool:
    args = getattr(exc, "args", ())
    return bool(args and int(args[0]) == 1553)


def ensure_attribute_decision_tables(cursor: Any) -> None:
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS knowloom_entity_attribute_decision_audit (
            id BIGINT PRIMARY KEY AUTO_INCREMENT,
            entity_id BIGINT NOT NULL,
            input_index INT NOT NULL DEFAULT -1,
            action VARCHAR(32) NOT NULL,
            attr_type VARCHAR(32) NOT NULL,
            incoming_value_text TEXT NOT NULL,
            target_attribute_id BIGINT NULL,
            changed_attribute_id BIGINT NULL,
            new_value_text TEXT NOT NULL,
            confidence DOUBLE NOT NULL DEFAULT 0,
            reason TEXT NOT NULL,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_knowloom_attr_decision_entity (entity_id),
            INDEX idx_knowloom_attr_decision_action (action)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS knowloom_entity_attribute_conflicts (
            id BIGINT PRIMARY KEY AUTO_INCREMENT,
            entity_id BIGINT NOT NULL,
            attribute_id BIGINT NOT NULL,
            attr_type VARCHAR(32) NOT NULL,
            incoming_value_text TEXT NOT NULL,
            incoming_evidence TEXT NOT NULL,
            reason TEXT NOT NULL,
            confidence DOUBLE NOT NULL DEFAULT 0,
            status VARCHAR(32) NOT NULL DEFAULT 'pending',
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            INDEX idx_knowloom_attr_conflict_entity (entity_id),
            INDEX idx_knowloom_attr_conflict_attribute (attribute_id),
            INDEX idx_knowloom_attr_conflict_status (status)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS knowloom_entity_attribute_events (
            id BIGINT PRIMARY KEY AUTO_INCREMENT,
            entity_id BIGINT NOT NULL,
            attribute_id BIGINT NOT NULL,
            attr_type VARCHAR(32) NOT NULL,
            action VARCHAR(32) NOT NULL,
            review_status VARCHAR(32) NOT NULL DEFAULT 'pending',
            before_json JSON NULL,
            after_json JSON NULL,
            incoming_json JSON NOT NULL,
            candidate_json JSON NULL,
            diff_json JSON NOT NULL,
            decision_reason TEXT NOT NULL,
            confidence DOUBLE NOT NULL DEFAULT 0,
            source VARCHAR(64) NOT NULL DEFAULT 'auto',
            note_id VARCHAR(128) NOT NULL DEFAULT '',
            block_id VARCHAR(128) NOT NULL DEFAULT '',
            block_index INT NOT NULL DEFAULT -1,
            corrected_by_event_id BIGINT NULL,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_knowloom_attr_event_entity (entity_id),
            INDEX idx_knowloom_attr_event_attribute (attribute_id),
            INDEX idx_knowloom_attr_event_action (action),
            INDEX idx_knowloom_attr_event_review (review_status)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """
    )


def ensure_identity_schema(cursor: Any) -> None:
    cursor.execute("SHOW COLUMNS FROM knowloom_entities")
    columns = {str(row["Field"]) for row in cursor.fetchall()}
    additions = {
        "identity_source": "ALTER TABLE knowloom_entities ADD COLUMN identity_source VARCHAR(16) NOT NULL DEFAULT 'model_prior' AFTER identity_description",
        "identity_user_text": "ALTER TABLE knowloom_entities ADD COLUMN identity_user_text TEXT NULL AFTER identity_source",
        "identity_basis_json": "ALTER TABLE knowloom_entities ADD COLUMN identity_basis_json JSON NULL AFTER identity_user_text",
        "identity_updated_at": "ALTER TABLE knowloom_entities ADD COLUMN identity_updated_at TIMESTAMP NULL AFTER identity_basis_json",
    }
    for name, statement in additions.items():
        if name not in columns:
            cursor.execute(statement)
    cursor.execute("SHOW COLUMNS FROM knowloom_incoming_entities")
    incoming_columns = {str(row["Field"]) for row in cursor.fetchall()}
    if "identity_source" not in incoming_columns:
        cursor.execute("ALTER TABLE knowloom_incoming_entities ADD COLUMN identity_source VARCHAR(16) NOT NULL DEFAULT 'model_prior' AFTER identity_description")
    if "identity_user_text" not in incoming_columns:
        cursor.execute("ALTER TABLE knowloom_incoming_entities ADD COLUMN identity_user_text TEXT NULL AFTER identity_source")
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS knowloom_entity_identity_events (
            id BIGINT PRIMARY KEY AUTO_INCREMENT, entity_id BIGINT NOT NULL, before_text TEXT NULL,
            before_source VARCHAR(16) NOT NULL DEFAULT '', after_text TEXT NOT NULL,
            after_source VARCHAR(16) NOT NULL, trigger_reason VARCHAR(64) NOT NULL, basis_json JSON NULL,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP, INDEX idx_knowloom_identity_event_entity (entity_id),
            CONSTRAINT fk_knowloom_identity_event_entity FOREIGN KEY (entity_id) REFERENCES knowloom_entities(id) ON DELETE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """)


def ensure_document_relation_schema(cursor: Any) -> None:
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS knowloom_document_relations (
            id BIGINT PRIMARY KEY AUTO_INCREMENT, workspace_id VARCHAR(128) NOT NULL DEFAULT 'local', project_id VARCHAR(128) NOT NULL DEFAULT 'knowloom', collection_id VARCHAR(128) NOT NULL DEFAULT 'default', domain VARCHAR(128) NOT NULL DEFAULT 'general',
            source_doc_key VARCHAR(255) NOT NULL, target_doc_key VARCHAR(255) NOT NULL, relation_type VARCHAR(32) NOT NULL, confidence DOUBLE NOT NULL DEFAULT 1.0, source VARCHAR(32) NOT NULL DEFAULT 'manual', evidence_text TEXT NOT NULL, status VARCHAR(16) NOT NULL DEFAULT 'active', created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE KEY uk_knowloom_document_relation (workspace_id, project_id, collection_id, domain, source_doc_key, target_doc_key, relation_type), INDEX idx_knowloom_document_relation_target (target_doc_key, relation_type)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """)
    cursor.execute("SHOW COLUMNS FROM knowloom_document_relations")
    relation_columns = {str(row["Field"]) for row in cursor.fetchall()}
    if "evidence_text" not in relation_columns:
        cursor.execute("ALTER TABLE knowloom_document_relations ADD COLUMN evidence_text TEXT NOT NULL AFTER source")
    if "status" not in relation_columns:
        cursor.execute("ALTER TABLE knowloom_document_relations ADD COLUMN status VARCHAR(16) NOT NULL DEFAULT 'active' AFTER evidence_text")


def ensure_entity_relation_schema(cursor: Any) -> None:
    cursor.execute("""CREATE TABLE IF NOT EXISTS knowloom_entity_relations (
        id BIGINT PRIMARY KEY AUTO_INCREMENT, scope_hash CHAR(40) NOT NULL, source_entity_id BIGINT NOT NULL,
        target_name VARCHAR(255) NOT NULL, target_normalized_name VARCHAR(255) NOT NULL, target_entity_id BIGINT NULL,
        relation_type VARCHAR(32) NOT NULL, confidence DOUBLE NOT NULL DEFAULT 0.7, status VARCHAR(16) NOT NULL DEFAULT 'active',
        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        UNIQUE KEY uk_knowloom_entity_relation (source_entity_id, target_normalized_name, relation_type),
        INDEX idx_knowloom_entity_relation_target (scope_hash, target_normalized_name, target_entity_id),
        INDEX idx_knowloom_entity_relation_target_entity (target_entity_id),
        CONSTRAINT fk_knowloom_relation_source FOREIGN KEY (source_entity_id) REFERENCES knowloom_entities(id) ON DELETE CASCADE,
        CONSTRAINT fk_knowloom_relation_target FOREIGN KEY (target_entity_id) REFERENCES knowloom_entities(id) ON DELETE SET NULL
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""")
    cursor.execute("""CREATE TABLE IF NOT EXISTS knowloom_entity_relation_evidence (
        id BIGINT PRIMARY KEY AUTO_INCREMENT, relation_id BIGINT NOT NULL, document_id BIGINT NULL, block_ref_id BIGINT NULL,
        evidence_text TEXT NOT NULL, evidence_fingerprint CHAR(64) NOT NULL,
        UNIQUE KEY uk_knowloom_entity_relation_evidence (relation_id, document_id, evidence_fingerprint),
        CONSTRAINT fk_knowloom_relation_evidence_relation FOREIGN KEY (relation_id) REFERENCES knowloom_entity_relations(id) ON DELETE CASCADE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""")
    cursor.execute("SHOW INDEX FROM knowloom_entity_relation_evidence WHERE Key_name='uk_knowloom_entity_relation_evidence'")
    relation_unique_rows = cursor.fetchall()
    relation_unique_columns = [str(row.get("Column_name") or "") for row in sorted(relation_unique_rows, key=lambda row: int(row.get("Seq_in_index") or 0))]
    if relation_unique_columns != ["relation_id", "document_id", "evidence_fingerprint"]:
        if relation_unique_rows:
            cursor.execute("ALTER TABLE knowloom_entity_relation_evidence DROP INDEX uk_knowloom_entity_relation_evidence")
        cursor.execute("ALTER TABLE knowloom_entity_relation_evidence ADD UNIQUE KEY uk_knowloom_entity_relation_evidence (relation_id, document_id, evidence_fingerprint)")


def ensure_file_ingest_schema(cursor: Any) -> None:
    cursor.execute("""CREATE TABLE IF NOT EXISTS knowloom_file_ingest_jobs (
        id BIGINT PRIMARY KEY AUTO_INCREMENT, workspace_id VARCHAR(128) NOT NULL, project_id VARCHAR(128) NOT NULL, collection_id VARCHAR(128) NOT NULL, domain VARCHAR(128) NOT NULL,
        document_id BIGINT NOT NULL, file_name VARCHAR(255) NOT NULL, file_sha256 CHAR(64) NOT NULL, original_file_path VARCHAR(1024) NOT NULL, meta_json JSON NOT NULL,
        status VARCHAR(32) NOT NULL DEFAULT 'converting', ingest_job_id BIGINT NULL, attempt_count INT NOT NULL DEFAULT 0, last_error TEXT NOT NULL,
        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        INDEX idx_knowloom_file_job_status (status), INDEX idx_knowloom_file_job_sha (file_sha256),
        CONSTRAINT fk_knowloom_file_job_document FOREIGN KEY (document_id) REFERENCES knowloom_documents(id) ON DELETE CASCADE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""")
