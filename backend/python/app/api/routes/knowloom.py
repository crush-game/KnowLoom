import asyncio
from hashlib import sha256
from pathlib import Path
from dataclasses import asdict

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Query, UploadFile, status
from pydantic import BaseModel, Field

from app.knowloom.constants import attribute_schema_payload
from app.knowloom.entity_store.ingestor import EntityIngestor
from app.knowloom.entity_store.models import DocumentMetadata, EntityScope
from app.knowloom.entity_store.repository import MySQLEntityRepository
from app.knowloom.entity_store.worker import entity_worker_runtime_status
from app.knowloom.entity_store.normalizer import apply_glossary, text_fingerprint
from app.knowloom.models import KnowLoomIndexSearchResult, KnowLoomPreprocessResult, KnowLoomQueryResult
from app.knowloom.services import KnowLoomProcessor, KnowLoomQueryService, KnowLoomRetriever
from app.knowloom.services.ask import KnowLoomAskService
from app.knowloom.services.file_text import FileTooLarge, ScannedPdf, convert_file, persist_original_file, validate_upload
from app.knowloom.services.graph_generation import KnowLoomGraphGenerationService
from app.knowloom.services.pipeline_debug import extraction_stage_payload, run_debug_pipeline
from app.knowloom.services.doc_meta import suggest_effective_at
from app.knowloom.services.document_relations import detect_document_relations
from app.knowloom.services.title_normalizer import normalize_document_title
from app.knowloom.services.file_ingest import process_file_ingest_job
from app.core.security import require_auth


router = APIRouter(prefix="/knowloom", tags=["knowloom"], dependencies=[Depends(require_auth)])


class KnowLoomScopePayload(BaseModel):
    workspace_id: str = "local"
    project_id: str = "knowloom"
    collection_id: str = "default"
    domain: str = "general"


class GlossaryItem(BaseModel):
    name: str = Field(..., min_length=1)
    aliases: list[str] = Field(default_factory=list)
    definition: str = Field(..., min_length=1, max_length=1000)


class KnowLoomFileCheckRequest(BaseModel):
    file_sha256: str = Field(..., min_length=64, max_length=64)
    file_name: str
    title: str = ""
    scope: KnowLoomScopePayload = Field(default_factory=KnowLoomScopePayload)

class KnowLoomFileMeta(BaseModel):
    doc_key: str = ""
    title: str = ""
    doc_number: str = ""
    doc_kind: str = Field(default="regulation", pattern="^(regulation|amendment|notice|guide|other)$")
    issuer: str = ""
    issuer_level: str = Field(default="university", pattern="^(national|university|department)$")
    audience: str = ""
    source_url: str = ""
    published_at: str = ""
    effective_at: str = ""
    glossary: list[GlossaryItem] = Field(default_factory=list)
    relations: list[dict[str, object]] = Field(default_factory=list)
    scope: KnowLoomScopePayload = Field(default_factory=KnowLoomScopePayload)

class KnowLoomFileAccepted(BaseModel):
    job_id: int
    document_id: int
    status: str
    warnings: list[str] = Field(default_factory=list)


class KnowLoomIngestRequest(BaseModel):
    text: str = Field(..., min_length=1)
    note_id: str = ""
    task_name: str = ""
    title: str = ""
    doc_number: str = ""
    doc_kind: str = Field(default="regulation", pattern="^(regulation|amendment|notice|guide|other)$")
    issuer: str = ""
    issuer_level: str = Field(default="university", pattern="^(national|university|department)$")
    audience: str = ""
    source_url: str = ""
    published_at: str = ""
    effective_at: str = ""
    glossary: list[GlossaryItem] = Field(default_factory=list)
    original_file_path: str = Field(default="", exclude=True)
    page_map: list[dict[str, int]] = Field(default_factory=list, exclude=True)
    file_sha256: str = Field(default="", exclude=True)
    scope: KnowLoomScopePayload = Field(default_factory=KnowLoomScopePayload)


class KnowLoomAskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=500)
    top_k_entities: int = Field(default=3, ge=1, le=10)
    top_k_blocks: int = Field(default=8, ge=1, le=20)
    include_history: bool = False
    scope: KnowLoomScopePayload = Field(default_factory=KnowLoomScopePayload)


