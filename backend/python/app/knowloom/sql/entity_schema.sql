CREATE TABLE IF NOT EXISTS knowloom_entities (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    workspace_id VARCHAR(128) NOT NULL DEFAULT 'local',
    project_id VARCHAR(128) NOT NULL DEFAULT 'knowloom',
    collection_id VARCHAR(128) NOT NULL DEFAULT 'default',
    domain VARCHAR(128) NOT NULL DEFAULT 'general',
    canonical_name VARCHAR(255) NOT NULL,
    normalized_name VARCHAR(255) NOT NULL,
    entity_type VARCHAR(64) NOT NULL DEFAULT 'concept',
    aliases_json JSON NOT NULL,
    identity_description TEXT NOT NULL,
    identity_source VARCHAR(16) NOT NULL DEFAULT 'model_prior',
    identity_user_text TEXT NULL,
    identity_basis_json JSON NULL,
    identity_updated_at TIMESTAMP NULL,
    summary TEXT NOT NULL,
    description_for_match TEXT NOT NULL,
    embedding_json JSON NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'active',
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_knowloom_entities_normalized_name (normalized_name),
    INDEX idx_knowloom_entities_type_name (entity_type, normalized_name),
    INDEX idx_knowloom_entities_scope (workspace_id, project_id, collection_id, domain),
    INDEX idx_knowloom_entities_scope_name (workspace_id, project_id, collection_id, domain, normalized_name),
    INDEX idx_knowloom_entities_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS knowloom_entity_attributes (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    entity_id BIGINT NOT NULL,
    attr_type VARCHAR(32) NOT NULL,
    value_text TEXT NOT NULL,
    value_fingerprint CHAR(64) NOT NULL,
    confidence DOUBLE NOT NULL DEFAULT 0.7,
    status VARCHAR(32) NOT NULL DEFAULT 'active',
    qualifier VARCHAR(255) NOT NULL DEFAULT '',
    superseded_by BIGINT NULL,
    superseded_reason VARCHAR(32) NOT NULL DEFAULT '',
    manually_confirmed TINYINT(1) NOT NULL DEFAULT 0,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_knowloom_entity_attr_fingerprint (entity_id, attr_type, value_fingerprint),
    INDEX idx_knowloom_entity_attributes_entity (entity_id),
    INDEX idx_knowloom_entity_attributes_type (attr_type),
    INDEX idx_knowloom_entity_attributes_entity_type_status (entity_id, attr_type, status),
    CONSTRAINT fk_knowloom_entity_attributes_entity
        FOREIGN KEY (entity_id) REFERENCES knowloom_entities(id)
        ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS knowloom_entity_attribute_evidence (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    attribute_id BIGINT NOT NULL,
    document_id BIGINT NULL,
    block_ref_id BIGINT NULL,
    note_id VARCHAR(128) NOT NULL DEFAULT '',
    block_id VARCHAR(128) NOT NULL DEFAULT '',
    block_index INT NOT NULL DEFAULT -1,
    evidence_text TEXT NOT NULL,
    evidence_fingerprint CHAR(64) NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uk_knowloom_attr_evidence_fingerprint (attribute_id, document_id, evidence_fingerprint),
    INDEX idx_knowloom_entity_evidence_attribute (attribute_id),
    INDEX idx_knowloom_entity_evidence_block (note_id, block_id),
    INDEX idx_knowloom_evidence_block_ref (block_ref_id),
    CONSTRAINT fk_knowloom_entity_evidence_attribute
        FOREIGN KEY (attribute_id) REFERENCES knowloom_entity_attributes(id)
        ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS knowloom_entity_resolution_audit (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    workspace_id VARCHAR(128) NOT NULL DEFAULT 'local',
    project_id VARCHAR(128) NOT NULL DEFAULT 'knowloom',
    collection_id VARCHAR(128) NOT NULL DEFAULT 'default',
    domain VARCHAR(128) NOT NULL DEFAULT 'general',
    incoming_name VARCHAR(255) NOT NULL,
    incoming_type VARCHAR(64) NOT NULL DEFAULT '',
    decision VARCHAR(32) NOT NULL,
    matched_entity_id BIGINT NULL,
    score DOUBLE NOT NULL DEFAULT 0,
    reason TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_knowloom_resolution_audit_scope (workspace_id, project_id, collection_id, domain),
    INDEX idx_knowloom_resolution_audit_name (incoming_name),
    INDEX idx_knowloom_resolution_audit_decision (decision),
    CONSTRAINT fk_knowloom_resolution_audit_entity
        FOREIGN KEY (matched_entity_id) REFERENCES knowloom_entities(id)
        ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS knowloom_entity_aliases (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    workspace_id VARCHAR(128) NOT NULL DEFAULT 'local',
    project_id VARCHAR(128) NOT NULL DEFAULT 'knowloom',
    collection_id VARCHAR(128) NOT NULL DEFAULT 'default',
    domain VARCHAR(128) NOT NULL DEFAULT 'general',
    scope_hash CHAR(40) NOT NULL,
    entity_id BIGINT NOT NULL,
    alias_text VARCHAR(255) NOT NULL,
    normalized_alias VARCHAR(255) NOT NULL,
    alias_type VARCHAR(32) NOT NULL DEFAULT 'alias',
    confidence DOUBLE NOT NULL DEFAULT 1.0,
    source VARCHAR(64) NOT NULL DEFAULT 'system',
    status VARCHAR(32) NOT NULL DEFAULT 'active',
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_knowloom_entity_alias_scope_alias_status (
        scope_hash, normalized_alias, status
    ),
    INDEX idx_knowloom_entity_alias_entity (entity_id),
    INDEX idx_knowloom_entity_alias_scope (workspace_id, project_id, collection_id, domain),
    INDEX idx_knowloom_entity_alias_status (status),
    CONSTRAINT fk_knowloom_entity_alias_entity
        FOREIGN KEY (entity_id) REFERENCES knowloom_entities(id)
        ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS knowloom_documents (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    workspace_id VARCHAR(128) NOT NULL DEFAULT 'local',
    project_id VARCHAR(128) NOT NULL DEFAULT 'knowloom',
    collection_id VARCHAR(128) NOT NULL DEFAULT 'default',
    domain VARCHAR(128) NOT NULL DEFAULT 'general',
    scope_hash CHAR(64) NOT NULL,
    doc_key VARCHAR(128) NOT NULL,
    version_no INT NOT NULL DEFAULT 1,
    title VARCHAR(255) NOT NULL DEFAULT '',
    doc_number VARCHAR(64) NOT NULL DEFAULT '',
    doc_kind VARCHAR(32) NOT NULL DEFAULT 'regulation',
    issuer VARCHAR(128) NOT NULL DEFAULT '',
    issuer_level VARCHAR(16) NOT NULL DEFAULT 'university',
    audience VARCHAR(128) NOT NULL DEFAULT '',
    source_url VARCHAR(1024) NOT NULL DEFAULT '',
    published_at DATE NULL,
    effective_at DATE NULL,
    content_text MEDIUMTEXT NOT NULL,
    content_fingerprint CHAR(64) NOT NULL,
    original_file_path VARCHAR(1024) NOT NULL DEFAULT '',
    page_map_json JSON NULL,
    file_sha256 CHAR(64) NOT NULL DEFAULT '',
    normalized_title VARCHAR(255) NOT NULL DEFAULT '',
    status VARCHAR(32) NOT NULL DEFAULT 'active',
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uk_knowloom_doc_version (scope_hash, doc_key, version_no),
    INDEX idx_knowloom_doc_key_status (scope_hash, doc_key, status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS knowloom_blocks (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    document_id BIGINT NOT NULL,
    block_index INT NOT NULL,
    heading VARCHAR(255) NOT NULL DEFAULT '',
    anchor_entity VARCHAR(255) NOT NULL DEFAULT '',
    l1_text MEDIUMTEXT NOT NULL,
    split_reason VARCHAR(32) NOT NULL DEFAULT '',
    parent_block_index INT NULL,
    chunk_index INT NOT NULL DEFAULT 0,
    chunk_count INT NOT NULL DEFAULT 1,
    text_fingerprint CHAR(64) NOT NULL,
    UNIQUE KEY uk_knowloom_block (document_id, block_index),
    CONSTRAINT fk_knowloom_block_document
        FOREIGN KEY (document_id) REFERENCES knowloom_documents(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS knowloom_ingest_jobs (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    workspace_id VARCHAR(128) NOT NULL DEFAULT 'local',
    project_id VARCHAR(128) NOT NULL DEFAULT 'knowloom',
    collection_id VARCHAR(128) NOT NULL DEFAULT 'default',
    domain VARCHAR(128) NOT NULL DEFAULT 'general',
    source_note_id VARCHAR(128) NOT NULL DEFAULT '',
    document_id BIGINT NULL,
    task_name VARCHAR(255) NOT NULL DEFAULT '',
    input_fingerprint CHAR(64) NOT NULL,
    input_text MEDIUMTEXT NOT NULL,
    preprocess_json JSON NOT NULL,
    block_count INT NOT NULL DEFAULT 0,
    entity_count INT NOT NULL DEFAULT 0,
    queued_count INT NOT NULL DEFAULT 0,
    status VARCHAR(32) NOT NULL DEFAULT 'queued',
    swept_at TIMESTAMP NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_knowloom_ingest_jobs_scope (workspace_id, project_id, collection_id, domain),
    INDEX idx_knowloom_ingest_jobs_status (status),
    INDEX idx_knowloom_ingest_jobs_fingerprint (input_fingerprint)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS knowloom_incoming_entities (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    job_id BIGINT NOT NULL,
    workspace_id VARCHAR(128) NOT NULL DEFAULT 'local',
    project_id VARCHAR(128) NOT NULL DEFAULT 'knowloom',
    collection_id VARCHAR(128) NOT NULL DEFAULT 'default',
    domain VARCHAR(128) NOT NULL DEFAULT 'general',
    dedupe_key CHAR(64) NOT NULL,
    name VARCHAR(255) NOT NULL,
    normalized_name VARCHAR(255) NOT NULL,
    entity_type VARCHAR(64) NOT NULL DEFAULT 'concept',
    aliases_json JSON NOT NULL,
    identity_description TEXT NOT NULL,
    identity_source VARCHAR(16) NOT NULL DEFAULT 'model_prior',
    identity_user_text TEXT NULL,
    description_for_match TEXT NOT NULL,
    attributes_json JSON NOT NULL,
    relations_json JSON NULL,
    source_blocks_json JSON NOT NULL,
    source_count INT NOT NULL DEFAULT 1,
    status VARCHAR(32) NOT NULL DEFAULT 'pending',
    attempt_count INT NOT NULL DEFAULT 0,
    matched_entity_id BIGINT NULL,
    decision VARCHAR(32) NOT NULL DEFAULT '',
    decision_score DOUBLE NOT NULL DEFAULT 0,
    decision_reason TEXT NOT NULL,
    last_error TEXT NOT NULL,
    locked_by VARCHAR(128) NOT NULL DEFAULT '',
    locked_until TIMESTAMP NULL DEFAULT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_knowloom_incoming_entity_dedupe (dedupe_key),
    INDEX idx_knowloom_incoming_entities_job (job_id),
    INDEX idx_knowloom_incoming_entities_scope (workspace_id, project_id, collection_id, domain),
    INDEX idx_knowloom_incoming_entities_status (status),
    INDEX idx_knowloom_incoming_entities_name (normalized_name),
    CONSTRAINT fk_knowloom_incoming_entities_job
        FOREIGN KEY (job_id) REFERENCES knowloom_ingest_jobs(id)
        ON DELETE CASCADE,
    CONSTRAINT fk_knowloom_incoming_entities_matched_entity
        FOREIGN KEY (matched_entity_id) REFERENCES knowloom_entities(id)
        ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS knowloom_entity_extraction_failures (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    job_id BIGINT NOT NULL,
    workspace_id VARCHAR(128) NOT NULL DEFAULT 'local',
    project_id VARCHAR(128) NOT NULL DEFAULT 'knowloom',
    collection_id VARCHAR(128) NOT NULL DEFAULT 'default',
    domain VARCHAR(128) NOT NULL DEFAULT 'general',
    source_note_id VARCHAR(128) NOT NULL DEFAULT '',
    block_index INT NOT NULL DEFAULT -1,
    heading VARCHAR(255) NOT NULL DEFAULT '',
    anchor_entity VARCHAR(255) NOT NULL DEFAULT '',
    l1_text MEDIUMTEXT NOT NULL,
    error TEXT NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'pending',
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_knowloom_extraction_failures_job (job_id),
    INDEX idx_knowloom_extraction_failures_status (status),
    INDEX idx_knowloom_extraction_failures_scope (workspace_id, project_id, collection_id, domain),
    CONSTRAINT fk_knowloom_extraction_failures_job
        FOREIGN KEY (job_id) REFERENCES knowloom_ingest_jobs(id)
        ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS knowloom_entity_review_tasks (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    incoming_entity_id BIGINT NOT NULL,
    job_id BIGINT NOT NULL,
    workspace_id VARCHAR(128) NOT NULL DEFAULT 'local',
    project_id VARCHAR(128) NOT NULL DEFAULT 'knowloom',
    collection_id VARCHAR(128) NOT NULL DEFAULT 'default',
    domain VARCHAR(128) NOT NULL DEFAULT 'general',
    incoming_snapshot_json JSON NOT NULL,
    candidates_json JSON NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'pending',
    decision VARCHAR(32) NOT NULL DEFAULT '',
    decided_entity_id BIGINT NULL,
    decided_by VARCHAR(128) NOT NULL DEFAULT '',
    reason TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_knowloom_review_incoming_status (incoming_entity_id, status),
    INDEX idx_knowloom_review_scope (workspace_id, project_id, collection_id, domain),
    INDEX idx_knowloom_review_status (status),
    INDEX idx_knowloom_review_job (job_id),
    CONSTRAINT fk_knowloom_review_incoming
        FOREIGN KEY (incoming_entity_id) REFERENCES knowloom_incoming_entities(id)
        ON DELETE CASCADE,
    CONSTRAINT fk_knowloom_review_decided_entity
        FOREIGN KEY (decided_entity_id) REFERENCES knowloom_entities(id)
        ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS knowloom_entity_resolution_rejections (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    workspace_id VARCHAR(128) NOT NULL DEFAULT 'local',
    project_id VARCHAR(128) NOT NULL DEFAULT 'knowloom',
    collection_id VARCHAR(128) NOT NULL DEFAULT 'default',
    domain VARCHAR(128) NOT NULL DEFAULT 'general',
    scope_hash CHAR(40) NOT NULL,
    incoming_normalized_name VARCHAR(255) NOT NULL,
    incoming_type VARCHAR(64) NOT NULL DEFAULT '',
    candidate_entity_id BIGINT NOT NULL,
    reason TEXT NOT NULL,
    decided_by VARCHAR(128) NOT NULL DEFAULT '',
    status VARCHAR(32) NOT NULL DEFAULT 'active',
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_knowloom_rejection_pair (
        scope_hash, incoming_normalized_name, incoming_type, candidate_entity_id, status
    ),
    INDEX idx_knowloom_rejection_scope (workspace_id, project_id, collection_id, domain),
    INDEX idx_knowloom_rejection_candidate (candidate_entity_id),
    CONSTRAINT fk_knowloom_rejection_candidate
        FOREIGN KEY (candidate_entity_id) REFERENCES knowloom_entities(id)
        ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS knowloom_entity_resolution_relation_memory (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    workspace_id VARCHAR(128) NOT NULL DEFAULT 'local',
    project_id VARCHAR(128) NOT NULL DEFAULT 'knowloom',
    collection_id VARCHAR(128) NOT NULL DEFAULT 'default',
    domain VARCHAR(128) NOT NULL DEFAULT 'general',
    scope_hash CHAR(40) NOT NULL,
    left_entity_id BIGINT NULL,
    left_name VARCHAR(255) NOT NULL DEFAULT '',
    left_normalized_name VARCHAR(255) NOT NULL,
    left_type VARCHAR(64) NOT NULL DEFAULT '',
    right_entity_id BIGINT NULL,
    right_name VARCHAR(255) NOT NULL DEFAULT '',
    right_normalized_name VARCHAR(255) NOT NULL,
    right_type VARCHAR(64) NOT NULL DEFAULT '',
    decision VARCHAR(32) NOT NULL,
    relation_type VARCHAR(64) NOT NULL DEFAULT '',
    confidence DOUBLE NOT NULL DEFAULT 1.0,
    hit_count BIGINT NOT NULL DEFAULT 0,
    source VARCHAR(64) NOT NULL DEFAULT 'manual',
    reason TEXT NOT NULL,
    evidence_json JSON NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'active',
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_knowloom_relation_memory_pair (
        scope_hash, left_normalized_name, left_type, right_normalized_name, right_type, status
    ),
    INDEX idx_knowloom_relation_memory_left (scope_hash, left_normalized_name, left_type, status),
    INDEX idx_knowloom_relation_memory_right (scope_hash, right_normalized_name, right_type, status),
    INDEX idx_knowloom_relation_memory_decision (decision, status),
    INDEX idx_knowloom_relation_memory_hits (hit_count, updated_at),
    CONSTRAINT fk_knowloom_relation_memory_left_entity
        FOREIGN KEY (left_entity_id) REFERENCES knowloom_entities(id)
        ON DELETE SET NULL,
    CONSTRAINT fk_knowloom_relation_memory_right_entity
        FOREIGN KEY (right_entity_id) REFERENCES knowloom_entities(id)
        ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

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
    INDEX idx_knowloom_attr_decision_action (action),
    CONSTRAINT fk_knowloom_attr_decision_entity
        FOREIGN KEY (entity_id) REFERENCES knowloom_entities(id)
        ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

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
    INDEX idx_knowloom_attr_event_review (review_status),
    CONSTRAINT fk_knowloom_attr_event_entity
        FOREIGN KEY (entity_id) REFERENCES knowloom_entities(id)
        ON DELETE CASCADE,
    CONSTRAINT fk_knowloom_attr_event_attribute
        FOREIGN KEY (attribute_id) REFERENCES knowloom_entity_attributes(id)
        ON DELETE CASCADE,
    CONSTRAINT fk_knowloom_attr_event_correction
        FOREIGN KEY (corrected_by_event_id) REFERENCES knowloom_entity_attribute_events(id)
        ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

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
    INDEX idx_knowloom_attr_conflict_status (status),
    CONSTRAINT fk_knowloom_attr_conflict_entity
        FOREIGN KEY (entity_id) REFERENCES knowloom_entities(id)
        ON DELETE CASCADE,
    CONSTRAINT fk_knowloom_attr_conflict_attribute
        FOREIGN KEY (attribute_id) REFERENCES knowloom_entity_attributes(id)
        ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


CREATE TABLE IF NOT EXISTS knowloom_entity_identity_events (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    entity_id BIGINT NOT NULL,
    before_text TEXT NULL,
    before_source VARCHAR(16) NOT NULL DEFAULT '',
    after_text TEXT NOT NULL,
    after_source VARCHAR(16) NOT NULL,
    trigger_reason VARCHAR(64) NOT NULL,
    basis_json JSON NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_knowloom_identity_event_entity (entity_id),
    CONSTRAINT fk_knowloom_identity_event_entity FOREIGN KEY (entity_id) REFERENCES knowloom_entities(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS knowloom_document_relations (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    workspace_id VARCHAR(128) NOT NULL DEFAULT 'local', project_id VARCHAR(128) NOT NULL DEFAULT 'knowloom',
    collection_id VARCHAR(128) NOT NULL DEFAULT 'default', domain VARCHAR(128) NOT NULL DEFAULT 'general',
    source_doc_key VARCHAR(255) NOT NULL, target_doc_key VARCHAR(255) NOT NULL,
    relation_type VARCHAR(32) NOT NULL, confidence DOUBLE NOT NULL DEFAULT 1.0, source VARCHAR(32) NOT NULL DEFAULT 'manual',
    evidence_text TEXT NOT NULL, status VARCHAR(16) NOT NULL DEFAULT 'active',
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uk_knowloom_document_relation (workspace_id, project_id, collection_id, domain, source_doc_key, target_doc_key, relation_type),
    INDEX idx_knowloom_document_relation_target (target_doc_key, relation_type)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS knowloom_entity_relations (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    scope_hash CHAR(40) NOT NULL,
    source_entity_id BIGINT NOT NULL,
    target_name VARCHAR(255) NOT NULL,
    target_normalized_name VARCHAR(255) NOT NULL,
    target_entity_id BIGINT NULL,
    relation_type VARCHAR(32) NOT NULL,
    confidence DOUBLE NOT NULL DEFAULT 0.7,
    status VARCHAR(16) NOT NULL DEFAULT 'active',
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uk_knowloom_entity_relation (source_entity_id, target_normalized_name, relation_type),
    INDEX idx_knowloom_entity_relation_target (scope_hash, target_normalized_name, target_entity_id),
    INDEX idx_knowloom_entity_relation_target_entity (target_entity_id),
    CONSTRAINT fk_knowloom_relation_source FOREIGN KEY (source_entity_id) REFERENCES knowloom_entities(id) ON DELETE CASCADE,
    CONSTRAINT fk_knowloom_relation_target FOREIGN KEY (target_entity_id) REFERENCES knowloom_entities(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS knowloom_entity_relation_evidence (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    relation_id BIGINT NOT NULL,
    document_id BIGINT NULL,
    block_ref_id BIGINT NULL,
    evidence_text TEXT NOT NULL,
    evidence_fingerprint CHAR(64) NOT NULL,
    UNIQUE KEY uk_knowloom_entity_relation_evidence (relation_id, document_id, evidence_fingerprint),
    CONSTRAINT fk_knowloom_relation_evidence_relation FOREIGN KEY (relation_id) REFERENCES knowloom_entity_relations(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


CREATE TABLE IF NOT EXISTS knowloom_file_ingest_jobs (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    workspace_id VARCHAR(128) NOT NULL, project_id VARCHAR(128) NOT NULL, collection_id VARCHAR(128) NOT NULL, domain VARCHAR(128) NOT NULL,
    document_id BIGINT NOT NULL, file_name VARCHAR(255) NOT NULL, file_sha256 CHAR(64) NOT NULL, original_file_path VARCHAR(1024) NOT NULL,
    meta_json JSON NOT NULL, status VARCHAR(32) NOT NULL DEFAULT 'converting', ingest_job_id BIGINT NULL, attempt_count INT NOT NULL DEFAULT 0,
    last_error TEXT NOT NULL, created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_knowloom_file_job_status (status), INDEX idx_knowloom_file_job_sha (file_sha256),
    CONSTRAINT fk_knowloom_file_job_document FOREIGN KEY (document_id) REFERENCES knowloom_documents(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
