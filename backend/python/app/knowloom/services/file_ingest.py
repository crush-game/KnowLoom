from __future__ import annotations

import asyncio
from dataclasses import fields
from pathlib import Path
from typing import Any

from app.knowloom.config import KnowLoomSettings, settings
from app.knowloom.entity_store.ingestor import EntityIngestor
from app.knowloom.entity_store.models import DocumentMetadata, EntityScope
from app.knowloom.entity_store.normalizer import apply_glossary, text_fingerprint
from app.knowloom.entity_store.repository import MySQLEntityRepository
from app.knowloom.services.document_relations import detect_document_relations
from app.knowloom.services.file_text import convert_file
from app.knowloom.services.processor import KnowLoomProcessor
from app.knowloom.services.title_normalizer import normalize_document_title


_FILE_INGEST_SEMAPHORE = asyncio.Semaphore(max(1, settings.file_ingest_max_concurrency))

async def process_file_ingest_job(job_id: int, config: KnowLoomSettings = settings) -> None:
    async with _FILE_INGEST_SEMAPHORE:
        await _process_file_ingest_job(job_id, config)

async def _process_file_ingest_job(job_id: int, config: KnowLoomSettings) -> None:
    repository = MySQLEntityRepository(config)
    job = await asyncio.to_thread(repository.get_file_ingest_job, job_id)
    if not job:
        return
    try:
        content = await asyncio.to_thread(Path(str(job["original_file_path"])).read_bytes)
        conversion = await asyncio.to_thread(convert_file, str(job["file_name"]), content)
        if len(conversion.text) > config.file_max_text_chars:
            raise ValueError(f"converted text exceeds the {config.file_max_text_chars} character limit")
        await asyncio.to_thread(repository.update_file_ingest_job, job_id, status="preprocessing")
        metadata = metadata_from_dict(job.get("meta") or {})
        metadata.original_file_path = str(job["original_file_path"])
        metadata.file_sha256 = str(job["file_sha256"])
        metadata.page_map = conversion.page_map
        metadata.normalized_title = metadata.normalized_title or normalize_document_title(metadata.title or str(job["file_name"]))
        duplicate = await asyncio.to_thread(repository.find_duplicate_converted_content, int(job["document_id"]), text_fingerprint(conversion.text))
        if duplicate:
            await asyncio.to_thread(repository.mark_file_ingest_duplicate, job_id)
            return
        scope = EntityScope(workspace_id=str(job["workspace_id"]), project_id=str(job["project_id"]), collection_id=str(job["collection_id"]), domain=str(job["domain"]))
        preprocess = await KnowLoomProcessor(config=config).preprocess(conversion.text)
        apply_glossary(preprocess.blocks, list((job.get("meta") or {}).get("glossary") or []))
        queued = await EntityIngestor(repository=repository, config=config, scope=scope).queue(preprocess, source_note_id=metadata.doc_key, task_name=f"file:{job['file_name']}", document_metadata=metadata, existing_document_id=int(job["document_id"]))
        for relation in detect_document_relations(conversion.text):
            target = await asyncio.to_thread(repository.find_document_by_title, scope=scope, title=relation.target_title)
            if target and str(target.get("doc_key") or "") != metadata.doc_key:
                await asyncio.to_thread(repository.add_document_relation, scope, source_doc_key=metadata.doc_key, target_doc_key=str(target["doc_key"]), relation_type=relation.relation_type, confidence=relation.confidence, source="rule", evidence_text=relation.evidence)
        for relation in list((job.get("meta") or {}).get("relations") or []):
            relation_type = str(relation.get("relation_type") or relation.get("type") or "")
            target_doc_key = str(relation.get("target_doc_key") or "")
            if relation_type in {"based_on", "implements", "amends", "repeals"} and target_doc_key and target_doc_key != metadata.doc_key:
                await asyncio.to_thread(repository.add_document_relation, scope, source_doc_key=metadata.doc_key, target_doc_key=target_doc_key, relation_type=relation_type, confidence=1.0, source="manual", evidence_text=str(relation.get("evidence") or ""))
                if relation_type == "repeals":
                    await asyncio.to_thread(repository.apply_document_repeal, scope, target_doc_key)
        await asyncio.to_thread(repository.update_file_ingest_job, job_id, status="queued", ingest_job_id=queued.job_id)
    except Exception as exc:
        await asyncio.to_thread(repository.update_file_ingest_job, job_id, status="failed", error=str(exc))


def metadata_from_dict(value: dict[str, Any]) -> DocumentMetadata:
    allowed = {field.name for field in fields(DocumentMetadata)}
    return DocumentMetadata(**{key: item for key, item in value.items() if key in allowed})


def recover_file_ingest_jobs(config: KnowLoomSettings = settings) -> int:
    return MySQLEntityRepository(config).recover_interrupted_file_jobs()