class KnowLoomQueryRequest(BaseModel):
    entity: str = Field(..., min_length=1)
    top_k: int = Field(default=5, ge=1, le=20)
    scope: KnowLoomScopePayload = Field(default_factory=KnowLoomScopePayload)


class KnowLoomGraphGenerateRequest(BaseModel):
    root_entity_id: int = Field(..., ge=1)
    selected_entity_ids: list[int] = Field(default_factory=list)
    scope: KnowLoomScopePayload = Field(default_factory=KnowLoomScopePayload)


class KnowLoomIngestResponse(BaseModel):
    preprocess: KnowLoomPreprocessResult
    job_id: int = 0
    status: str = "queued"
    queued_count: int = 0
    incoming_entity_ids: list[int] = Field(default_factory=list)
    document_id: int | None = None
    duplicate: bool = False
    effective_at_suggestion: str = ""
    ingest_results: list[dict[str, object]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    glossary_unmatched: list[str] = Field(default_factory=list)


class KnowLoomReviewTaskListResponse(BaseModel):
    tasks: list[dict[str, object]] = Field(default_factory=list)


class KnowLoomIngestJobListResponse(BaseModel):
    jobs: list[dict[str, object]] = Field(default_factory=list)


class KnowLoomReviewMergeRequest(BaseModel):
    entity_id: int = Field(..., ge=1)
    reason: str = ""
    decided_by: str = "manual"


class KnowLoomReviewActionRequest(BaseModel):
    reason: str = ""
    decided_by: str = "manual"


class KnowLoomReviewRejectRequest(KnowLoomReviewActionRequest):
    candidate_entity_ids: list[int] = Field(default_factory=list)


@router.get("/attribute-schema")
async def get_attribute_schema() -> dict[str, object]:
    return attribute_schema_payload()


@router.post("/extract", response_model=KnowLoomPreprocessResult)
async def extract_text(request: KnowLoomIngestRequest) -> KnowLoomPreprocessResult:
    try:
        return await KnowLoomProcessor().preprocess(request.text)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc


@router.post("/debug/extract")
async def debug_extract_text(request: KnowLoomIngestRequest) -> dict[str, object]:
    try:
        preprocess = await KnowLoomProcessor().preprocess(request.text)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc

    return debug_extract_payload(preprocess)


@router.post("/debug/pipeline")
async def debug_pipeline(request: KnowLoomIngestRequest) -> dict[str, object]:
    scope = to_scope(request.scope)
    try:
        return await run_debug_pipeline(
            request.text,
            scope=scope,
            source_note_id=request.note_id,
            task_name=request.task_name or "pipeline-debug",
        )
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc


def debug_extract_payload(preprocess: KnowLoomPreprocessResult) -> dict[str, object]:
    payload = extraction_stage_payload(preprocess)
    return {
        "input_text": payload["input_text"],
        "block_split": payload["block_split"],
        "entity_extraction": payload["entity_extraction"],
        "timings": payload["timings"],
    }


@router.post("/ingest/file/check")
async def check_ingest_file(payload: KnowLoomFileCheckRequest) -> dict[str, object]:
    scope = to_scope(payload.scope)
    normalized_title = normalize_document_title(payload.title or payload.file_name)
    return await asyncio.to_thread(MySQLEntityRepository().check_file_upload, scope=scope, file_sha256=payload.file_sha256.lower(), normalized_title=normalized_title)


@router.post("/ingest/file", status_code=status.HTTP_202_ACCEPTED, response_model=KnowLoomFileAccepted)
async def ingest_file_async(background_tasks: BackgroundTasks, file: UploadFile = File(...), meta: str = Form("{}")) -> KnowLoomFileAccepted:
    try:
        payload = KnowLoomFileMeta.model_validate_json(meta)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"invalid file metadata: {exc}") from exc
    content = await file.read(20 * 1024 * 1024 + 1)
    try:
        await asyncio.to_thread(validate_upload, file.filename or "", content)
    except FileTooLarge as exc:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail=str(exc)) from exc
    except ScannedPdf as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    digest = sha256(content).hexdigest()
    scope = to_scope(payload.scope)
    repository = MySQLEntityRepository()
    check = await asyncio.to_thread(repository.check_file_upload, scope=scope, file_sha256=digest, normalized_title=normalize_document_title(payload.title or (file.filename or "")))
    if check.get("duplicate_of"):
        duplicate = check["duplicate_of"]
        return KnowLoomFileAccepted(job_id=0, document_id=int(duplicate["id"]), status="duplicate")
    original_path = await asyncio.to_thread(persist_original_file, file.filename or "", content)
    title = payload.title or Path(file.filename or "upload").stem
    metadata = DocumentMetadata(doc_key=payload.doc_key or digest, title=title, doc_number=payload.doc_number, doc_kind=payload.doc_kind, issuer=payload.issuer, issuer_level=payload.issuer_level, audience=payload.audience, source_url=payload.source_url, published_at=payload.published_at, effective_at=payload.effective_at, original_file_path=original_path, file_sha256=digest, normalized_title=normalize_document_title(title))
    created = await asyncio.to_thread(repository.create_file_ingest_job, scope=scope, file_name=file.filename or "upload", file_sha256=digest, original_file_path=original_path, metadata=metadata, extra_meta={"glossary":[item.model_dump() for item in payload.glossary], "relations":payload.relations})
    background_tasks.add_task(process_file_ingest_job, int(created["job_id"]))
    return KnowLoomFileAccepted(**created)


