import asyncio
from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.knowloom.entity_store.ingestor import EntityIngestor
from app.knowloom.entity_store.models import DocumentMetadata, EntityScope
from app.knowloom.entity_store.repository import MySQLEntityRepository
from app.knowloom.entity_store.worker import entity_worker_runtime_status
from app.knowloom.entity_store.normalizer import text_fingerprint
from app.knowloom.models import KnowLoomIndexSearchResult, KnowLoomPreprocessResult, KnowLoomQueryResult
from app.knowloom.services import KnowLoomProcessor, KnowLoomQueryService, KnowLoomRetriever
from app.knowloom.services.graph_generation import KnowLoomGraphGenerationService
from app.knowloom.services.pipeline_debug import extraction_stage_payload, run_debug_pipeline
from app.knowloom.services.doc_meta import suggest_effective_at
from app.core.security import require_auth


router = APIRouter(prefix="/knowloom", tags=["knowloom"], dependencies=[Depends(require_auth)])


class KnowLoomScopePayload(BaseModel):
    workspace_id: str = "local"
    project_id: str = "knowloom"
    collection_id: str = "default"
    domain: str = "general"


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
        queue_result = await EntityIngestor(scope=scope).queue(
            preprocess,
            source_note_id=request.note_id,
            task_name=request.task_name,
            document_metadata=metadata,
        )
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
    )
