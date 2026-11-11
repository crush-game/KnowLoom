import asyncio
from time import perf_counter
from typing import Any

from app.knowloom.config import KnowLoomSettings, settings
from app.knowloom.llm import KnowLoomLLMClient
from app.knowloom.models import BlockExtractionFailure, KnowLoomPreprocessResult
from app.knowloom.services.block_splitter import BlockSplitter
from app.knowloom.services.entity_extractor import EntityExtractor


class KnowLoomProcessorError(RuntimeError):
    pass


class KnowLoomProcessor:
    def __init__(
        self,
        config: KnowLoomSettings = settings,
        llm_client: KnowLoomLLMClient | None = None,
        block_splitter: BlockSplitter | None = None,
        entity_extractor: EntityExtractor | None = None,
    ) -> None:
        self.config = config
        self.llm = llm_client or KnowLoomLLMClient(config)
        self.block_splitter = block_splitter or BlockSplitter(self.llm, config)
        self.entity_extractor = entity_extractor or EntityExtractor(self.llm, config)

    async def preprocess(self, text: str) -> KnowLoomPreprocessResult:
        total_started_at = perf_counter()
        timings: dict[str, float] = {}
        normalized_text = str(text or "").strip()
        if not normalized_text:
            raise KnowLoomProcessorError("input text is empty")

        try:
            before_block_split_at = perf_counter()
            timings["startup_to_first_block_split_ms"] = elapsed_ms(total_started_at)
            if hasattr(self.block_splitter, "split_with_timings"):
                blocks, split_timings = await self.block_splitter.split_with_timings(normalized_text)
                timings.update(split_timings)
            else:
                blocks = await self.block_splitter.split(normalized_text)
                timings["entity_anchor_split_ms"] = elapsed_ms(before_block_split_at)
                timings["physical_chunk_split_ms"] = 0.0
            entity_extraction_started_at = perf_counter()
            extraction_failures: list[BlockExtractionFailure] = []
            if hasattr(self.entity_extractor, "extract_many_with_failures"):
                extractions, extraction_failures = await self.entity_extractor.extract_many_with_failures(blocks)
            else:
                extractions = await self.entity_extractor.extract_many(blocks)
            timings["entity_extraction_ms"] = elapsed_ms(entity_extraction_started_at)
        except Exception as exc:
            if isinstance(exc, KnowLoomProcessorError):
                raise
            raise KnowLoomProcessorError(str(exc)) from exc

        timings["total_ms"] = elapsed_ms(total_started_at)
        return KnowLoomPreprocessResult(
            input_text=normalized_text,
            blocks=extractions,
            timings=timings,
            extraction_failures=extraction_failures,
        )


async def preprocess_text_async(text: str, *, config: KnowLoomSettings = settings) -> KnowLoomPreprocessResult:
    processor = KnowLoomProcessor(config=config)
    return await processor.preprocess(text)


def preprocess_text(text: str, *, config: KnowLoomSettings = settings) -> KnowLoomPreprocessResult:
    return asyncio.run(preprocess_text_async(text, config=config))


def result_to_dict(result: KnowLoomPreprocessResult) -> dict[str, Any]:
    return result.model_dump()


def elapsed_ms(started_at: float) -> float:
    return round((perf_counter() - started_at) * 1000, 2)