@router.get("/ingest/file-jobs/{job_id}")
async def get_file_ingest_job(job_id: int) -> dict[str, object]:
    job = await asyncio.to_thread(MySQLEntityRepository().get_file_ingest_job, job_id)
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="file ingest job not found")
    job.pop("meta_json", None)
    return job


@router.post("/ingest-jobs/{job_id}/retry", status_code=status.HTTP_202_ACCEPTED)
async def retry_file_ingest_job(job_id: int, background_tasks: BackgroundTasks) -> dict[str, object]:
    repository = MySQLEntityRepository()
    changed = await asyncio.to_thread(repository.claim_file_ingest_retry, job_id)
    if not changed:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="file job is not retryable")
    background_tasks.add_task(process_file_ingest_job, job_id)
    return {"job_id": job_id, "status": "converting"}


@router.post("/upload", response_model=KnowLoomIngestResponse)
async def upload_file(file: UploadFile = File(...), task_name: str = "", title: str = "", doc_key: str = "", doc_number: str = "", doc_kind: str = "regulation", issuer: str = "", issuer_level: str = "university", audience: str = "", published_at: str = "", effective_at: str = "") -> KnowLoomIngestResponse:
    content = await file.read(20 * 1024 * 1024 + 1)
    try:
        conversion = await asyncio.to_thread(convert_file, file.filename or "", content)
        original_path = await asyncio.to_thread(persist_original_file, file.filename or "", content)
    except FileTooLarge as exc:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail=str(exc)) from exc
    except ScannedPdf as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return await ingest_text(KnowLoomIngestRequest(text=conversion.text, note_id=doc_key, task_name=task_name, title=title or (file.filename or ""), doc_number=doc_number, doc_kind=doc_kind, issuer=issuer, issuer_level=issuer_level, audience=audience, published_at=published_at, effective_at=effective_at, original_file_path=original_path, page_map=conversion.page_map, file_sha256=__import__("hashlib").sha256(content).hexdigest()))

@router.post("/ingest", response_model=KnowLoomIngestResponse)
async def ingest_text(request: KnowLoomIngestRequest) -> KnowLoomIngestResponse:
    scope = to_scope(request.scope)
    metadata = document_metadata_from_request(request)
    repository = MySQLEntityRepository()
    suggestion = "" if request.effective_at else suggest_effective_at(request.text)
    try:
        duplicate = await asyncio.to_thread(
            repository.find_duplicate_document,
            scope=scope,
            doc_key=metadata.doc_key,
            content_fingerprint=text_fingerprint(request.text),
        )
        if duplicate:
            return KnowLoomIngestResponse(
                preprocess=KnowLoomPreprocessResult(input_text=request.text),
                job_id=0,
                status="duplicate",
                queued_count=0,
                document_id=int(duplicate["id"]),
                duplicate=True,
                effective_at_suggestion=suggestion,
            )
        preprocess = await KnowLoomProcessor().preprocess(request.text)
        glossary_unmatched = apply_glossary(preprocess.blocks, [item.model_dump() for item in request.glossary])
        queue_result = await EntityIngestor(scope=scope).queue(
            preprocess,
            source_note_id=request.note_id,
            task_name=request.task_name,
            document_metadata=metadata,
        )
        for relation in detect_document_relations(request.text):
            target = await asyncio.to_thread(repository.find_document_by_title, scope=scope, title=relation.target_title)
            if target and str(target.get("doc_key") or "") != metadata.doc_key:
                await asyncio.to_thread(repository.add_document_relation, scope, source_doc_key=metadata.doc_key, target_doc_key=str(target["doc_key"]), relation_type=relation.relation_type, confidence=relation.confidence, source="rule", evidence_text=relation.evidence)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc

    return KnowLoomIngestResponse(
        preprocess=preprocess,
        job_id=queue_result.job_id,
        status=queue_result.status,
        queued_count=queue_result.queued_count,
        incoming_entity_ids=queue_result.incoming_entity_ids,
        document_id=queue_result.document_id,
        duplicate=queue_result.duplicate,
        effective_at_suggestion=suggestion,
        glossary_unmatched=glossary_unmatched,
    )


@router.get("/blocks/{block_id}")
async def get_block(block_id: int, context: bool = True) -> dict[str, object]:
    try:
        block = await asyncio.to_thread(MySQLEntityRepository().get_block_with_context, block_id, context=context)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc
    if block is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="block not found")
    return block


@router.get("/documents/{doc_key}/versions")
async def get_document_versions(
    doc_key: str,
    workspace_id: str = "local",
    project_id: str = "knowloom",
    collection_id: str = "default",
    domain: str = "general",
) -> dict[str, object]:
    scope = EntityScope(workspace_id=workspace_id, project_id=project_id, collection_id=collection_id, domain=domain)
    try:
        versions = await asyncio.to_thread(MySQLEntityRepository().list_document_versions, scope=scope, doc_key=doc_key)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc
    return {"doc_key": doc_key, "versions": versions}


@router.post("/ask")
async def ask_question(request: KnowLoomAskRequest) -> dict[str, object]:
    try:
        return asdict(await KnowLoomAskService(scope=to_scope(request.scope)).ask(request.question, top_k_entities=request.top_k_entities, top_k_blocks=request.top_k_blocks, include_history=request.include_history))
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc


@router.post("/query", response_model=KnowLoomQueryResult)
async def query_entity(request: KnowLoomQueryRequest) -> KnowLoomQueryResult:
    try:
        return await KnowLoomQueryService(scope=to_scope(request.scope)).query(request.entity, top_k=request.top_k)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc


@router.post("/index-search", response_model=KnowLoomIndexSearchResult)
async def search_entity_indexes(request: KnowLoomQueryRequest) -> KnowLoomIndexSearchResult:
    try:
        return await KnowLoomRetriever(scope=to_scope(request.scope)).search_indexes(request.entity, top_k=request.top_k)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc


@router.post("/graph/candidates")
async def graph_candidates(request: KnowLoomQueryRequest) -> dict[str, object]:
    try:
        return await KnowLoomGraphGenerationService(scope=to_scope(request.scope)).candidates(request.entity, top_k=request.top_k)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc


@router.post("/graph/generate")
async def graph_generate(request: KnowLoomGraphGenerateRequest) -> dict[str, object]:
    try:
        return await KnowLoomGraphGenerationService(scope=to_scope(request.scope)).generate(
            root_entity_id=request.root_entity_id,
            selected_entity_ids=request.selected_entity_ids,
        )
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc


@router.get("/ingest-jobs", response_model=KnowLoomIngestJobListResponse)
async def list_ingest_jobs(limit: int = 20) -> KnowLoomIngestJobListResponse:
    repository = MySQLEntityRepository()
    try:
        jobs = await asyncio.to_thread(repository.list_ingest_jobs, limit=limit)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc
    return KnowLoomIngestJobListResponse(jobs=jobs)


@router.get("/ingest-jobs/{job_id}")
async def get_ingest_job(job_id: int) -> dict[str, object]:
    repository = MySQLEntityRepository()
    try:
        job = await asyncio.to_thread(repository.get_ingest_job_status, job_id)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="ingest job not found")
    return job


@router.get("/worker-status")
async def get_worker_status() -> dict[str, object]:
    repository = MySQLEntityRepository()
    response: dict[str, object] = {
        "worker": entity_worker_runtime_status(),
        "queue": {"available": False, "backend": "mysql"},
        "mysql": {},
        "warnings": [],
    }
    try:
        response["mysql"] = await asyncio.to_thread(repository.ingest_observability_summary)
    except Exception as exc:
        response["warnings"].append(f"mysql summary unavailable: {exc}")  # type: ignore[index]
    return response


@router.get("/attribute-conflicts")
async def list_attribute_conflicts(status_filter: str = Query("pending", alias="status"), entity_id: int | None = None, limit: int = 50) -> dict[str, object]:
    conflicts = await asyncio.to_thread(MySQLEntityRepository().list_attribute_conflicts, status=status_filter, entity_id=entity_id, limit=limit)
    return {"conflicts": conflicts}


class DocumentRelationRequest(BaseModel):
    source_doc_key: str = Field(..., min_length=1)
    target_doc_key: str = Field(..., min_length=1)
    relation_type: str = Field(..., pattern="^(based_on|amends|repeals|implements)$")
    scope: KnowLoomScopePayload = Field(default_factory=KnowLoomScopePayload)


@router.post("/document-relations")
async def add_document_relation(request: DocumentRelationRequest) -> dict[str, object]:
    repository = MySQLEntityRepository()
    scope = to_scope(request.scope)
    relation_id = await asyncio.to_thread(repository.add_document_relation, scope, source_doc_key=request.source_doc_key, target_doc_key=request.target_doc_key, relation_type=request.relation_type)
    changed_attributes = await asyncio.to_thread(repository.apply_document_repeal, scope, request.target_doc_key) if request.relation_type == "repeals" else []
    return {"id": relation_id, "status": "active", "relation_type": request.relation_type, "changed_attribute_ids": changed_attributes}


@router.get("/documents/{doc_key}/relations")
async def list_document_relations(doc_key: str, workspace_id: str = "local", project_id: str = "knowloom", collection_id: str = "default", domain: str = "general") -> dict[str, object]:
    scope = EntityScope(workspace_id=workspace_id, project_id=project_id, collection_id=collection_id, domain=domain)
    relations = await asyncio.to_thread(MySQLEntityRepository().list_document_relations, scope, doc_key=doc_key)
    return {"doc_key": doc_key, "relations": relations}


@router.post("/document-relations/{relation_id}/confirm")
async def confirm_document_relation(relation_id: int) -> dict[str, object]:
    repository = MySQLEntityRepository()
    relation = await asyncio.to_thread(repository.resolve_document_relation, relation_id, decision="confirm")
    if not relation:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="relation is not pending")
    changed: list[int] = []
    if str(relation.get("relation_type")) == "repeals":
        scope = EntityScope(workspace_id=str(relation["workspace_id"]), project_id=str(relation["project_id"]), collection_id=str(relation["collection_id"]), domain=str(relation["domain"]))
        changed = await asyncio.to_thread(repository.apply_document_repeal, scope, str(relation["target_doc_key"]))
    return {"id": relation_id, "status": "active", "changed_attribute_ids": changed}


@router.post("/document-relations/{relation_id}/reject")
async def reject_document_relation(relation_id: int) -> dict[str, object]:
    relation = await asyncio.to_thread(MySQLEntityRepository().resolve_document_relation, relation_id, decision="reject")
    if not relation:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="relation is not pending")
    return {"id": relation_id, "status": "rejected"}


class EntityIdentityUpdateRequest(BaseModel):
    definition: str = Field(..., min_length=1, max_length=1000)


@router.put("/entities/{entity_id}/identity")
async def update_entity_identity(entity_id: int, request: EntityIdentityUpdateRequest) -> dict[str, object]:
    from app.knowloom.entity_store.identity_writer import build_user_identity
    draft = build_user_identity(request.definition)
    changed = await asyncio.to_thread(MySQLEntityRepository().update_identity, entity_id, text=draft.text, source=draft.source, trigger_reason=draft.trigger_reason, user_text=draft.user_text)
    if not changed:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="entity not found or identity is protected")
    return {"id": entity_id, "identity_description": draft.text, "identity_source": "user"}


class AttributeConflictResolutionRequest(BaseModel):
    resolution: str
    decided_by: str = "manual"


@router.post("/attribute-conflicts/{conflict_id}/resolve")
async def resolve_attribute_conflict(conflict_id: int, request: AttributeConflictResolutionRequest) -> dict[str, object]:
    changed = await asyncio.to_thread(MySQLEntityRepository().resolve_attribute_conflict, conflict_id, resolution=request.resolution, decided_by=request.decided_by)
    if not changed:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="conflict is no longer pending")
    return {"id": conflict_id, "status": "resolved", "resolution": request.resolution}


class AttributeEventRevertRequest(BaseModel):
    decided_by: str = "manual"


@router.post("/attribute-events/{event_id}/revert")
async def revert_attribute_event(event_id: int, request: AttributeEventRevertRequest) -> dict[str, object]:
    try:
        result = await asyncio.to_thread(MySQLEntityRepository().revert_attribute_event, event_id, decided_by=request.decided_by)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="event is not revertible or was already reverted")
    await EntityIngestor().sync_attribute_indexes(list(result.get("changed_attribute_ids") or []))
    return result


@router.get("/review-tasks", response_model=KnowLoomReviewTaskListResponse)
async def list_review_tasks(status_filter: str = Query("pending", alias="status"), limit: int = 50) -> KnowLoomReviewTaskListResponse:
    ingestor = EntityIngestor()
    try:
        tasks = await asyncio.to_thread(ingestor.repository.list_review_tasks, status=status_filter, limit=limit)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc
    return KnowLoomReviewTaskListResponse(tasks=tasks)


@router.get("/review-tasks/{review_task_id}")
async def get_review_task(review_task_id: int) -> dict[str, object]:
    ingestor = EntityIngestor()
    try:
        task = await asyncio.to_thread(ingestor.repository.get_review_task, review_task_id)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="review task not found")
    return task


@router.post("/review-tasks/{review_task_id}/merge")
async def merge_review_task(review_task_id: int, request: KnowLoomReviewMergeRequest) -> dict[str, object]:
    try:
        result = await EntityIngestor().manual_merge_review_task(
            review_task_id,
            entity_id=request.entity_id,
            reason=request.reason,
            decided_by=request.decided_by,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc
    return {"status": "merged", "result": asdict(result)}


@router.post("/review-tasks/{review_task_id}/new")
async def create_new_from_review_task(review_task_id: int, request: KnowLoomReviewActionRequest) -> dict[str, object]:
    try:
        result = await EntityIngestor().manual_create_new_review_task(
            review_task_id,
            reason=request.reason,
            decided_by=request.decided_by,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc
    return {"status": "new_created", "result": asdict(result)}


@router.post("/review-tasks/{review_task_id}/reject")
async def reject_review_task_candidates(review_task_id: int, request: KnowLoomReviewRejectRequest) -> dict[str, object]:
    try:
        result = await EntityIngestor().reject_review_candidates(
            review_task_id,
            candidate_entity_ids=request.candidate_entity_ids,
            reason=request.reason,
            decided_by=request.decided_by,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc
    return result


def to_scope(payload: KnowLoomScopePayload) -> EntityScope:
    return EntityScope(
        workspace_id=payload.workspace_id,
        project_id=payload.project_id,
        collection_id=payload.collection_id,
        domain=payload.domain,
    )


def document_metadata_from_request(request: KnowLoomIngestRequest) -> DocumentMetadata:
    return DocumentMetadata(
        doc_key=str(request.note_id or text_fingerprint(request.text)),
        title=request.title,
        doc_number=request.doc_number,
        doc_kind=request.doc_kind,
        issuer=request.issuer,
        issuer_level=request.issuer_level,
        audience=request.audience,
        source_url=request.source_url,
        published_at=request.published_at,
        effective_at=request.effective_at,
        original_file_path=request.original_file_path,
        page_map=request.page_map,
        file_sha256=request.file_sha256,
        normalized_title=normalize_document_title(request.title),
    )
