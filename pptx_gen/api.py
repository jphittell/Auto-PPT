"""FastAPI app for local web testing of Auto-PPT."""

from __future__ import annotations

import asyncio
import base64
import copy
import hashlib
import json
import logging
import mimetypes
import re
import shutil
from collections import Counter, OrderedDict
from datetime import datetime, timedelta, timezone
from time import perf_counter
from threading import RLock
from pathlib import Path
from typing import Any, AsyncIterator
from urllib.parse import urlparse
from uuid import uuid4

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

import pptx_gen.pipeline as pipeline_module
from pptx_gen.api_schemas import (
    BrandKitRequest,
    ChatGenerateResponse,
    ChatMessageResponse,
    ExportBlockRequest,
    ExportRequest,
    ExportSlideRequest,
    GenerateDeckRequest,
    GenerationJobAcceptedResponse,
    GenerationJobStatusResponse,
    HealthDependencyResponse,
    HealthResponse,
    IngestResponse,
    OutlineSlideRequest,
    PlanDeckRequest,
    PlanPromptRequest,
    PlanDeckResponse,
    PresentationSpecResponse,
    SlidePreviewRequest,
    SlideSpecResponse,
    TemplateResponse,
    ThemeSummaryResponse,
)
from pptx_gen.ingestion.schemas import ChunkRecord, ContentClassification, ContentElementType
from pptx_gen.indexing.vector_store import InMemoryVectorStore
from pptx_gen.observability import REQUEST_ID_HEADER, ApiKeyMiddleware, RequestIDMiddleware, configure_logging, current_request_id
from pptx_gen.settings import SETTINGS
from pptx_gen.store import DraftState, StoredDeck, create_store
from pptx_gen.layout.schemas import StyleTokens
from pptx_gen.layout.templates import TEMPLATE_ALIASES, TEMPLATE_REGISTRY, canonical_template_key, list_template_keys
from pptx_gen.planning.prompt_chain import (
    MIN_RETRIEVAL_SCORE,
    build_retrieval_plan,
    collect_deck_brief,
    execute_retrieval_plan,
    generate_outline,
    generate_presentation_spec,
    remediate_low_quality_slides,
)
from pptx_gen.planning.llm_client import build_default_structured_llm_client
from pptx_gen.planning.schemas import (
    DeckBrief,
    DeckTheme,
    LayoutIntent,
    OutlineItem,
    OutlineSpec,
    PresentationBlock,
    PresentationBlockKind,
    PresentationSpec,
    RetrievedChunk,
    SlideArchetype,
    SlidePurpose,
    SlideSpec,
    SourceCitation,
)
from pptx_gen.renderer.markdown_strip import strip_markdown


configure_logging()
_INGEST_LOGGER = logging.getLogger("pptx_gen.ingest")


def _request_id_for_error(request: Request | None = None) -> str:
    request_id = current_request_id()
    if request_id:
        return request_id
    if request is not None:
        header_request_id = request.headers.get(REQUEST_ID_HEADER, '').strip()
        if header_request_id:
            return header_request_id
    return uuid4().hex[:16]


def _error_payload(*, code: str, message: str, request: Request | None = None) -> dict[str, Any]:
    return {
        'error': {
            'code': code,
            'message': message,
            'request_id': _request_id_for_error(request),
        }
    }


def _error_response(
    *,
    status_code: int,
    code: str,
    message: str,
    request: Request | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    response = JSONResponse(
        status_code=status_code,
        content=_error_payload(code=code, message=message, request=request),
    )
    response.headers[REQUEST_ID_HEADER] = _request_id_for_error(request)
    if headers:
        for key, value in headers.items():
            response.headers[key] = value
    return response


def _raise_api_error(status_code: int, code: str, message: str) -> None:
    raise HTTPException(status_code=status_code, detail={'code': code, 'message': message})


def _default_error_code(status_code: int) -> str:
    return {
        400: 'bad_request',
        404: 'not_found',
        413: 'payload_too_large',
        422: 'invalid_request',
        429: 'rate_limit_exceeded',
        500: 'internal_error',
        503: 'service_unavailable',
    }.get(status_code, 'request_error')


def _extract_error_detail(detail: Any, *, status_code: int) -> tuple[str, str]:
    if isinstance(detail, dict):
        error_detail = detail.get('error') if isinstance(detail.get('error'), dict) else detail
        code = str(error_detail.get('code') or _default_error_code(status_code))
        message = str(error_detail.get('message') or detail.get('detail') or 'Request failed.')
        return code, message
    if isinstance(detail, str) and detail.strip():
        return _default_error_code(status_code), detail
    return _default_error_code(status_code), 'Request failed.'


async def _http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    code, message = _extract_error_detail(exc.detail, status_code=exc.status_code)
    headers = dict(exc.headers or {})
    return _error_response(
        status_code=exc.status_code,
        code=code,
        message=message,
        request=request,
        headers=headers,
    )


async def _validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    first_error = exc.errors()[0] if exc.errors() else {}
    location = '.'.join(str(part) for part in first_error.get('loc', []) if part != 'body')
    message = 'Invalid request payload.'
    detail = str(first_error.get('msg') or '').strip()
    if location and detail:
        message = f'Invalid request payload for {location}: {detail}'
    elif detail:
        message = f'Invalid request payload: {detail}'
    return _error_response(
        status_code=422,
        code='invalid_request',
        message=message,
        request=request,
    )


async def _rate_limit_exception_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    message = str(exc.detail or RATE_LIMIT_ERROR_MESSAGE)
    headers = {'Retry-After': str(getattr(exc, 'retry_after', 60))}
    return _error_response(
        status_code=429,
        code='rate_limit_exceeded',
        message=message,
        request=request,
        headers=headers,
    )


async def _unexpected_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    import logging

    logging.getLogger('pptx_gen.api').exception('unhandled api exception')
    return _error_response(
        status_code=500,
        code='internal_error',
        message='Internal server error.',
        request=request,
    )


def _rate_limit_key(request: Request) -> str:
    api_key = request.headers.get("x-api-key", "").strip()
    if api_key:
        return f"api-key:{api_key}"
    peer = request.client.host if request.client else None
    # Only trust X-Forwarded-For when the immediate TCP peer is a known proxy.
    # An attacker can set this header to any value; trusting it unconditionally
    # lets them cycle through spoofed IPs to bypass the rate limiter.
    if peer and peer in SETTINGS.trusted_proxy_ips:
        forwarded_for = request.headers.get("x-forwarded-for", "").strip()
        if forwarded_for:
            leftmost = forwarded_for.split(",", 1)[0].strip()
            if leftmost:
                return f"ip:{leftmost}"
    return f"ip:{peer or 'unknown'}"


def _runtime_work_dir(prefix: str) -> Path:
    RUNTIME_TEMP_DIR.mkdir(parents=True, exist_ok=True)
    work_dir = RUNTIME_TEMP_DIR / f"{prefix}-{uuid4().hex[:10]}"
    work_dir.mkdir(parents=True, exist_ok=True)
    return work_dir


def _doc_id_from_filename(filename: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "-", Path(filename).stem.strip()).strip("-_.").lower()
    return slug or "document"


def _vector_store_for_doc(doc_id: str) -> InMemoryVectorStore:
    return InMemoryVectorStore(collection_name=doc_id)


INGEST_RATE_LIMIT = "6/minute"
PLAN_RATE_LIMIT = "20/minute"
GENERATION_RATE_LIMIT = "8/minute"
EXPORT_RATE_LIMIT = "12/minute"
RATE_LIMIT_ERROR_MESSAGE = "Rate limit exceeded. Try again later."
PREVIEW_STRUCTURE_CACHE_MAX_ENTRIES = 256

app = FastAPI(title="Auto-PPT API", version="0.1.0")
limiter = Limiter(key_func=_rate_limit_key)
app.state.limiter = limiter
app.add_exception_handler(HTTPException, _http_exception_handler)
app.add_exception_handler(RequestValidationError, _validation_exception_handler)
app.add_exception_handler(RateLimitExceeded, _rate_limit_exception_handler)
app.add_exception_handler(Exception, _unexpected_exception_handler)
app.add_middleware(RequestIDMiddleware)
app.add_middleware(ApiKeyMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=SETTINGS.cors_allowed_origins,
    allow_credentials=SETTINGS.cors_safe_allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(SlowAPIMiddleware)


_store = create_store(
    backend=SETTINGS.store_backend,
    db_path=SETTINGS.store_path,
)
# Vector stores are compute caches rebuilt from stored chunks — not persisted.
_INGESTED_VECTOR_STORES: dict[str, InMemoryVectorStore] = {}
_EMBEDDER: Any | None = None
_STRUCTURED_LLM_CLIENT: Any | bool | None = None
_PREVIEW_STRUCTURE_CACHE: OrderedDict[str, dict[str, Any]] = OrderedDict()
_PREVIEW_STRUCTURE_CACHE_LOCK = RLock()
_GENERATION_QUEUE: asyncio.Queue[str] | None = None
_GENERATION_QUEUE_LOOP: asyncio.AbstractEventLoop | None = None
_GENERATION_WORKER_TASK: asyncio.Task[None] | None = None
_GENERATION_PRUNER_TASK: asyncio.Task[None] | None = None
_GENERATION_JOBS: dict[str, dict[str, Any]] = {}
_JOB_TTL_SECONDS: int = 3600       # evict finished jobs after 1 hour
_JOB_PRUNE_INTERVAL_SECONDS: int = 300  # scan every 5 minutes
REPO_ROOT = Path(__file__).resolve().parents[1]
WEB_DIR = REPO_ROOT / "web"
WEB_INDEX = WEB_DIR / "index.html"
RUNTIME_ASSET_DIR = REPO_ROOT / "out" / "runtime_assets"
RUNTIME_TEMP_DIR = REPO_ROOT / "out" / "tmp"
ONAC_TEMPLATE_PATH = REPO_ROOT / "Input" / "Assets" / "PPTs" / "ONAC Presentation Template" / "ONAC Presentation Template.pptx"
DECK_DEFAULT_TEMPLATE_IDS = {
    # Tier 1 — core
    "headline.evidence", "compare.2col", "kpi.big",
    # Tier 2 — frequent exec templates surfaced in the picker
    "timeline.roadmap", "matrix.2x2", "team.grid",
    "process.steps", "dashboard.kpi",
    "impact.statement",
}
SPECIALIST_TEMPLATE_IDS = {"exec.summary", "chart.takeaway", "closing.actions", "title.cover", "section.divider"}
FONT_PAIR_MAP = {
    "Georgia/Oracle Sans Tab": ("Georgia", "Oracle Sans Tab"),
    "Inter/Inter": ("Inter", "Inter"),
    "Lato/Merriweather": ("Merriweather", "Lato"),
    "DM Sans/DM Serif Display": ("DM Serif Display", "DM Sans"),
}
BRAND_THEMES = {
    "ONAC": {
        "style_tokens": StyleTokens(**pipeline_module.ONAC_STYLE_TOKENS),
        "template_path": ONAC_TEMPLATE_PATH,
    },
}
BRAND_THEME_ALIASES = {
    "Auto PPT": "ONAC",
    "Default": "ONAC",
    "Executive Theme": "ONAC",
    "Executive": "ONAC",
    "Corporate": "ONAC",
    "Professional": "ONAC",
}


def _probe_embedder() -> HealthDependencyResponse:
    started = perf_counter()
    embedding = _get_embedder().encode(["health probe"])
    if not embedding or not embedding[0]:
        raise RuntimeError("Embedder returned an empty embedding.")
    return HealthDependencyResponse(latency_ms=max(0, int((perf_counter() - started) * 1000)))


def _probe_vector_store() -> HealthDependencyResponse:
    started = perf_counter()
    store = InMemoryVectorStore(collection_name=f"health-{uuid4().hex[:8]}", backend="memory")
    probe_chunk = ChunkRecord(
        chunk_id=f"health:{uuid4().hex[:8]}:0",
        chunk_index=0,
        doc_id="health-doc",
        source_id="health-source",
        element_id="health-element",
        element_type=ContentElementType.PARAGRAPH,
        classification=ContentClassification.AUDIENCE_CONTENT,
        page=1,
        locator="health:page1",
        text="Health probe chunk.",
    )
    probe_embedding = [0.1, 0.2, 0.3]
    store.upsert_chunks([probe_chunk], [probe_embedding])
    retrieved = store.query(query_embedding=probe_embedding, n_results=1)
    if not retrieved or retrieved[0].chunk_id != probe_chunk.chunk_id:
        raise RuntimeError("Vector store probe failed to round-trip a chunk.")
    return HealthDependencyResponse(latency_ms=max(0, int((perf_counter() - started) * 1000)))


def _health_check_sync() -> HealthResponse:
    failures: list[str] = []
    embedder_status: HealthDependencyResponse | None = None
    vector_store_status: HealthDependencyResponse | None = None

    try:
        embedder_status = _probe_embedder()
    except Exception as exc:
        failures.append(f"embedder: {exc}")

    try:
        vector_store_status = _probe_vector_store()
    except Exception as exc:
        failures.append(f"vector_store: {exc}")

    if failures:
        _raise_api_error(503, 'health_check_failed', '; '.join(failures))

    assert embedder_status is not None
    assert vector_store_status is not None
    return HealthResponse(embedder=embedder_status, vector_store=vector_store_status)


@app.get("/api/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return await asyncio.to_thread(_health_check_sync)


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _generation_job_urls(job_id: str) -> tuple[str, str]:
    return (f"/api/generate/jobs/{job_id}", f"/api/generate/jobs/{job_id}/events")


def _generation_job_status_payload(job: dict[str, Any]) -> GenerationJobStatusResponse:
    error = job.get("error")
    return GenerationJobStatusResponse(
        job_id=job["job_id"],
        status=job["status"],
        stage=job["stage"],
        progress=job["progress"],
        created_at=job["created_at"],
        started_at=job.get("started_at"),
        finished_at=job.get("finished_at"),
        deck_id=job.get("deck_id"),
        error=error,
    )


def _format_sse_event(event: str, payload: dict[str, Any]) -> str:
    data = json.dumps(payload, separators=(",", ":"))
    return f"event: {event}\ndata: {data}\n\n"


async def _publish_generation_event(job: dict[str, Any], event: str) -> None:
    payload = _generation_job_status_payload(job).model_dump(mode="json")
    for listener in list(job["listeners"]):
        await listener.put(_format_sse_event(event, payload))


async def _set_generation_job_state(
    job: dict[str, Any],
    *,
    status: str,
    stage: str,
    progress: float,
    deck_id: str | None = None,
    error: dict[str, str] | None = None,
) -> None:
    job["status"] = status
    job["stage"] = stage
    job["progress"] = progress
    if status == "running" and job.get("started_at") is None:
        job["started_at"] = _timestamp()
    if status in {"completed", "failed"}:
        job["finished_at"] = _timestamp()
    if deck_id is not None:
        job["deck_id"] = deck_id
    if error is not None:
        job["error"] = error
    await _publish_generation_event(job, status)


async def _run_generation_job(job_id: str) -> None:
    job = _GENERATION_JOBS[job_id]
    await _set_generation_job_state(job, status="running", stage="loading_draft", progress=0.15)
    try:
        await _set_generation_job_state(job, status="running", stage="generating_deck", progress=0.45)
        deck = await asyncio.to_thread(_generate_deck_from_draft_sync, job["payload"])
        await _set_generation_job_state(
            job,
            status="completed",
            stage="completed",
            progress=1.0,
            deck_id=deck.id,
        )
    except HTTPException as exc:
        code, message = _extract_error_detail(exc.detail, status_code=exc.status_code)
        await _set_generation_job_state(
            job,
            status="failed",
            stage="failed",
            progress=1.0,
            error={"code": code, "message": message},
        )
    except Exception as exc:
        await _set_generation_job_state(
            job,
            status="failed",
            stage="failed",
            progress=1.0,
            error={"code": "generation_failed", "message": str(exc)},
        )


async def _generation_worker() -> None:
    assert _GENERATION_QUEUE is not None
    while True:
        job_id = await _GENERATION_QUEUE.get()
        try:
            await _run_generation_job(job_id)
        finally:
            _GENERATION_QUEUE.task_done()


async def _prune_generation_jobs() -> None:
    """Background task: evict completed/failed jobs that are older than _JOB_TTL_SECONDS.

    Only removes a job when:
    - its status is "completed" or "failed" (never touches in-progress jobs)
    - it has no active SSE listeners (no client is still streaming it)
    - its finished_at timestamp is past the TTL window
    """
    while True:
        await asyncio.sleep(_JOB_PRUNE_INTERVAL_SECONDS)
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=_JOB_TTL_SECONDS)
        stale: list[str] = []
        for job_id, job in list(_GENERATION_JOBS.items()):
            if job["status"] not in {"completed", "failed"}:
                continue
            if job["listeners"]:  # a client is still streaming this job
                continue
            finished_at = job.get("finished_at")
            if not finished_at:
                continue
            try:
                ts = datetime.fromisoformat(finished_at)
                # Handle naive timestamps from pre-fix data by assuming UTC.
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                if ts < cutoff:
                    stale.append(job_id)
            except ValueError:
                pass  # malformed timestamp — leave it for the next cycle
        for job_id in stale:
            _GENERATION_JOBS.pop(job_id, None)
        if stale:
            logging.getLogger("pptx_gen.api").debug(
                "generation_jobs_pruned", extra={"count": len(stale)}
            )


async def _ensure_generation_worker() -> None:
    global _GENERATION_QUEUE, _GENERATION_QUEUE_LOOP, _GENERATION_WORKER_TASK
    current_loop = asyncio.get_running_loop()
    if _GENERATION_QUEUE is None or _GENERATION_QUEUE_LOOP is not current_loop:
        _GENERATION_QUEUE = asyncio.Queue()
        _GENERATION_QUEUE_LOOP = current_loop
    if _GENERATION_WORKER_TASK is None or _GENERATION_WORKER_TASK.done():
        _GENERATION_WORKER_TASK = asyncio.create_task(_generation_worker())


@app.on_event("startup")
async def _startup_generation_worker() -> None:
    global _GENERATION_PRUNER_TASK
    await _ensure_generation_worker()
    if _GENERATION_PRUNER_TASK is None or _GENERATION_PRUNER_TASK.done():
        _GENERATION_PRUNER_TASK = asyncio.create_task(_prune_generation_jobs())
    if SETTINGS.warm_embedder_on_startup:
        started = perf_counter()
        try:
            await asyncio.to_thread(_get_embedder().encode, ["startup warmup"])
            _INGEST_LOGGER.info(
                "embedder_startup_warmup",
                extra={
                    "duration_ms": int((perf_counter() - started) * 1000),
                    "status": "ok",
                },
            )
        except Exception:
            _INGEST_LOGGER.exception(
                "embedder_startup_warmup_failed",
                extra={
                    "duration_ms": int((perf_counter() - started) * 1000),
                    "status": "error",
                },
            )


@app.on_event("shutdown")
async def _shutdown_generation_worker() -> None:
    global _GENERATION_QUEUE, _GENERATION_QUEUE_LOOP, _GENERATION_WORKER_TASK, _GENERATION_PRUNER_TASK
    for task in (_GENERATION_WORKER_TASK, _GENERATION_PRUNER_TASK):
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
    _GENERATION_WORKER_TASK = None
    _GENERATION_PRUNER_TASK = None
    _GENERATION_QUEUE = None
    _GENERATION_QUEUE_LOOP = None


@app.get("/api/generate/jobs/{job_id}", response_model=GenerationJobStatusResponse)
async def get_generation_job(job_id: str) -> GenerationJobStatusResponse:
    job = _GENERATION_JOBS.get(job_id)
    if job is None:
        _raise_api_error(404, "generation_job_not_found", f"Unknown generation job: {job_id}")
    return _generation_job_status_payload(job)


@app.get("/api/generate/jobs/{job_id}/events")
async def stream_generation_job(job_id: str) -> StreamingResponse:
    job = _GENERATION_JOBS.get(job_id)
    if job is None:
        _raise_api_error(404, "generation_job_not_found", f"Unknown generation job: {job_id}")

    listener: asyncio.Queue[str] = asyncio.Queue()
    job["listeners"].add(listener)
    await listener.put(_format_sse_event("snapshot", _generation_job_status_payload(job).model_dump(mode="json")))

    async def event_stream() -> AsyncIterator[str]:
        try:
            while True:
                if job["status"] in {"completed", "failed"} and listener.empty():
                    break
                try:
                    message = await asyncio.wait_for(listener.get(), timeout=15)
                    yield message
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
        finally:
            job["listeners"].discard(listener)

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.post("/api/generate/async", response_model=GenerationJobAcceptedResponse)
@limiter.shared_limit(GENERATION_RATE_LIMIT, scope="generation-heavy", error_message=RATE_LIMIT_ERROR_MESSAGE)
async def enqueue_deck_generation(request: Request, payload: GenerateDeckRequest) -> GenerationJobAcceptedResponse:
    await _ensure_generation_worker()
    assert _GENERATION_QUEUE is not None
    job_id = f"genjob-{uuid4().hex[:10]}"
    status_url, stream_url = _generation_job_urls(job_id)
    job = {
        "job_id": job_id,
        "payload": payload,
        "status": "queued",
        "stage": "queued",
        "progress": 0.0,
        "created_at": _timestamp(),
        "started_at": None,
        "finished_at": None,
        "deck_id": None,
        "error": None,
        "listeners": set(),
    }
    _GENERATION_JOBS[job_id] = job
    await _GENERATION_QUEUE.put(job_id)
    return GenerationJobAcceptedResponse(job_id=job_id, status="queued", stream_url=stream_url, status_url=status_url)


@app.get("/api/generate/jobs/{job_id}/result", response_model=PresentationSpecResponse)
async def get_generation_job_result(job_id: str) -> PresentationSpecResponse:
    job = _GENERATION_JOBS.get(job_id)
    if job is None:
        _raise_api_error(404, "generation_job_not_found", f"Unknown generation job: {job_id}")
    if job["status"] != "completed" or not job.get("deck_id"):
        _raise_api_error(409, "generation_job_not_ready", f"Generation job is not complete: {job_id}")
    stored = _store.get_deck_spec(job["deck_id"])
    if stored is None:
        _raise_api_error(404, "deck_not_found", f"Unknown deck_id: {job['deck_id']}")
    return _to_api_presentation_spec(stored)


@app.get("/api/assets/local")
async def get_local_preview_asset(path: str) -> Response:
    return FileResponse(_resolve_local_preview_asset(path))


async def _ingest_document(file: UploadFile) -> IngestResponse:
    total_started = perf_counter()
    original_name = Path(file.filename or "upload.txt").name
    suffix = Path(original_name).suffix.lower()
    if suffix not in {".pdf", ".txt", ".md", ".pptx"}:
        _raise_api_error(400, 'unsupported_upload_type', 'Only .pdf, .txt, .md, and .pptx uploads are supported.')

    payload = await file.read()
    if len(payload) > SETTINGS.max_upload_bytes:
        max_mb = SETTINGS.max_upload_bytes // (1024 * 1024)
        _raise_api_error(413, 'upload_too_large', f'Upload exceeds the {max_mb} MB limit.')

    work_dir = _runtime_work_dir("ingest")
    doc_id = _doc_id_from_filename(original_name)
    doc_vector_store = _vector_store_for_doc(doc_id)
    cache_hit = False
    pipeline_ms = 0
    try:
        if doc_vector_store.has_data() and _store.has_ingestion_result(doc_id):
            cache_hit = True
            result = _store.get_ingestion_result(doc_id)
            assert result is not None
        else:
            doc_vector_store.clear()
            pipeline_started = perf_counter()
            result = await asyncio.to_thread(
                _ingest_and_index_sync,
                work_dir / original_name,
                payload,
                Path(original_name).stem.replace("_", " "),
                doc_vector_store,
            )
            pipeline_ms = int((perf_counter() - pipeline_started) * 1000)
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)

    element_counts = Counter(element.type.value for element in result.ingestion_request.document.elements)
    source_metadata = dict(result.ingestion_request.extensions or {})
    summary_started = perf_counter()
    summary = await _generate_document_summary(result)
    summary_ms = int((perf_counter() - summary_started) * 1000)
    response = IngestResponse(
        doc_id=result.doc_id,
        chunk_count=result.n_chunks,
        title=result.ingestion_request.document.title,
        element_types=dict(sorted(element_counts.items())),
        source_format=str(source_metadata.get("source_format") or suffix.removeprefix(".") or "document"),
        slide_count=(
            int(source_metadata["slide_count"])
            if source_metadata.get("slide_count") not in {None, ""}
            else None
        ),
        slide_types=(
            dict(source_metadata["slide_types"])
            if isinstance(source_metadata.get("slide_types"), dict)
            else {}
        ),
        summary=summary,
    )
    _store.put_ingested_doc(result.doc_id, response)
    _store.put_ingestion_result(result.doc_id, result)
    _INGESTED_VECTOR_STORES[result.doc_id] = doc_vector_store

    _INGEST_LOGGER.info(
        "ingest_request_timing",
        extra={
            "doc_id": result.doc_id,
            "path": "/api/ingest",
            "method": "POST",
            "cache_hit": cache_hit,
            "payload_bytes": len(payload),
            "n_elements": result.n_elements,
            "n_chunks": result.n_chunks,
            "pipeline_ms": pipeline_ms,
            "summary_ms": summary_ms,
            "total_ms": int((perf_counter() - total_started) * 1000),
        },
    )
    return response


@app.post("/api/ingest", response_model=IngestResponse)
@limiter.limit(INGEST_RATE_LIMIT, error_message=RATE_LIMIT_ERROR_MESSAGE)
async def ingest_document(request: Request, file: UploadFile = File(...)) -> IngestResponse:
    return await _ingest_document(file)


@app.post("/api/plan", response_model=PlanDeckResponse)
@limiter.limit(PLAN_RATE_LIMIT, error_message=RATE_LIMIT_ERROR_MESSAGE)
async def plan_deck(request: Request, payload: PlanDeckRequest) -> PlanDeckResponse:
    return await asyncio.to_thread(
        _plan_deck_response,
        doc_ids=payload.doc_ids,
        goal=payload.goal,
        audience=payload.audience,
        tone=payload.tone,
        slide_count=payload.slide_count,
    )


@app.post("/api/plan/prompt", response_model=PlanDeckResponse)
@limiter.limit(PLAN_RATE_LIMIT, error_message=RATE_LIMIT_ERROR_MESSAGE)
async def plan_deck_from_prompt(request: Request, payload: PlanPromptRequest) -> PlanDeckResponse:
    ingestion_results = _ingested_results_for(payload.doc_ids)
    combined_title = " + ".join(result.ingestion_request.document.title for result in ingestion_results)
    content_chunk_count = sum(
        1 for result in ingestion_results
        for chunk in result.chunks
        if chunk.classification is ContentClassification.AUDIENCE_CONTENT
    )
    inferred = _infer_chat_brief(
        payload.prompt,
        combined_title,
        content_chunk_count=content_chunk_count,
        source_context=_source_metadata_for_results(ingestion_results),
    )
    return await asyncio.to_thread(
        _plan_deck_response,
        doc_ids=payload.doc_ids,
        goal=inferred["goal"],
        audience=inferred["audience"],
        tone=inferred["tone"],
        slide_count=inferred["slide_count"],
    )


def _plan_deck_response(
    *,
    doc_ids: list[str],
    goal: str,
    audience: str,
    tone: float,
    slide_count: int,
) -> PlanDeckResponse:
    ingestion_results = _ingested_results_for(doc_ids)
    combined_title = " + ".join(result.ingestion_request.document.title for result in ingestion_results)
    tone_label = _tone_label_from_score(tone)
    source_ids = [result.source_id for result in ingestion_results]
    source_texts = [
        chunk.text
        for result in ingestion_results
        for chunk in result.chunks
        if chunk.classification is ContentClassification.AUDIENCE_CONTENT
    ]
    source_metadata = _source_metadata_for_results(ingestion_results)

    brief = collect_deck_brief(
        user_request=goal,
        audience=audience,
        goal=goal,
        tone=tone_label,
        slide_count_target=slide_count,
        source_corpus_ids=source_ids,
        document_title=combined_title,
        source_texts=source_texts,
        source_metadata=source_metadata,
        llm_client=_get_optional_structured_llm_client(),
    )
    outline = _normalize_outline_exact_count(
        generate_outline(brief, llm_client=_get_optional_structured_llm_client()),
        slide_count,
        goal,
        ingestion_results=ingestion_results,
    )

    created_at = _timestamp()
    draft_id = f"draft-{uuid4().hex[:10]}"
    _store.put_draft(draft_id, DraftState(
        draft_id=draft_id,
        doc_ids=list(doc_ids),
        source_ids=source_ids,
        title=combined_title,
        goal=goal,
        audience=audience,
        tone_label=tone_label,
        slide_count=slide_count,
        brief=brief.model_copy(update={"slide_count_target": slide_count}),
        outline=outline,
        created_at=created_at,
    ))

    return PlanDeckResponse(
        draft_id=draft_id,
        doc_id=doc_ids[0],
        doc_ids=list(doc_ids),
        title=combined_title,
        goal=goal,
        audience=audience,
        slides=_outline_to_response_slides(
            outline,
            goal=goal,
            audience=audience,
            title=combined_title,
            created_at=created_at,
        ),
        created_at=created_at,
    )


def _generate_deck_from_draft_sync(request_model: GenerateDeckRequest) -> PresentationSpecResponse:
    import logging
    logger = logging.getLogger("pptx_gen.api")

    draft = _store.get_draft(request_model.draft_id)
    if draft is None:
        _raise_api_error(404, 'draft_not_found', f'Unknown draft_id: {request_model.draft_id}')
    if len(request_model.outline) != draft.slide_count:
        draft = draft.model_copy(update={
            "slide_count": len(request_model.outline),
            "brief": draft.brief.model_copy(update={"slide_count_target": len(request_model.outline)}),
        })
        _store.put_draft(draft.draft_id, draft)

    selected_template_id = canonical_template_key(request_model.selected_template_id)
    if selected_template_id not in DECK_DEFAULT_TEMPLATE_IDS:
        _raise_api_error(400, 'unsupported_deck_template', f'Unsupported deck-level template: {request_model.selected_template_id}')

    try:
        outline = _apply_outline_edits(draft, request_model.outline)
        vector_store = _build_vector_store(draft.doc_ids)
        retrieved_chunks = execute_retrieval_plan(
            build_retrieval_plan(draft.brief, outline, llm_client=_get_optional_structured_llm_client()),
            vector_store=vector_store,
            embedder=_get_embedder(),
        )
        theme_name = request_model.theme_name or "ONAC"
        _theme_config(theme_name)
        style_tokens = _style_tokens_from_brand_kit(request_model.brand_kit, theme_name)
        deck_id = f"deck-{draft.doc_ids[0]}-{uuid4().hex[:10]}"
        logo_path = _persist_logo_asset(deck_id, request_model.brand_kit.logo_data_url)

        llm_client = _get_optional_structured_llm_client()
        spec = generate_presentation_spec(
            draft.brief.model_copy(update={"tone": draft.tone_label, "slide_count_target": draft.slide_count}),
            outline,
            retrieved_chunks,
            deck_title=f"{draft.title} presentation",
            style_tokens=style_tokens,
            theme_name=theme_name,
            language="en-US",
            llm_client=llm_client,
        )
        if llm_client is not None:
            spec = remediate_low_quality_slides(
                spec,
                draft.brief.model_copy(update={"tone": draft.tone_label, "slide_count_target": draft.slide_count}),
                outline,
                retrieved_chunks,
                llm_client=llm_client,
            )
        spec = _enforce_outline_authority(spec, outline, draft.source_ids)
        spec = _apply_global_template_default(spec, selected_template_id)
        spec = _inject_brand_logo(spec, logo_path)

        created_at = _timestamp()
        stored_deck = StoredDeck(
            deck_id=deck_id,
            doc_ids=draft.doc_ids,
            goal=draft.goal,
            created_at=created_at,
            spec=spec,
        )
        _store.put_deck_spec(deck_id, stored_deck)
        return _to_api_presentation_spec(stored_deck)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("generate_deck_from_draft failed")
        raise HTTPException(status_code=500, detail={'code': 'generation_failed', 'message': f'Generation failed: {exc}'}) from exc


@app.post("/api/generate", response_model=PresentationSpecResponse)
@limiter.shared_limit(GENERATION_RATE_LIMIT, scope="generation-heavy", error_message=RATE_LIMIT_ERROR_MESSAGE)
async def generate_deck_from_draft(request: Request, payload: GenerateDeckRequest) -> PresentationSpecResponse:
    return await asyncio.to_thread(_generate_deck_from_draft_sync, payload)


@app.post("/api/slide/preview", response_model=SlideSpecResponse)
@limiter.shared_limit(GENERATION_RATE_LIMIT, scope="generation-heavy", error_message=RATE_LIMIT_ERROR_MESSAGE)
async def generate_slide_preview(request: Request, payload: SlidePreviewRequest) -> SlideSpecResponse:
    import logging
    logger = logging.getLogger("pptx_gen.api")

    try:
        purpose = SlidePurpose(payload.purpose)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={'code': 'unsupported_slide_purpose', 'message': f'Unsupported slide purpose: {payload.purpose}'}) from exc

    content_text = payload.content.strip()
    chosen_template = canonical_template_key(payload.template_id)

    grounding_text = await asyncio.to_thread(
        _retrieve_grounding_for_preview,
        deck_id=payload.deck_id,
        title=payload.title,
        content=content_text,
    )

    structured: dict[str, Any] | None = None
    try:
        structured = await _llm_structure_slide_content(
            content=content_text,
            title=payload.title,
            audience=payload.audience,
            goal=payload.goal,
            purpose=purpose,
            selected_template=chosen_template,
            grounding_text=grounding_text,
        )
    except PreviewLLMUnavailableError:
        # No LLM client configured (expected in local dev) — fall through to the
        # deterministic path.
        logger.warning("slide_preview_llm_unavailable", extra={"title": payload.title, "fallback": "deterministic"})
    except PreviewStructureError as exc:
        # LLM returned unusable/malformed output — surface as a structured 500 so
        # callers can distinguish this from a healthy deterministic preview.
        raise HTTPException(
            status_code=500,
            detail={"code": "preview_generation_failed", "message": str(exc)},
        ) from exc

    if structured is not None:
        blocks_data = structured.get("blocks", [])
        headline = structured.get("headline", payload.title)
        speaker_notes = structured.get("speaker_notes", "")
    else:
        # Deterministic fallback: wrap the raw content as a single text block.
        blocks_data = [{"kind": "text", "text": content_text}] if content_text else []
        headline = payload.title
        speaker_notes = ""

    slide = _build_preview_slide(
        slide_id=payload.slide_id,
        purpose=purpose,
        headline=headline,
        template_key=chosen_template,
        blocks_data=blocks_data,
        speaker_notes=speaker_notes,
    )
    return _to_api_slide_spec(slide, index=1)


def _retrieve_grounding_for_preview(
    *,
    deck_id: str | None,
    title: str,
    content: str,
    max_chunks: int = 6,
) -> str:
    """Pull source-doc passages for a slide-preview regeneration.

    Returns a newline-joined string of the top chunks most relevant to the
    slide's title and current content. Empty string if no deck context is
    available or retrieval fails — callers treat empty as "no grounding".
    """
    if not deck_id:
        return ""
    deck = _store.get_deck_spec(deck_id)
    if deck is None or not deck.doc_ids:
        return ""

    import logging
    logger = logging.getLogger("pptx_gen.api")
    try:
        available_doc_ids = [d for d in deck.doc_ids if _store.has_ingestion_result(d)]
        if not available_doc_ids:
            return ""
        vector_store = _build_vector_store(available_doc_ids)
        embedder = _get_embedder()

        # Prefer the slide title as the query signal; add the first non-empty
        # content line as a secondary query. Callers already pass stripped
        # content, but defend against the empty case.
        queries: list[str] = []
        title_stripped = title.strip() if title else ""
        if title_stripped:
            queries.append(title_stripped)
        content_stripped = content.strip() if content else ""
        if content_stripped:
            first_line = content_stripped.splitlines()[0].strip()
            if first_line and first_line not in queries:
                queries.append(first_line)
        if not queries:
            return ""

        seen_ids: set[str] = set()
        collected: list[str] = []
        for query in queries[:2]:
            embedding = embedder.encode([query])[0]
            hits = vector_store.query(
                query_embedding=embedding,
                n_results=max_chunks,
                exclude_classifications=[
                    ContentClassification.META_PLANNING,
                    ContentClassification.BOILERPLATE,
                ],
            )
            for hit in hits:
                if hit.chunk_id in seen_ids:
                    continue
                if hit.score is not None and hit.score < MIN_RETRIEVAL_SCORE:
                    continue
                seen_ids.add(hit.chunk_id)
                collected.append(hit.text.strip())
                if len(collected) >= max_chunks:
                    break
            if len(collected) >= max_chunks:
                break
        return "\n\n".join(collected)
    except Exception as exc:
        logger.warning("grounding retrieval failed for deck %s: %s", deck_id, exc)
        return ""


@app.post("/api/chat/generate", response_model=ChatGenerateResponse)
@limiter.shared_limit(GENERATION_RATE_LIMIT, scope="generation-heavy", error_message=RATE_LIMIT_ERROR_MESSAGE)
async def chat_generate_deck(
    request: Request,
    prompt: str = Form(...),
    file: UploadFile = File(...),
) -> ChatGenerateResponse:
    ingest = await _ingest_document(file)
    ingestion_result = _store.get_ingestion_result(ingest.doc_id)
    assert ingestion_result is not None  # just ingested above
    content_chunk_count = sum(
        1 for chunk in ingestion_result.chunks
        if chunk.classification is ContentClassification.AUDIENCE_CONTENT
    )
    inferred = _infer_chat_brief(
        prompt,
        ingest.title,
        content_chunk_count=content_chunk_count,
        source_context=_source_metadata_for_results([ingestion_result]),
    )
    planned = await asyncio.to_thread(
        _plan_deck_response,
        doc_ids=[ingest.doc_id],
        goal=inferred["goal"],
        audience=inferred["audience"],
        tone=inferred["tone"],
        slide_count=inferred["slide_count"],
    )
    deck = await asyncio.to_thread(_generate_deck_from_draft_sync,
        GenerateDeckRequest(
            draft_id=planned.draft_id,
            outline=[
                OutlineSlideRequest(
                    id=slide.id,
                    index=slide.index,
                    purpose=slide.purpose,
                    title=slide.title,
                    template_id=slide.template_id,
                )
                for slide in planned.slides
            ],
            theme_name="ONAC",
            selected_template_id=inferred["selected_template_id"],
            brand_kit=BrandKitRequest(
                logo_data_url=None,
                primary_color="#C74634",
                accent_color="#2A2F2F",
                font_pair="Georgia/Oracle Sans Tab",
            ),
        )
    )
    session_id = f"chat-{uuid4().hex[:10]}"
    messages = [
        ChatMessageResponse(role="user", content=prompt),
        ChatMessageResponse(
            role="assistant",
            content=(
                f"Understood. I used {ingest.title} to create a {inferred['slide_count']}-slide deck for "
                f"{inferred['audience']} with a {inferred['goal'].lower()} focus."
            ),
        ),
        ChatMessageResponse(
            role="assistant",
            content=f"The deck is ready with {len(deck.slides)} slides and opens in the editor for refinement.",
        ),
    ]
    _store.put_chat_session(session_id, messages)
    return ChatGenerateResponse(
        session_id=session_id,
        prompt=prompt,
        inferred_goal=inferred["goal"],
        inferred_audience=inferred["audience"],
        inferred_slide_count=inferred["slide_count"],
        messages=messages,
        deck=deck,
    )


@app.get("/api/templates", response_model=list[TemplateResponse])
async def get_templates() -> list[TemplateResponse]:
    return [
        TemplateResponse(
            id=template_key,
            name=_humanize_template_name(template_key),
            alias=_ALIAS_BY_CANONICAL.get(template_key, template_key),
            columns=_template_column_count(template_key),
            description=TEMPLATE_REGISTRY[template_key].description,
            deck_default_allowed=template_key in DECK_DEFAULT_TEMPLATE_IDS,
        )
        for template_key in list_template_keys()
    ]


@app.get("/api/themes", response_model=list[str])
async def get_themes() -> list[str]:
    return sorted(BRAND_THEMES.keys())


@app.get("/api/deck/{deck_id}", response_model=PresentationSpecResponse)
async def get_deck(deck_id: str) -> PresentationSpecResponse:
    stored = _store.get_deck_spec(deck_id)
    if stored is None:
        _raise_api_error(404, 'deck_not_found', f'Unknown deck_id: {deck_id}')
    return _to_api_presentation_spec(stored)


@app.post("/api/export/{deck_id}", response_model=None)
@limiter.limit(EXPORT_RATE_LIMIT, error_message=RATE_LIMIT_ERROR_MESSAGE)
async def export_deck(request: Request, deck_id: str, payload: ExportRequest) -> Response:
    stored = _store.get_deck_spec(deck_id)
    if stored is None:
        _raise_api_error(404, 'deck_not_found', f'Unknown deck_id: {deck_id}')

    export_spec = _merge_export_slides(stored.spec, payload.slides)

    if payload.format == "pptx":
        pptx_bytes = await asyncio.to_thread(_export_pptx_sync, export_spec, deck_id)
        return Response(
            content=pptx_bytes,
            media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
            headers={"Content-Disposition": f'attachment; filename="{deck_id}.pptx"'},
        )

    deck_data = _to_api_presentation_spec(stored, spec_override=export_spec).model_dump()
    pdf_bytes = await asyncio.to_thread(_export_pdf_sync, deck_data)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{deck_id}.pdf"'},
    )


@app.get("/", include_in_schema=False)
async def serve_frontend_index() -> Response:
    return _serve_frontend_path("")


@app.get("/{full_path:path}", include_in_schema=False)
async def serve_frontend_path(full_path: str) -> Response:
    return _serve_frontend_path(full_path)


def _get_embedder():
    global _EMBEDDER
    if _EMBEDDER is None:
        _EMBEDDER = pipeline_module.SentenceTransformerEmbedder()
    return _EMBEDDER


def _get_optional_structured_llm_client():
    global _STRUCTURED_LLM_CLIENT
    if _STRUCTURED_LLM_CLIENT is False:
        return None
    if _STRUCTURED_LLM_CLIENT is None:
        _STRUCTURED_LLM_CLIENT = build_default_structured_llm_client()
    return _STRUCTURED_LLM_CLIENT


def _require_structured_llm_client():
    client = _get_optional_structured_llm_client()
    if client is None:
        _raise_api_error(503, 'structured_llm_not_configured', 'No structured LLM client is configured. Set OPENAI_API_KEY or ANTHROPIC_API_KEY.')
    return client


def _ingest_and_index_sync(
    temp_path: Path,
    payload: bytes,
    title: str,
    vector_store: InMemoryVectorStore,
) -> pipeline_module.IngestionIndexResult:
    """Write upload bytes to disk and run the blocking ingest pipeline.

    Runs entirely inside ``asyncio.to_thread`` so neither the file write
    nor the embedder model load block the event loop.
    """
    temp_path.write_bytes(payload)
    return pipeline_module.ingest_and_index(
        temp_path,
        title=title,
        embedder=_get_embedder(),
        vector_store=vector_store,
    )


def _export_pptx_sync(export_spec: PresentationSpec, deck_id: str) -> bytes:
    """Render a PresentationSpec to PPTX bytes inside a worker thread."""
    work_dir = _runtime_work_dir("export")
    try:
        export_path = work_dir / f"{deck_id}.pptx"
        template_path = _theme_template_path(export_spec.theme.name)
        pipeline_module.generate_deck(
            presentation_spec=export_spec,
            output_path=export_path,
            enable_refinement=False,
            template_path=template_path,
            theme_name=export_spec.theme.name,
        )
        if not export_path.exists():
            _raise_api_error(500, 'pptx_export_failed', 'PPTX export failed.')
        return export_path.read_bytes()
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


def _export_pdf_sync(deck_data: dict) -> bytes:
    """Render deck data to PDF bytes inside a worker thread."""
    from pptx_gen.renderer.pdf_exporter import export_deck_to_pdf
    return export_deck_to_pdf(deck_data)


def _generate_document_summary_sync(result: pipeline_module.IngestionIndexResult) -> str:
    """Generate a natural-language summary of an ingested document using the LLM."""
    from pptx_gen.ingestion.schemas import ContentElementType

    elements = result.ingestion_request.document.elements
    title = result.ingestion_request.document.title

    # Collect headings and leading content to form a representative excerpt
    headings = [el.text for el in elements if el.type in (ContentElementType.TITLE, ContentElementType.HEADING)]
    paragraphs = [el.text for el in elements if el.type == ContentElementType.PARAGRAPH and len(el.text.split()) > 8]

    # Build a concise excerpt (first ~2000 chars) for the LLM
    excerpt_parts: list[str] = []
    char_budget = 2000
    for heading in headings[:15]:
        excerpt_parts.append(f"## {heading}")
        char_budget -= len(heading) + 3
        if char_budget <= 0:
            break
    for para in paragraphs[:20]:
        if char_budget <= 0:
            break
        excerpt_parts.append(para)
        char_budget -= len(para)

    excerpt = "\n\n".join(excerpt_parts)

    # Try LLM summary
    try:
        llm_client = _get_optional_structured_llm_client()
        if llm_client is None:
            raise ValueError("No LLM client")

        system = (
            "You summarize documents for presentation authors. Write a clear, informative 3-5 sentence overview "
            "describing what the document covers, its key topics, and the kind of content it contains. "
            "Be specific about the subject matter ? mention actual topics, findings, and themes, not just "
            "structural details like page counts. Write in third person."
        )
        user_prompt = f"Document title: {title}\n\nExcerpt:\n{excerpt}"

        if hasattr(llm_client, "anthropic_client"):
            response = llm_client.anthropic_client.messages.create(
                model=llm_client.model,
                max_tokens=300,
                temperature=0.3,
                system=system,
                messages=[{"role": "user", "content": user_prompt}],
            )
            return response.content[0].text.strip()
        elif hasattr(llm_client, "openai_client"):
            response = llm_client.openai_client.chat.completions.create(
                model=llm_client.model,
                max_tokens=300,
                temperature=0.3,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_prompt},
                ],
            )
            return response.choices[0].message.content.strip()
    except Exception:
        logging.getLogger("pptx_gen.api").warning(
            "llm_document_summary_failed",
            exc_info=True,
            extra={"title": title, "fallback": "extractive"},
        )

    # Fallback: extractive summary from headings
    if headings:
        topic_list = ", ".join(headings[:6])
        return (
            f'"{title}" covers the following topics: {topic_list}. '
            f"The document contains {len(paragraphs)} substantive sections "
            f"across {result.n_chunks} content segments."
        )
    return f'"{title}" was processed into {result.n_chunks} content segments.'


async def _generate_document_summary(result: pipeline_module.IngestionIndexResult) -> str:
    return await asyncio.to_thread(_generate_document_summary_sync, result)


def _ingested_results_for(doc_ids: list[str]) -> list[pipeline_module.IngestionIndexResult]:
    missing = [doc_id for doc_id in doc_ids if not _store.has_ingestion_result(doc_id)]
    if missing:
        _raise_api_error(404, 'document_not_found', f"Unknown doc_id(s): {', '.join(missing)}")
    results: list[pipeline_module.IngestionIndexResult] = []
    for doc_id in doc_ids:
        result = _store.get_ingestion_result(doc_id)
        assert result is not None  # confirmed by has_ingestion_result above
        results.append(result)
    return results


def _source_metadata_for_results(
    ingestion_results: list[pipeline_module.IngestionIndexResult],
) -> dict[str, Any]:
    if len(ingestion_results) != 1:
        return {}
    extensions = dict(ingestion_results[0].ingestion_request.extensions or {})
    if str(extensions.get("source_format", "")).lower() != "pptx":
        return {}
    return extensions


def _build_vector_store(doc_ids: list[str]) -> InMemoryVectorStore:
    # If there's only one doc and we already have its vector store cached, reuse it.
    if len(doc_ids) == 1 and doc_ids[0] in _INGESTED_VECTOR_STORES:
        return _INGESTED_VECTOR_STORES[doc_ids[0]]

    # For a single doc, prefer reopening the persisted Chroma collection.
    if len(doc_ids) == 1:
        persisted = _vector_store_for_doc(doc_ids[0])
        if persisted.has_data():
            _INGESTED_VECTOR_STORES[doc_ids[0]] = persisted
            return persisted

    # For multi-doc decks, merge cached/persisted stores when available, only re-embed misses.
    vector_store = InMemoryVectorStore(collection_name=f"merged-{uuid4().hex[:8]}", backend="memory")
    embedder = _get_embedder()
    for doc_id in doc_ids:
        cached = _INGESTED_VECTOR_STORES.get(doc_id)
        if cached is None:
            reopened = _vector_store_for_doc(doc_id)
            if reopened.has_data():
                cached = reopened
                _INGESTED_VECTOR_STORES[doc_id] = reopened
        if cached is not None:
            vector_store.merge(cached)
            continue
        result = _store.get_ingestion_result(doc_id)
        if result is None:
            continue
        embeddings = embedder.encode([chunk.text for chunk in result.chunks])
        doc_store = _vector_store_for_doc(doc_id)
        doc_store.clear()
        doc_store.upsert_chunks(result.chunks, embeddings)
        _INGESTED_VECTOR_STORES[doc_id] = doc_store
        vector_store.merge(doc_store)
    return vector_store


def _outline_to_response_slides(
    outline: OutlineSpec,
    *,
    goal: str,
    audience: str,
    title: str,
    created_at: str,
) -> list[SlideSpecResponse]:
    return [
        SlideSpecResponse(
            id=item.slide_id,
            index=index,
            purpose=item.purpose.value,
            archetype=item.archetype.value if item.archetype else None,
            title=item.headline,
            blocks=_outline_preview_blocks(
                item,
                outline=outline,
                goal=goal,
                audience=audience,
                title=title,
                created_at=created_at,
            ),
            template_id=_recommended_outline_template(item),
            speaker_notes=None,
        )
        for index, item in enumerate(outline.outline, start=1)
    ]


def _apply_outline_edits(draft: DraftState, outline_updates: list[OutlineSlideRequest]) -> OutlineSpec:
    base_by_id = {item.slide_id: item for item in draft.outline.outline}
    requested_ids = [item.id for item in sorted(outline_updates, key=lambda item: item.index)]
    if set(requested_ids) != set(base_by_id):
        _raise_api_error(400, 'outline_mismatch', 'Outline slides must match the planned draft.')

    outline_items: list[OutlineItem] = []
    explicit_template_by_slide_id: dict[str, str] = {}
    for update in sorted(outline_updates, key=lambda item: item.index):
        base = base_by_id[update.id]
        chosen_template = canonical_template_key(update.template_id or base.template_key or "headline.evidence")
        if chosen_template != canonical_template_key(base.template_key or "headline.evidence"):
            explicit_template_by_slide_id[base.slide_id] = chosen_template
        outline_items.append(
            OutlineItem(
                slide_id=base.slide_id,
                purpose=base.purpose,
                archetype=base.archetype,
                headline=update.title,
                message=base.message,
                evidence_queries=list(base.evidence_queries),
                template_key=chosen_template,
            )
        )
    extensions = dict(draft.outline.extensions or {})
    if explicit_template_by_slide_id:
        extensions["explicit_template_by_slide_id"] = explicit_template_by_slide_id
    return OutlineSpec(
        outline=outline_items,
        questions_for_user=list(draft.outline.questions_for_user),
        extensions=extensions or None,
    )


def _normalize_outline_exact_count(
    outline: OutlineSpec,
    target_count: int,
    goal: str,
    *,
    ingestion_results: list[pipeline_module.IngestionIndexResult] | None = None,
) -> OutlineSpec:
    """Trim or extend an outline to exactly `target_count` slides.

    When the planner returns fewer items than the target, we try to pad with
    *doc-derived* topics (unused headings/titles from the ingested source) so
    every outline item points at real content. Only if the source has nothing
    left to offer do we truncate the target; we never emit ordinal
    "Supporting Detail N" placeholders whose evidence queries don't match the
    source corpus.
    """
    items = list(outline.outline)
    while len(items) > target_count:
        removable_index = next(
            (index for index in range(len(items) - 1, -1, -1) if items[index].purpose is SlidePurpose.CONTENT),
            len(items) - 1,
        )
        items.pop(removable_index)

    if len(items) < target_count:
        source_topics = _derive_source_topics(items, ingestion_results or [])
        insert_at = next(
            (index for index, item in enumerate(items) if item.purpose in {SlidePurpose.SUMMARY, SlidePurpose.CLOSING}),
            len(items),
        )
        for topic in source_topics:
            if len(items) >= target_count:
                break
            headline, message = topic
            items.insert(
                insert_at,
                OutlineItem(
                    slide_id=f"s{len(items) + 1}",
                    purpose=SlidePurpose.CONTENT,
                    headline=headline,
                    message=message,
                    evidence_queries=[headline, message],
                    template_key="headline.evidence",
                ),
            )
            insert_at += 1
        # If we still can't reach target_count, silently truncate rather than
        # emit ungrounded ordinal placeholders. The resulting deck will have
        # fewer slides than requested but every slide will be grounded.

    normalized = [
        item.model_copy(update={"slide_id": f"s{index}"})
        for index, item in enumerate(items, start=1)
    ]
    return OutlineSpec(
        outline=normalized,
        questions_for_user=list(outline.questions_for_user),
        extensions=outline.extensions,
    )


def _derive_source_topics(
    existing_items: list[OutlineItem],
    ingestion_results: list[pipeline_module.IngestionIndexResult],
) -> list[tuple[str, str]]:
    """Pull candidate (headline, message) pairs from ingested source documents.

    Prefers TITLE/HEADING chunks; falls back to the first sentence of longer
    AUDIENCE_CONTENT chunks. Skips any candidate whose headline is already
    covered (case-insensitive substring match) by an existing outline item.
    Each headline is trimmed to ~10 words so it renders cleanly as a slide
    title.
    """
    if not ingestion_results:
        return []

    covered = {(item.headline or "").strip().lower() for item in existing_items if item.headline}

    def is_covered(candidate: str) -> bool:
        norm = candidate.strip().lower()
        if not norm:
            return True
        for existing in covered:
            if norm == existing or norm in existing or existing in norm:
                return True
        return False

    def trim_headline(text: str, max_words: int = 10) -> str:
        words = text.split()
        return " ".join(words[:max_words]).rstrip(",.;:—-")

    def is_stub_headline(h: str) -> bool:
        """Reject bare numbers, bullets, arrow notation, JSON fragments, and single-word stubs."""
        if re.search(r'--?>|=>|<--?', h):
            return True
        if re.search(r'[{}]', h) or re.search(r'"[^"]+"\s*:', h):
            return True
        alpha = sum(1 for ch in h if ch.isalpha())
        if len(h) > 3 and alpha / len(h) < 0.4:
            return True
        real_words = [w for w in h.split() if re.search(r"[a-zA-Z]", w)]
        return len(real_words) < 2

    candidates: list[tuple[str, str]] = []
    seen_headlines: set[str] = set()

    # Pass 1: TITLE/HEADING chunks are the highest-signal topic source.
    for result in ingestion_results:
        for chunk in result.chunks:
            if chunk.classification is not ContentClassification.AUDIENCE_CONTENT:
                continue
            if chunk.element_type not in {ContentElementType.TITLE, ContentElementType.HEADING}:
                continue
            headline = trim_headline(chunk.text)
            if not headline or is_covered(headline) or is_stub_headline(headline):
                continue
            key = headline.lower()
            if key in seen_headlines:
                continue
            seen_headlines.add(key)
            candidates.append((headline, chunk.text.strip()))

    # Pass 2: first sentence of substantive paragraph chunks as backup.
    # Always run when Pass 1 was sparse, even if the outline has no items yet
    # (common when a caller uses this helper to prospectively mine topics).
    if len(candidates) < max(len(existing_items), 3):
        for result in ingestion_results:
            for chunk in result.chunks:
                if chunk.classification is not ContentClassification.AUDIENCE_CONTENT:
                    continue
                if chunk.element_type in {ContentElementType.TITLE, ContentElementType.HEADING}:
                    continue
                sentences = re.split(r"(?<=[.!?])\s+", chunk.text.strip())
                first = sentences[0] if sentences else ""
                if len(first.split()) < 4:
                    continue
                headline = trim_headline(first)
                if not headline or is_covered(headline):
                    continue
                key = headline.lower()
                if key in seen_headlines:
                    continue
                seen_headlines.add(key)
                candidates.append((headline, chunk.text.strip()))

    return candidates


def _style_tokens_from_brand_kit(brand_kit: BrandKitRequest, theme_name: str = "ONAC") -> StyleTokens:
    theme = _theme_config(theme_name)
    base_tokens: StyleTokens = theme["style_tokens"]
    font_pair = brand_kit.font_pair or f"{base_tokens.fonts.heading}/{base_tokens.fonts.body}"
    heading_font, body_font = FONT_PAIR_MAP.get(font_pair, (base_tokens.fonts.heading, base_tokens.fonts.body))
    return StyleTokens(
        fonts={
            "heading": heading_font,
            "body": body_font,
            "mono": base_tokens.fonts.mono,
        },
        colors={
            "bg": base_tokens.colors.bg,
            "text": base_tokens.colors.text,
            "accent": brand_kit.primary_color or base_tokens.colors.accent,
            "muted": brand_kit.accent_color or base_tokens.colors.muted,
        },
        spacing=base_tokens.spacing.model_dump(),
        images=base_tokens.images.model_dump(),
    )


def _theme_config(theme_name: str) -> dict[str, Any]:
    canonical_theme_name = BRAND_THEME_ALIASES.get(theme_name, theme_name)
    theme = BRAND_THEMES.get(canonical_theme_name)
    if theme is None:
        # Unknown theme — fall back to default rather than crashing the export
        logging.getLogger("pptx_gen.api").warning(
            "llm_fallback",
            extra={"event": "llm_fallback", "reason": "unsupported_theme",
                   "context": theme_name, "recovery": "defaulted to ONAC"},
        )
        theme = BRAND_THEMES["ONAC"]
    return theme


def _theme_template_path(theme_name: str) -> str | None:
    template_path = _theme_config(theme_name).get("template_path")
    return str(template_path) if template_path else None


def _persist_logo_asset(deck_id: str, logo_data_url: str | None) -> str | None:
    if not logo_data_url:
        return None
    try:
        header, payload = logo_data_url.split(",", 1)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={'code': 'invalid_logo_data_url', 'message': 'Invalid logo data URL.'}) from exc
    if ";base64" not in header:
        _raise_api_error(400, 'logo_not_base64', 'Logo data URL must be base64 encoded.')

    extension = ".png"
    if "image/jpeg" in header:
        extension = ".jpg"
    elif "image/webp" in header:
        extension = ".webp"

    RUNTIME_ASSET_DIR.mkdir(parents=True, exist_ok=True)
    logo_path = RUNTIME_ASSET_DIR / f"{deck_id}-logo{extension}"
    logo_path.write_bytes(base64.b64decode(payload))
    return str(logo_path)


def _inject_brand_logo(spec: PresentationSpec, logo_path: str | None) -> PresentationSpec:
    if not logo_path:
        return spec
    slides: list[SlideSpec] = []
    injected = False
    for slide in spec.slides:
        if not injected and slide.purpose is SlidePurpose.TITLE and slide.blocks:
            first = slide.blocks[0]
            slides.append(
                slide.model_copy(
                    update={
                        "blocks": [
                            first.model_copy(update={"content": {**first.content, "logo": logo_path}}),
                            *slide.blocks[1:],
                        ]
                    }
                )
            )
            injected = True
        else:
            slides.append(slide)
    return spec.model_copy(update={"slides": slides})


def _enforce_outline_authority(
    spec: PresentationSpec,
    outline: OutlineSpec,
    source_ids: list[str],
) -> PresentationSpec:
    existing_by_id = {slide.slide_id: slide for slide in spec.slides}
    # Build a positional index so we can match LLM slides that used different IDs
    existing_by_index = {index: slide for index, slide in enumerate(spec.slides)}
    used_positions: set[int] = set()

    slides: list[SlideSpec] = []
    for outline_index, item in enumerate(outline.outline):
        slide = existing_by_id.get(item.slide_id)
        # If no ID match, try matching by position — the LLM often generates
        # correct content but with different slide_id values
        if slide is None and outline_index in existing_by_index:
            positional = existing_by_index[outline_index]
            if positional.slide_id not in {i.slide_id for i in outline.outline}:
                slide = positional
                used_positions.add(outline_index)
        if slide is None:
            slides.append(
                SlideSpec(
                    slide_id=item.slide_id,
                    purpose=item.purpose,
                    archetype=item.archetype,
                    layout_intent=LayoutIntent(template_key=item.template_key or "headline.evidence", strict_template=True),
                    headline=item.headline,
                    speaker_notes=item.message,
                    blocks=[
                        PresentationBlock(
                            block_id="b1",
                            kind=PresentationBlockKind.TEXT,
                            content={"text": item.message},
                            source_citations=_fallback_citation(source_ids) if item.purpose in {SlidePurpose.CONTENT, SlidePurpose.SUMMARY, SlidePurpose.CLOSING} else [],
                        )
                    ],
                )
            )
            continue
        slides.append(
            slide.model_copy(
                update={
                    "slide_id": item.slide_id,
                    "purpose": item.purpose,
                    "archetype": item.archetype or slide.archetype,
                    "layout_intent": LayoutIntent(
                        template_key=item.template_key or slide.layout_intent.template_key,
                        strict_template=True,
                    ),
                    "headline": item.headline,
                }
            )
        )
    return spec.model_copy(update={"slides": slides, "extensions": outline.extensions})


def _apply_global_template_default(spec: PresentationSpec, selected_template_id: str) -> PresentationSpec:
    slides: list[SlideSpec] = []
    explicit_template_by_slide_id = {
        slide_id: canonical_template_key(template_key)
        for slide_id, template_key in (spec.extensions or {}).get("explicit_template_by_slide_id", {}).items()
    }
    for slide in spec.slides:
        if slide.purpose not in {SlidePurpose.CONTENT, SlidePurpose.SUMMARY}:
            slides.append(slide)
            continue
        current_template = canonical_template_key(slide.layout_intent.template_key)
        if slide.slide_id in explicit_template_by_slide_id:
            # User explicitly changed the template in the outline editor.
            chosen_template = explicit_template_by_slide_id[slide.slide_id]
        elif current_template in SPECIALIST_TEMPLATE_IDS:
            # Specialist templates (exec.summary, chart.takeaway, etc.) are
            # assigned by the outline heuristic — always keep them.
            chosen_template = current_template
        elif current_template in DECK_DEFAULT_TEMPLATE_IDS and current_template != "headline.evidence":
            # The outline heuristic chose a specific deck-level template
            # (e.g., compare.2col, kpi.big) — preserve the variety.
            chosen_template = current_template
        else:
            # Generic fallback — apply the user's deck-level selection.
            chosen_template = selected_template_id
        slides.append(_coerce_slide_for_template(slide, chosen_template))
    return spec.model_copy(update={"slides": slides})


def _coerce_slide_for_template(slide: SlideSpec, template_key: str) -> SlideSpec:
    canonical = canonical_template_key(template_key or "headline.evidence")

    text_items: list[str] = []
    cards: list[dict[str, str]] = []
    chart_data: dict[str, Any] | None = None
    table_data: dict[str, Any] | None = None
    takeaway: str | None = None
    citations: list[SourceCitation] = []

    for block in slide.blocks:
        citations.extend(block.source_citations)
        if block.kind is PresentationBlockKind.CALLOUT:
            if isinstance(block.content.get("cards"), list):
                for card in block.content.get("cards", []):
                    if isinstance(card, dict):
                        cards.append(
                            {
                                "title": str(card.get("title", "")).strip(),
                                "text": str(card.get("text", "")).strip(),
                            }
                        )
            elif block.content.get("text"):
                takeaway = str(block.content.get("text", "")).strip()
        elif block.kind is PresentationBlockKind.BULLETS:
            text_items.extend(str(item).strip() for item in block.content.get("items", []) if str(item).strip())
        elif block.kind is PresentationBlockKind.TEXT:
            text = str(block.content.get("text", "")).strip()
            if text:
                text_items.append(text)
        elif block.kind is PresentationBlockKind.CHART:
            chart_data = dict(block.content)
        elif block.kind is PresentationBlockKind.TABLE:
            table_data = dict(block.content)
        elif block.kind is PresentationBlockKind.KPI_CARDS:
            for item in block.content.get("items", []):
                if isinstance(item, dict):
                    label = str(item.get("label", "")).strip()
                    value = str(item.get("value", "")).strip()
                    cards.append({"title": label or value, "text": value or label})
        elif block.kind is PresentationBlockKind.TIMELINE:
            for item in block.content.get("items", []):
                if isinstance(item, dict):
                    label = str(item.get("label") or item.get("title") or "").strip()
                    desc = str(item.get("description", "")).strip()
                    if label:
                        text_items.append(f"{label}: {desc}" if desc else label)
        elif block.kind is PresentationBlockKind.STEPS:
            for step in block.content.get("steps", []):
                if isinstance(step, dict):
                    title = str(step.get("title", "")).strip()
                    desc = str(step.get("description", "")).strip()
                    if title:
                        text_items.append(f"{title} — {desc}" if desc else title)
        elif block.kind is PresentationBlockKind.PEOPLE_CARDS:
            for person in block.content.get("people", []):
                if isinstance(person, dict):
                    name = str(person.get("name", "")).strip()
                    title_str = str(person.get("title", "")).strip()
                    if name:
                        text_items.append(f"{name} · {title_str}" if title_str else name)
        elif block.kind is PresentationBlockKind.MATRIX:
            for quadrant in block.content.get("quadrants", []):
                if isinstance(quadrant, dict):
                    q_title = str(quadrant.get("title", "")).strip()
                    items_list = quadrant.get("items", [])
                    if q_title:
                        text_items.append(f"{q_title}: {', '.join(str(i) for i in items_list)}" if items_list else q_title)
        elif block.kind is PresentationBlockKind.STATUS_CARDS:
            for card in block.content.get("cards", []):
                if isinstance(card, dict):
                    label = str(card.get("label", "")).strip()
                    status = str(card.get("status", "")).strip()
                    if label:
                        text_items.append(f"[{status.upper()}] {label}" if status else label)

    if table_data and not text_items:
        rows = table_data.get("rows", [])
        for row in rows[:4]:
            if isinstance(row, list):
                text_items.append(" | ".join(str(cell) for cell in row if str(cell).strip()))
    if not text_items and slide.headline:
        text_items.append(slide.headline)

    def _fallback_callout() -> str:
        return takeaway or (text_items[-1] if text_items else slide.headline)

    if canonical == "title.cover":
        blocks = [
            PresentationBlock(
                block_id="b1",
                kind=PresentationBlockKind.TEXT,
                content={"subtitle": text_items[0] if text_items else "", "presenter": "", "date": datetime.now().strftime("%B %d, %Y")},
                source_citations=[],
            )
        ]
    elif canonical == "section.divider":
        blocks = [
            PresentationBlock(
                block_id="b1",
                kind=PresentationBlockKind.TEXT,
                content={"tagline": text_items[0] if text_items else "", "footer_info": ""},
                source_citations=[],
            )
        ]
    elif canonical == "exec.summary":
        summary_cards = cards[:3]
        if len(summary_cards) < 3:
            for item in text_items[:3 - len(summary_cards)]:
                summary_cards.append({"title": " ".join(item.split()[:4]) or "Point", "text": item})
        blocks = [
            PresentationBlock(block_id="b1", kind=PresentationBlockKind.BULLETS, content={"items": text_items[:5]}, source_citations=citations),
            PresentationBlock(block_id="b2", kind=PresentationBlockKind.CALLOUT, content={"text": _fallback_callout()}, source_citations=citations),
            PresentationBlock(block_id="b3", kind=PresentationBlockKind.CALLOUT, content={"cards": summary_cards[:3]}, source_citations=citations),
        ]
    elif canonical == "headline.evidence":
        blocks = [
            PresentationBlock(block_id="b1", kind=PresentationBlockKind.BULLETS, content={"items": text_items}, source_citations=citations),
            PresentationBlock(block_id="b2", kind=PresentationBlockKind.CALLOUT, content={"text": _fallback_callout()}, source_citations=citations),
        ]
    elif canonical == "kpi.big":
        metric_texts = text_items[:3]
        while len(metric_texts) < 3:
            metric_texts.append(slide.headline)
        blocks = [
            PresentationBlock(block_id=f"b{index + 1}", kind=PresentationBlockKind.TEXT, content={"text": metric_texts[index]}, source_citations=citations[:1] if citations else [])
            for index in range(3)
        ]
    elif canonical == "compare.2col":
        midpoint = max(1, (len(text_items) + 1) // 2)
        blocks = [
            PresentationBlock(block_id="b1", kind=PresentationBlockKind.BULLETS, content={"items": text_items[:midpoint]}, source_citations=citations),
            PresentationBlock(block_id="b2", kind=PresentationBlockKind.BULLETS, content={"items": text_items[midpoint:] or text_items[:1]}, source_citations=citations),
        ]
    elif canonical == "chart.takeaway":
        blocks = [
            PresentationBlock(
                block_id="b1",
                kind=PresentationBlockKind.CHART,
                content=chart_data or {"chart_type": "bar", "data": [{"label": f"Point {index + 1}", "value": index + 1} for index in range(min(max(len(text_items), 1), 3))]},
                source_citations=citations,
            ),
            PresentationBlock(block_id="b2", kind=PresentationBlockKind.CALLOUT, content={"text": _fallback_callout()}, source_citations=citations),
        ]
    else:
        blocks = [
            PresentationBlock(block_id="b1", kind=PresentationBlockKind.BULLETS, content={"items": text_items}, source_citations=citations),
            PresentationBlock(block_id="b2", kind=PresentationBlockKind.CALLOUT, content={"text": _fallback_callout()}, source_citations=citations),
        ]
        canonical = "closing.actions" if canonical == "closing.actions" else "headline.evidence"

    return slide.model_copy(update={"layout_intent": LayoutIntent(template_key=canonical, strict_template=True), "blocks": blocks})


def _slide_summary_items(slide: SlideSpec) -> list[str]:
    items: list[str] = []
    for block in slide.blocks:
        text = _block_summary_text(block)
        if text and text not in items:
            items.append(text)
        if len(items) == 3:
            break
    if not items:
        items.append(slide.headline)
    return items


def _block_summary_text(block: PresentationBlock) -> str:
    content = block.content
    if block.kind is PresentationBlockKind.BULLETS:
        values = [str(item) for item in content.get("items", []) if item]
        return "; ".join(values[:2])
    if block.kind is PresentationBlockKind.KPI_CARDS:
        values = [f"{item.get('label', '')}: {item.get('value', '')}" for item in content.get("items", [])]
        return "; ".join(values[:2])
    if block.kind is PresentationBlockKind.TABLE:
        rows = [" | ".join(str(cell) for cell in row) for row in content.get("rows", [])]
        return "; ".join(rows[:2])
    if block.kind is PresentationBlockKind.CHART:
        series = [f"{item.get('label', '')}: {item.get('value', '')}" for item in content.get("series", [])]
        return "; ".join(series[:2])
    if block.kind is PresentationBlockKind.TIMELINE:
        items = [str(i.get("label") or i.get("title") or "") for i in content.get("items", [])]
        return "; ".join(items[:3])
    if block.kind is PresentationBlockKind.STEPS:
        titles = [str(s.get("title", "")) for s in content.get("steps", [])]
        return "; ".join(titles[:3])
    if block.kind is PresentationBlockKind.PEOPLE_CARDS:
        names = [str(p.get("name", "")) for p in content.get("people", [])]
        return "; ".join(names[:3])
    if block.kind is PresentationBlockKind.MATRIX:
        titles = [str(q.get("title", "")) for q in content.get("quadrants", [])]
        return "; ".join(titles[:4])
    if block.kind is PresentationBlockKind.STATUS_CARDS:
        labels = [f"[{c.get('status','?').upper()}] {c.get('label','')}" for c in content.get("cards", [])]
        return "; ".join(labels[:4])
    for field in ("text", "label", "subtitle", "tagline", "footer_info"):
        value = content.get(field)
        if value:
            return str(value)
    return ""


def _theme_name(template_key: str) -> str:
    return "ONAC"


def _outline_preview_blocks(
    item: OutlineItem,
    *,
    outline: OutlineSpec,
    goal: str,
    audience: str,
    title: str,
    created_at: str,
) -> list[dict[str, str | None]]:
    if item.purpose is SlidePurpose.TITLE:
        title_lines = [
            f"Subtitle: {goal}",
            f"Audience: {audience}",
            f"Deck: {title}",
            f"Date: {created_at[:10]}",
        ]
        return [
            {
                "id": f"{item.slide_id}-title-meta",
                "kind": "text",
                "content": "\n".join(title_lines),
                "citation": None,
            }
        ]

    if item.purpose is SlidePurpose.CLOSING:
        agenda_lines = [
            outline_item.headline
            for outline_item in outline.outline
            if outline_item.purpose in {SlidePurpose.CONTENT, SlidePurpose.SUMMARY}
        ][:5]
        return [
            {
                "id": f"{item.slide_id}-agenda",
                "kind": "bullets",
                "content": "\n".join(f"\u2022 {line}" for line in agenda_lines),
                "citation": None,
            }
        ]

    bullets = [item.message, *item.evidence_queries[:2]]
    return [
        {
            "id": f"{item.slide_id}-outline",
            "kind": "bullets",
            "content": "\n".join(f"\u2022 {_trim_outline_line(line)}" for line in bullets if line),
            "citation": None,
        }
    ]


def _recommended_outline_template(item: OutlineItem) -> str:
    if item.purpose is SlidePurpose.TITLE:
        return "title.cover"
    if item.purpose is SlidePurpose.CLOSING:
        return "closing.actions"
    if item.archetype is SlideArchetype.EXECUTIVE_SUMMARY:
        return "exec.summary"
    if item.archetype is SlideArchetype.COMPARISON:
        return "compare.2col"
    if item.archetype is SlideArchetype.METRICS:
        return "kpi.big"
    if item.archetype is SlideArchetype.CHART:
        return "chart.takeaway"
    if item.purpose is SlidePurpose.SUMMARY:
        return "closing.actions"

    headline = f"{item.headline} {item.message}".lower()
    if any(term in headline for term in ("metric", "kpi", "score", "rate", "roi", "growth")):
        return "kpi.big"
    if any(term in headline for term in ("chart", "trend", "graph", "plot")):
        return "chart.takeaway"
    if any(term in headline for term in ("compare", "comparison", "option", "tradeoff", "landscape", "tools")):
        return "compare.2col"
    if any(term in headline for term in ("overview", "summary", "executive", "capability")):
        return "exec.summary"
    return canonical_template_key(item.template_key or "headline.evidence")


def _trim_outline_line(value: str) -> str:
    words = [word for word in str(value).replace("\n", " ").split() if word]
    return " ".join(words[:12])


def _fallback_citation(source_ids: list[str]) -> list[SourceCitation]:
    source_id = source_ids[0] if source_ids else "source"
    return [SourceCitation(source_id=source_id, locator=f"{source_id}:page1")]


def _preview_structure_cache_key(namespace: str, payload: dict[str, Any]) -> str:
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    ).hexdigest()
    return f"{namespace}:{digest}"


def _get_preview_structure_cache(key: str) -> dict[str, Any] | None:
    with _PREVIEW_STRUCTURE_CACHE_LOCK:
        cached = _PREVIEW_STRUCTURE_CACHE.get(key)
        if cached is None:
            return None
        _PREVIEW_STRUCTURE_CACHE.move_to_end(key)
        return copy.deepcopy(cached)


def _set_preview_structure_cache(key: str, value: dict[str, Any]) -> dict[str, Any]:
    cached_value = copy.deepcopy(value)
    with _PREVIEW_STRUCTURE_CACHE_LOCK:
        if key in _PREVIEW_STRUCTURE_CACHE:
            _PREVIEW_STRUCTURE_CACHE.pop(key)
        _PREVIEW_STRUCTURE_CACHE[key] = cached_value
        while len(_PREVIEW_STRUCTURE_CACHE) > PREVIEW_STRUCTURE_CACHE_MAX_ENTRIES:
            _PREVIEW_STRUCTURE_CACHE.popitem(last=False)
    return copy.deepcopy(cached_value)


def _clear_preview_structure_cache() -> None:
    with _PREVIEW_STRUCTURE_CACHE_LOCK:
        _PREVIEW_STRUCTURE_CACHE.clear()


def _preview_llm_cache_scope(llm_client: Any) -> str:
    model = getattr(llm_client, "model", None)
    return f"{llm_client.__class__.__name__}:{model or 'default'}"


def _generate_structured_preview_with_llm(
    *,
    llm_client: Any,
    content: str,
    title: str,
    audience: str,
    goal: str,
    purpose: SlidePurpose,
    selected_template: str,
    grounding_text: str = "",
) -> dict[str, Any]:
    system = (
        "You are a professional presentation writer. "
        "Given raw editor notes, produce a polished slide with a clear headline, speaker notes, and structured blocks. "
        "CRITICAL: Do NOT copy-paste the raw notes. Synthesize, summarize, and rewrite them into concise, "
        "audience-facing language with an executive tone. Each bullet should be 10-20 words of original phrasing. "
        "Respect the selected template key and format blocks to fit that layout. "
        "When source-document passages are provided, ground every factual claim in them; "
        "prefer source-document content over editor notes when the two diverge."
    )
    source_section = (
        f"\n\nSource-document passages (ground all factual claims in these; "
        f"prefer these over the editor notes when they conflict):\n{grounding_text}"
        if grounding_text.strip()
        else ""
    )
    user_prompt = (
        f"Goal: {goal}\n"
        f"Audience: {audience}\n"
        f"Slide purpose: {purpose.value}\n"
        f"Selected template key: {selected_template}\n"
        f"Title seed: {title}\n\n"
        f"Template guidance:\n{_preview_template_guidance(selected_template)}\n\n"
        "Return a JSON object with: headline (str), speaker_notes (str), blocks (list of block objects). "
        "Do NOT wrap in a PresentationSpec. The response IS the slide object directly.\n\n"
        f"Raw editor notes to synthesize (do NOT echo verbatim):\n{content}"
        f"{source_section}"
    )

    result = llm_client.generate_json(
        system_prompt=system,
        user_prompt=user_prompt,
        schema_name="SlidePreviewLLMResponse",
    )
    if not isinstance(result, dict):
        raise ValueError("Structured preview returned a non-object payload")

    blocks_payload = result.get("blocks", [])
    if not isinstance(blocks_payload, list):
        raise ValueError("Structured preview blocks must be a list")

    normalized_blocks: list[dict[str, Any]] = []
    for block in blocks_payload:
        if not isinstance(block, dict):
            raise ValueError("Structured preview blocks must contain objects")
        kind = block.get("kind", "text")
        if kind == "callout":
            if isinstance(block.get("cards"), list):
                normalized_blocks.append({"kind": kind, "cards": block.get("cards", [])})
            else:
                normalized_blocks.append({"kind": kind, "text": block.get("text", "")})
        elif kind in {"bullets", "kpi_cards"}:
            normalized_blocks.append({"kind": kind, "items": block.get("items", [])})
        elif kind == "table":
            normalized_blocks.append({"kind": kind, "columns": block.get("columns", []), "rows": block.get("rows", [])})
        elif kind == "chart":
            normalized_blocks.append({"kind": kind, "chart_type": block.get("chart_type", "bar"), "series": block.get("series", [])})
        elif kind == "quote":
            normalized_blocks.append({"kind": kind, "text": block.get("text", ""), "attribution": block.get("attribution", "")})
        else:
            normalized_blocks.append({"kind": kind, "text": block.get("text", "")})
    return {
        "headline": result.get("headline", title),
        "template_id": selected_template,
        "speaker_notes": result.get("speaker_notes", ""),
        "blocks": normalized_blocks,
    }


async def _llm_structure_slide_content(
    *,
    content: str,
    title: str,
    audience: str,
    goal: str,
    purpose: SlidePurpose,
    selected_template: str,
    grounding_text: str = "",
) -> dict[str, Any]:
    """Use the structured client to turn editor notes into one well-formed preview slide."""
    llm_client = _get_optional_structured_llm_client()
    if llm_client is None:
        raise PreviewLLMUnavailableError("Structured preview is unavailable because no LLM client is configured.")

    cache_key = _preview_structure_cache_key(
        "llm_preview",
        {
            "scope": _preview_llm_cache_scope(llm_client),
            "content": content,
            "title": title,
            "audience": audience,
            "goal": goal,
            "purpose": purpose.value,
            "selected_template": selected_template,
            "grounding_text": grounding_text,
        },
    )
    cached = _get_preview_structure_cache(cache_key)
    if cached is not None:
        return cached

    try:
        structured = _generate_structured_preview_with_llm(
            llm_client=llm_client,
            content=content,
            title=title,
            audience=audience,
            goal=goal,
            purpose=purpose,
            selected_template=selected_template,
            grounding_text=grounding_text,
        )
        _assert_preview_structure_quality(structured, title=title)
        return _set_preview_structure_cache(cache_key, structured)
    except Exception as llm_exc:
        raise PreviewStructureError(str(llm_exc)) from llm_exc


class PreviewStructureError(ValueError):
    """Raised when preview generation cannot produce a trustworthy structure."""


class PreviewLLMUnavailableError(PreviewStructureError):
    """Raised specifically when no LLM client is configured for preview.
    Unlike a malformed-output PreviewStructureError, this is an expected
    operational state (local dev without API key) and warrants a silent
    fallback to the deterministic preview path.
    """


def _assert_preview_structure_quality(structured: dict[str, Any], *, title: str) -> None:
    blocks = structured.get("blocks", [])
    if not isinstance(blocks, list) or not blocks:
        raise PreviewStructureError("Structured preview returned no blocks.")

    normalized_headline = _normalize_preview_text(structured.get("headline", title))
    normalized_strings: list[str] = []
    for block in blocks:
        normalized_strings.extend(_preview_block_strings(block))

    normalized_strings = [value for value in normalized_strings if value]
    if not normalized_strings:
        raise PreviewStructureError("Structured preview returned no meaningful content.")

    unique_strings = list(dict.fromkeys(normalized_strings))
    nontrivial_unique = [value for value in unique_strings if len(value.split()) >= 2]
    if not nontrivial_unique:
        raise PreviewStructureError("Structured preview returned no meaningful content.")

    repeated_headline_values = [value for value in unique_strings if value == normalized_headline]
    if normalized_headline and len(unique_strings) >= 2 and len(unique_strings) == len(repeated_headline_values):
        raise PreviewStructureError("Structured preview repeated the headline instead of generating slide content.")

    if len(unique_strings) == 1 and len(normalized_strings) >= 2:
        raise PreviewStructureError("Structured preview collapsed to repeated duplicate content.")


def _preview_block_strings(block: Any) -> list[str]:
    if not isinstance(block, dict):
        return []

    kind = str(block.get("kind", "")).strip().lower()
    values: list[str] = []

    def _append(value: Any) -> None:
        normalized = _normalize_preview_text(value)
        if normalized:
            values.append(normalized)

    if kind in {"text", "callout", "quote", "image"}:
        _append(block.get("text", ""))
        _append(block.get("attribution", ""))
    if kind in {"bullets", "kpi_cards"} and isinstance(block.get("items"), list):
        for item in block.get("items", []):
            if isinstance(item, dict):
                _append(item.get("label", ""))
                _append(item.get("value", ""))
                _append(item.get("delta", ""))
            else:
                _append(item)
    if kind == "chart" and isinstance(block.get("series"), list):
        for item in block.get("series", []):
            if isinstance(item, dict):
                _append(item.get("label", ""))
                _append(item.get("value", ""))
    if kind == "table" and isinstance(block.get("rows"), list):
        for row in block.get("rows", []):
            if isinstance(row, list):
                for cell in row:
                    _append(cell)
    if kind == "callout" and isinstance(block.get("cards"), list):
        for card in block.get("cards", []):
            if isinstance(card, dict):
                _append(card.get("title", ""))
                _append(card.get("text", ""))
    if kind == "timeline" and isinstance(block.get("items"), list):
        for item in block.get("items", []):
            if isinstance(item, dict):
                _append(item.get("label", ""))
                _append(item.get("title", ""))
                _append(item.get("description", ""))
    if kind == "steps" and isinstance(block.get("steps"), list):
        for step in block.get("steps", []):
            if isinstance(step, dict):
                _append(step.get("title", ""))
                _append(step.get("description", ""))
    if kind == "people_cards" and isinstance(block.get("people"), list):
        for person in block.get("people", []):
            if isinstance(person, dict):
                _append(person.get("name", ""))
                _append(person.get("title", ""))
                _append(person.get("bio", ""))
    if kind == "matrix" and isinstance(block.get("quadrants"), list):
        for quadrant in block.get("quadrants", []):
            if isinstance(quadrant, dict):
                _append(quadrant.get("title", ""))
                if isinstance(quadrant.get("items"), list):
                    for item in quadrant.get("items", []):
                        _append(item)
    if kind == "status_cards" and isinstance(block.get("cards"), list):
        for card in block.get("cards", []):
            if isinstance(card, dict):
                _append(card.get("label", ""))
                _append(card.get("status", ""))
                _append(card.get("note", ""))
    return values


def _normalize_preview_text(value: Any) -> str:
    if not isinstance(value, (str, int, float)):
        return ""
    return re.sub(r"\s+", " ", str(value).strip().lower())

def _preview_template_guidance(template_key: str) -> str:
    guidance = {
        "title.cover": "Use one high-level subtitle-style text block.",
        "section.divider": "Use one short transition statement or subhead.",
        "headline.evidence": "Use a bullets block plus a short takeaway callout.",
        "exec.summary": "Use three summary cards plus one brief takeaway callout.",
        "compare.2col": "Split the content into two clear sides or perspectives.",
        "chart.takeaway": "Use a chart block if numeric evidence exists plus a short takeaway callout.",
        "kpi.big": "Use kpi_cards with three metrics and short labels.",
        "closing.actions": "Use bullets for concrete next steps or recommendations.",
        "quote.photo": "Use one quote block and optionally a short supporting text or image placeholder.",
        "quote.texture": "Use one strong quote block with attribution if available.",
        "impact.statement": "Use one bold statement block only.",
        "content.3col": "Use three cards or three short text blocks, one per column.",
        "content.4col": "Use four cards or four short text blocks, one per column.",
        "icons.3": "Use three short cards with a heading and brief body text.",
        "icons.4": "Use four short cards with a heading and brief body text.",
        "content.photo": "Use text or bullets for the main message and one image placeholder block.",
        "bold.photo": "Use one bold statement block and one image placeholder block.",
        "split.content": "Use two contrasting text blocks, one for each side.",
        "agenda.table": "Use a concise table with row labels and descriptions.",
        "screenshot": "Use one brief intro text block and one image placeholder block.",
        "timeline.roadmap": "Use a timeline block. Extract up to 5 milestones with label, date, and description. Return {\"blocks\": [{\"kind\": \"timeline\", \"items\": [{\"label\": \"...\", \"date\": \"...\", \"description\": \"...\"}]}]}",
        "matrix.2x2": "Use a matrix block with four quadrants (tl, tr, bl, br). Each quadrant has a title and 1–3 bullet items. Return {\"blocks\": [{\"kind\": \"matrix\", \"quadrants\": [{\"quadrant\": \"tl\", \"title\": \"...\", \"items\": [\"...\"]}]}]}",
        "team.grid": "Use a people_cards block. Extract up to 4 people with name, title, and optional bio. Return {\"blocks\": [{\"kind\": \"people_cards\", \"people\": [{\"name\": \"...\", \"title\": \"...\", \"bio\": \"...\"}]}]}",
        "process.steps": "Use a steps block. Extract 3–5 numbered steps with title and description. Return {\"blocks\": [{\"kind\": \"steps\", \"steps\": [{\"number\": 1, \"title\": \"...\", \"description\": \"...\"}]}]}",
        "dashboard.kpi": "Use kpi_cards with 4–6 metrics, each with a label, value, and optional delta. Return {\"blocks\": [{\"kind\": \"kpi_cards\", \"items\": [{\"label\": \"...\", \"value\": \"...\", \"delta\": \"...\"}]}]}",
        "financial.table": "Use a table block with column headers and financial row data. Include a footnote text block for source/disclaimer. Return {\"blocks\": [{\"kind\": \"table\", \"columns\": [\"...\"], \"rows\": [[\"...\"]]}, {\"kind\": \"text\", \"text\": \"Source: ...\"}]}",
        "status.rag": "Use a status_cards block. Each card has a label (initiative name), status (red/amber/green), and optional note. Return {\"blocks\": [{\"kind\": \"status_cards\", \"cards\": [{\"label\": \"...\", \"status\": \"green\", \"note\": \"...\"}]}]}",
    }
    return guidance.get(template_key, "Format the content to fit the selected layout cleanly and concisely.")


def _fallback_structure_content(
    content: str,
    title: str,
    template: str,
    *,
    grounding_text: str = "",
) -> dict[str, Any]:
    cache_key = _preview_structure_cache_key(
        "fallback_preview",
        {
            "content": content,
            "title": title,
            "template": template,
            "grounding_text": grounding_text,
        },
    )
    cached = _get_preview_structure_cache(cache_key)
    if cached is not None:
        return cached
    structured = _fallback_structure_content_uncached(content, title, template, grounding_text=grounding_text)
    return _set_preview_structure_cache(cache_key, structured)


def _fallback_structure_content_uncached(
    content: str,
    title: str,
    template: str,
    *,
    grounding_text: str = "",
) -> dict[str, Any]:
    """Structure content into slide blocks without LLM.

    When `grounding_text` is provided (retrieved source-document passages),
    it takes priority over the raw editor notes in `content` so regenerate
    pulls from the source doc rather than re-tokenizing residual prompt text.
    """
    source_text = grounding_text.strip() or content
    lines = [line.strip() for line in source_text.splitlines() if line.strip()]
    bullet_lines = [line.lstrip("-•* ").strip() for line in lines if line.startswith(("-", "•", "*"))]
    plain_lines = [line for line in lines if not line.startswith(("-", "•", "*"))]

    sentences: list[str] = []
    for line in lines:
        sentences.extend(re.split(r"(?<=[.!?])\s+", line))
    sentences = [s.strip() for s in sentences if len(s.split()) >= 5]
    # Prefer sentence-level points when the plain-line split would collapse
    # multiple distinct sentences into a single paragraph. This keeps
    # multi-sentence editor notes from degrading into one-point layouts.
    sentence_split_preferred = len(sentences) >= 2 and len(sentences) > len(plain_lines)
    points = (
        bullet_lines
        or (sentences if sentence_split_preferred else plain_lines)
        or sentences
        or [source_text.strip() or title]
    )

    def cards_from_points(count: int) -> list[dict[str, str]]:
        """Build up to `count` cards from available points.

        Never pad with generic "Add supporting detail" filler — if fewer
        real points exist, return fewer cards and let the renderer handle
        the empty slots. This keeps user-facing slides free of placeholder
        text even on the deterministic fallback path.
        """
        cards: list[dict[str, str]] = []
        seen_titles: set[str] = set()
        for point in points[:count]:
            words = point.split()
            if not words:
                continue
            card_title = " ".join(words[:4])
            card_text = " ".join(words[:18]) or point
            key = card_title.lower()
            if key in seen_titles:
                continue
            seen_titles.add(key)
            cards.append({"title": card_title, "text": card_text})
        return cards

    def bullets_from_points(count: int = 5) -> list[str]:
        values = [" ".join(point.split()[:16]) for point in points[:count] if point.strip()]
        return values or [title]

    if template == "kpi.big":
        items: list[dict[str, str]] = []
        seen_labels: set[str] = set()
        for sentence in points[:3]:
            words = sentence.split()
            if not words:
                continue
            numbers = re.findall(r"\b[\d,.]+[%$]?\b", sentence)
            if not numbers:
                # Only emit a KPI card when the source actually carries a metric;
                # inventing "N/A" / "Metric N" filler is the class of bug we just killed.
                continue
            label = " ".join(words[:6])
            key = label.lower()
            if key in seen_labels:
                continue
            seen_labels.add(key)
            items.append({"value": numbers[0], "label": label})
        return {
            "headline": title,
            "template_id": template,
            "speaker_notes": "",
            "blocks": [{"kind": "kpi_cards", "items": items}],
        }

    if template == "compare.2col":
        midpoint = max(1, (len(points) + 1) // 2)
        left_items = [" ".join(point.split()[:16]) for point in points[:midpoint]]
        right_items = [" ".join(point.split()[:16]) for point in points[midpoint:]]
        # No filler: if the source only supports one column, emit a single
        # bullets block. The renderer/UI renders the missing side as an
        # empty column rather than fabricated comparison text.
        blocks: list[dict[str, Any]] = [{"kind": "bullets", "items": left_items}]
        if right_items:
            blocks.append({"kind": "bullets", "items": right_items})
        return {
            "headline": title,
            "template_id": template,
            "speaker_notes": "",
            "blocks": blocks,
        }

    if template == "exec.summary":
        return {
            "headline": title,
            "template_id": template,
            "speaker_notes": "",
            "blocks": [
                {"kind": "bullets", "items": bullets_from_points(4)},
                {"kind": "callout", "text": " ".join((sentences[:1] or points[:1]))[:160]},
                {"kind": "callout", "cards": cards_from_points(3)},
            ],
        }

    if template in {"content.3col", "icons.3"}:
        return {"headline": title, "template_id": template, "speaker_notes": "", "blocks": [{"kind": "callout", "cards": cards_from_points(3)}]}

    if template in {"content.4col", "icons.4"}:
        return {"headline": title, "template_id": template, "speaker_notes": "", "blocks": [{"kind": "callout", "cards": cards_from_points(4)}]}

    if template == "agenda.table":
        rows = [[f"Item {index + 1}", " ".join(point.split()[:14])] for index, point in enumerate(points[:5])]
        return {
            "headline": title,
            "template_id": template,
            "speaker_notes": "",
            "blocks": [{"kind": "table", "columns": ["Section", "Focus"], "rows": rows}],
        }

    if template == "chart.takeaway":
        series = []
        for index, point in enumerate(points[:4], start=1):
            numbers = re.findall(r"\b[\d,.]+[%$]?\b", point)
            value_token = (numbers[0] if numbers else str(index)).replace("$", "").replace("%", "")
            try:
                value = float(value_token.replace(",", ""))
            except ValueError:
                value = float(index)
            series.append({"label": f"Point {index}", "value": value})
        return {
            "headline": title,
            "template_id": template,
            "speaker_notes": "",
            "blocks": [
                {"kind": "chart", "chart_type": "bar", "series": series or [{"label": "Point 1", "value": 1.0}]},
                {"kind": "callout", "text": " ".join((sentences[:1] or points[:1]))[:160]},
            ],
        }

    if template in {"quote.photo", "quote.texture"}:
        quote_text = " ".join((sentences[:1] or points[:1]))[:180]
        blocks = [{"kind": "quote", "text": quote_text, "attribution": title}]
        if template == "quote.photo":
            blocks.append({"kind": "image", "text": "Photo"})
        return {"headline": title, "template_id": template, "speaker_notes": "", "blocks": blocks}

    if template == "impact.statement":
        return {"headline": title, "template_id": template, "speaker_notes": "", "blocks": [{"kind": "text", "text": " ".join((sentences[:1] or points[:1]))[:160]}]}

    if template in {"content.photo", "bold.photo", "screenshot"}:
        primary_block = (
            {"kind": "bullets", "items": bullets_from_points(4)}
            if template == "content.photo"
            else {"kind": "text", "text": " ".join((sentences[:1] or points[:1]))[:180]}
        )
        return {
            "headline": title,
            "template_id": template,
            "speaker_notes": "",
            "blocks": [primary_block, {"kind": "image", "text": "Image"}],
        }

    if template == "split.content":
        midpoint = max(1, (len(points) + 1) // 2)
        return {
            "headline": title,
            "template_id": template,
            "speaker_notes": "",
            "blocks": [
                {"kind": "text", "text": " ".join(points[:midpoint])[:180]},
                {"kind": "text", "text": " ".join(points[midpoint:])[:180] or "Add contrasting point"},
            ],
        }

    if template in {"timeline.roadmap", "process.steps"}:
        milestones = [s.strip() for s in re.split(r"[.\n]+", source_text) if s.strip()][:5]
        if template == "timeline.roadmap":
            items = [{"label": " ".join(s.split()[:8]).rstrip(",.;:"), "description": s} for s in milestones]
            return {"headline": title, "template_id": template, "speaker_notes": "", "blocks": [{"kind": "timeline", "items": items}]}
        steps = [{"number": i + 1, "title": " ".join(s.split()[:6]).rstrip(",.;:"), "description": s} for i, s in enumerate(milestones)]
        return {"headline": title, "template_id": template, "speaker_notes": "", "blocks": [{"kind": "steps", "steps": steps}]}

    if template == "matrix.2x2":
        quadrant_labels = [("tl", "Top Left"), ("tr", "Top Right"), ("bl", "Bottom Left"), ("br", "Bottom Right")]
        raw = [s.strip() for s in re.split(r"[.\n]+", source_text) if s.strip()][:4]
        quadrants = [
            {"quadrant": label, "title": " ".join(s.split()[:6]).rstrip(",.;:") if i < len(raw) else fallback,
             "items": [s] if i < len(raw) else []}
            for i, (label, fallback) in enumerate(quadrant_labels)
            for s in [raw[i] if i < len(raw) else ""]
        ]
        return {"headline": title, "template_id": template, "speaker_notes": "", "blocks": [{"kind": "matrix", "quadrants": quadrants}]}

    if template == "team.grid":
        raw = [s.strip() for s in re.split(r"[.\n]+", source_text) if s.strip()][:4]
        people = [{"name": " ".join(s.split()[:3]).rstrip(",.;:"), "title": " ".join(s.split()[3:6]).rstrip(",.;:") or "Team Member"} for s in raw]
        return {"headline": title, "template_id": template, "speaker_notes": "", "blocks": [{"kind": "people_cards", "people": people}]}

    if template == "financial.table":
        rows = [[f"Item {i + 1}", " ".join(point.split()[:10])] for i, point in enumerate(points[:8])]
        numbers_found = [re.search(r"[\d,.]+[%$MBK]?", p) for p in points[:8]]
        if any(numbers_found):
            rows = [
                [" ".join(point.split()[:6]).rstrip(",.;:"), m.group(0) if m else "—"]
                for point, m in zip(points[:8], numbers_found)
            ]
        return {
            "headline": title,
            "template_id": template,
            "speaker_notes": "",
            "blocks": [
                {"kind": "table", "columns": ["Item", "Value"], "rows": rows},
                {"kind": "text", "text": "Source: see attached"},
            ],
        }

    if template == "status.rag":
        raw = [s.strip() for s in re.split(r"[.\n]+", source_text) if s.strip()][:8]
        status_cycle = ["green", "amber", "red"]
        cards = [
            {"label": " ".join(s.split()[:8]).rstrip(",.;:"), "status": status_cycle[i % 3], "note": ""}
            for i, s in enumerate(raw)
        ]
        return {
            "headline": title,
            "template_id": template,
            "speaker_notes": "",
            "blocks": [{"kind": "status_cards", "cards": cards}],
        }

    if template == "dashboard.kpi":
        items: list[dict[str, str]] = []
        seen_labels: set[str] = set()
        for sentence in points[:6]:
            words = sentence.split()
            if not words:
                continue
            numbers = re.findall(r"\b[\d,.]+[%$MBK]?\b", sentence)
            label = " ".join(words[:5]).rstrip(",.;:")
            key = label.lower()
            if key in seen_labels:
                continue
            seen_labels.add(key)
            items.append({"label": label, "value": numbers[0] if numbers else "—", "delta": ""})
        return {"headline": title, "template_id": template, "speaker_notes": "", "blocks": [{"kind": "kpi_cards", "items": items}]}

    if template in {"title.cover", "section.divider"}:
        return {
            "headline": title,
            "template_id": template,
            "speaker_notes": "",
            "blocks": [{"kind": "text", "text": " ".join((sentences[:1] or points[:1]))[:160]}],
        }

    if template == "closing.actions":
        return {
            "headline": title,
            "template_id": template,
            "speaker_notes": "",
            "blocks": [{"kind": "bullets", "items": bullets_from_points(5)}],
        }

    return {
        "headline": title,
        "template_id": template,
        "speaker_notes": "",
        "blocks": [
            {"kind": "bullets", "items": bullets_from_points(5)},
            {"kind": "callout", "text": " ".join((sentences[:1] or points[:1]))[:160]},
        ],
    }


def _build_preview_slide(
    *,
    slide_id: str,
    purpose: SlidePurpose,
    headline: str,
    template_key: str,
    blocks_data: list[dict[str, Any]],
    speaker_notes: str,
) -> SlideSpec:
    """Build a SlideSpec from structured block data."""
    blocks: list[PresentationBlock] = []
    for i, block_data in enumerate(blocks_data):
        kind_str = block_data.get("kind", "text")
        try:
            kind = PresentationBlockKind(kind_str)
        except ValueError:
            kind = PresentationBlockKind.TEXT

        if kind == PresentationBlockKind.CALLOUT:
            if isinstance(block_data.get("cards"), list):
                content = {"cards": block_data.get("cards", [])}
            else:
                content = {"text": block_data.get("text", "")}
            if block_data.get("tone_hint"):
                content["tone_hint"] = block_data["tone_hint"]
        elif kind == PresentationBlockKind.BULLETS:
            content = {"items": block_data.get("items", [])}
        elif kind == PresentationBlockKind.KPI_CARDS:
            content = {"items": block_data.get("items", [])}
        elif kind == PresentationBlockKind.TABLE:
            content = {"columns": block_data.get("columns", []), "rows": block_data.get("rows", [])}
        elif kind == PresentationBlockKind.CHART:
            content = _preview_chart_content(block_data)
        elif kind == PresentationBlockKind.QUOTE:
            content = {"text": block_data.get("text", ""), "attribution": block_data.get("attribution", "")}
        elif kind == PresentationBlockKind.IMAGE:
            content = _preview_image_content(block_data)
        elif kind == PresentationBlockKind.TIMELINE:
            content = {"items": block_data.get("items", [])}
        elif kind == PresentationBlockKind.STEPS:
            content = {"steps": block_data.get("steps", [])}
        elif kind == PresentationBlockKind.PEOPLE_CARDS:
            content = {"people": block_data.get("people", [])}
        elif kind == PresentationBlockKind.MATRIX:
            content = {"quadrants": block_data.get("quadrants", [])}
        elif kind == PresentationBlockKind.STATUS_CARDS:
            content = {"cards": block_data.get("cards", [])}
        else:
            content = {"text": block_data.get("text", "")}

        blocks.append(PresentationBlock(
            block_id=f"b{i+1}",
            kind=kind,
            content=content,
        ))

    if not blocks:
        blocks.append(PresentationBlock(
            block_id="b1",
            kind=PresentationBlockKind.TEXT,
            content={"text": headline},
        ))

    return SlideSpec(
        slide_id=slide_id,
        purpose=purpose,
        layout_intent=LayoutIntent(template_key=template_key, strict_template=True),
        headline=headline,
        speaker_notes=speaker_notes,
        blocks=blocks,
    )


def _preview_chart_content(block_data: dict[str, Any]) -> dict[str, Any]:
    raw_points = block_data.get("data", block_data.get("series", []))
    points: list[dict[str, Any]] = []
    if isinstance(raw_points, list):
        for item in raw_points:
            if not isinstance(item, dict):
                continue
            label = str(item.get("label", "")).strip()
            value = item.get("value", 0)
            try:
                numeric_value = float(value)
            except (TypeError, ValueError):
                numeric_value = 0.0
            points.append({"label": label, "value": numeric_value})
    if not points:
        points = [{"label": "Point 1", "value": 1.0}]
    return {
        "chart_type": block_data.get("chart_type", "bar"),
        "series": points,
        "data": points,
        "title": block_data.get("title", ""),
        "x_label": block_data.get("x_label", ""),
        "y_label": block_data.get("y_label", ""),
        "path": block_data.get("path", ""),
    }


def _preview_image_content(block_data: dict[str, Any]) -> dict[str, Any]:
    content: dict[str, Any] = {"text": block_data.get("text", "Image")}
    for key in (
        "path",
        "local_path",
        "file_path",
        "asset_path",
        "uri",
        "query",
        "search_query",
        "image_query",
        "url",
    ):
        value = block_data.get(key)
        if isinstance(value, str) and value.strip():
            content[key] = value.strip()
    return content


def _infer_best_template_for_content(content: str) -> str:
    """Analyze content to choose the best slide template."""
    lowered = content.lower()
    word_count = len(content.split())

    # Detect comparison / multi-option content → cards
    if any(term in lowered for term in ("option", "vs.", "versus", "compare", "comparison", "alternative")):
        return "compare.2col"

    # Detect architecture / component descriptions → grid
    if any(term in lowered for term in ("component", "architecture", "pipeline", "module", "layer", "system")):
        return "exec.summary"

    # Detect metrics / numbers → KPI
    import re
    numbers = re.findall(r"\b\d+[%$]?\b", content)
    if len(numbers) >= 3:
        return "kpi.big"

    # Detect lists of 3+ distinct points → cards
    bullet_lines = [line for line in content.splitlines() if line.strip().startswith(("-", "•", "*", "1", "2", "3"))]
    if len(bullet_lines) >= 3:
        return "compare.2col"

    # Detect multiple paragraphs with distinct topics → executive overview
    paragraphs = [p.strip() for p in content.split("\n\n") if p.strip()]
    if len(paragraphs) >= 2 and word_count > 60:
        return "exec.summary"

    # Dense text → executive overview for summarization
    if word_count > 80:
        return "exec.summary"

    return "headline.evidence"


def _preview_archetype_for_template(template_key: str) -> SlideArchetype | None:
    if template_key == "exec.summary":
        return SlideArchetype.EXECUTIVE_SUMMARY
    if template_key == "compare.2col":
        return SlideArchetype.COMPARISON
    if template_key == "kpi.big":
        return SlideArchetype.METRICS
    if template_key == "chart.takeaway":
        return SlideArchetype.CHART
    return None


def _to_api_presentation_spec(
    stored: StoredDeck,
    *,
    spec_override: PresentationSpec | None = None,
) -> PresentationSpecResponse:
    """Derive a ``PresentationSpecResponse`` from the canonical ``StoredDeck``.

    Pass ``spec_override`` when the export path has merged user-edited slides
    into a modified ``PresentationSpec`` that should drive the response
    instead of the stored spec.
    """
    planning_spec = spec_override if spec_override is not None else stored.spec
    slides = [
        SlideSpecResponse(
            id=slide.slide_id,
            index=index,
            purpose=slide.purpose.value,
            archetype=slide.archetype.value if slide.archetype else None,
            title=slide.headline,
            blocks=[
                {
                    "id": block.block_id,
                    "kind": block.kind.value,
                    "content": _stringify_block_content(block.kind, block.content),
                    "data": block.content,
                    "citation": block.source_citations[0].locator if block.source_citations else None,
                }
                for block in slide.blocks
            ],
            template_id=slide.layout_intent.template_key,
            speaker_notes=slide.speaker_notes or None,
        )
        for index, slide in enumerate(planning_spec.slides, start=1)
    ]
    logo_present = any(
        slide.purpose is SlidePurpose.TITLE
        and any(block.content.get("logo") for block in slide.blocks)
        for slide in planning_spec.slides
    )
    return PresentationSpecResponse(
        id=stored.deck_id,
        doc_id=stored.doc_ids[0],
        doc_ids=stored.doc_ids,
        title=planning_spec.title,
        goal=stored.goal,
        audience=planning_spec.audience,
        slides=slides,
        created_at=stored.created_at,
        theme=ThemeSummaryResponse(
            name=planning_spec.theme.name,
            primary_color=planning_spec.theme.style_tokens.colors.accent,
            accent_color=planning_spec.theme.style_tokens.colors.muted,
            heading_font=planning_spec.theme.style_tokens.fonts.heading,
            body_font=planning_spec.theme.style_tokens.fonts.body,
            logo_present=logo_present,
        ),
    )


def _to_api_slide_spec(slide: SlideSpec, *, index: int) -> SlideSpecResponse:
    return SlideSpecResponse(
        id=slide.slide_id,
        index=index,
        purpose=slide.purpose.value,
        archetype=slide.archetype.value if slide.archetype else None,
        title=slide.headline,
        blocks=[
            {
                "id": block.block_id,
                "kind": block.kind.value,
                "content": _stringify_block_content(block.kind, block.content),
                "data": block.content,
                "citation": block.source_citations[0].locator if block.source_citations else None,
            }
            for block in slide.blocks
        ],
        template_id=slide.layout_intent.template_key,
        speaker_notes=slide.speaker_notes or None,
    )


def _stringify_block_content(kind: PresentationBlockKind, content: dict[str, Any]) -> str:
    text: str
    if kind is PresentationBlockKind.BULLETS:
        text = "\n".join(f"\u2022 {item}" for item in content.get("items", []))
    elif kind is PresentationBlockKind.KPI_CARDS:
        text = "\n".join(f"{item.get('value', '')}|{item.get('label', '')}" for item in content.get("items", []))
    elif kind is PresentationBlockKind.TABLE:
        text = "\n".join(" | ".join(str(cell) for cell in row) for row in content.get("rows", []))
    elif kind is PresentationBlockKind.CHART:
        text = "\n".join(f"{item.get('label', '')}: {item.get('value', '')}" for item in content.get("series", []))
    elif kind is PresentationBlockKind.CALLOUT and isinstance(content.get("cards"), list):
        text = "\n".join(f"{card.get('title', '')}: {card.get('text', '')}" for card in content["cards"])
    elif kind is PresentationBlockKind.TIMELINE:
        text = "\n".join(
            f"{item.get('date', '')}: {item.get('label') or item.get('title', '')}".strip(": ")
            for item in content.get("items", [])
        )
    elif kind is PresentationBlockKind.STEPS:
        text = "\n".join(
            f"{step.get('number', i + 1)}. {step.get('title', '')} — {step.get('description', '')}".rstrip(" —")
            for i, step in enumerate(content.get("steps", []))
        )
    elif kind is PresentationBlockKind.PEOPLE_CARDS:
        text = "\n".join(
            f"{p.get('name', '')} · {p.get('title', '')}"
            for p in content.get("people", [])
        )
    elif kind is PresentationBlockKind.MATRIX:
        text = "\n".join(
            f"[{q.get('quadrant', '').upper()}] {q.get('title', '')}: {', '.join(str(i) for i in q.get('items', []))}"
            for q in content.get("quadrants", [])
        )
    elif kind is PresentationBlockKind.STATUS_CARDS:
        text = "\n".join(
            f"[{c.get('status', '?').upper()}] {c.get('label', '')}"
            + (f" — {c['note']}" if c.get("note") else "")
            for c in content.get("cards", [])
        )
    else:
        text = ""
        for field in ("text", "label", "subtitle", "tagline", "footer_info", "logo"):
            if field in content and content[field]:
                text = str(content[field])
                break
        if not text:
            text = "\n".join(f"{key}: {value}" for key, value in content.items())
    return strip_markdown(text)


def _merge_export_slides(planning_spec: PresentationSpec, ui_slides: list[ExportSlideRequest] | None) -> PresentationSpec:
    if not ui_slides:
        return planning_spec

    existing_slides = {slide.slide_id: slide for slide in planning_spec.slides}
    source_ids = [citation.source_id for slide in planning_spec.slides for block in slide.blocks for citation in block.source_citations]
    fallback_source_id = source_ids[0] if source_ids else "ui-export"
    merged_slides = [
        _ui_slide_to_planning_slide(ui_slide, existing_slides.get(ui_slide.id), fallback_source_id)
        for ui_slide in sorted(ui_slides, key=lambda slide: slide.index)
    ]
    return planning_spec.model_copy(update={"slides": merged_slides})


def _ui_slide_to_planning_slide(
    ui_slide: ExportSlideRequest,
    existing_slide: SlideSpec | None,
    fallback_source_id: str,
) -> SlideSpec:
    raw_template_id = ui_slide.template_id.strip()
    template_key = canonical_template_key(raw_template_id)
    try:
        purpose = SlidePurpose(ui_slide.purpose)
    except ValueError:
        purpose = existing_slide.purpose if existing_slide else SlidePurpose.CONTENT

    archetype = existing_slide.archetype if existing_slide else None
    if ui_slide.archetype:
        try:
            archetype = SlideArchetype(ui_slide.archetype)
        except ValueError:
            pass

    existing_blocks = {block.block_id: block for block in existing_slide.blocks} if existing_slide else {}
    blocks = [
        _ui_block_to_planning_block(block, existing_blocks.get(block.id), fallback_source_id)
        for block in ui_slide.blocks
    ]
    if not blocks:
        blocks = [
            PresentationBlock(
                block_id=f"{ui_slide.id}-b1",
                kind=PresentationBlockKind.TEXT,
                content={"text": ui_slide.title},
            )
        ]

    headline, blocks = _canonicalize_export_slide(template_key, ui_slide.title, blocks, raw_template_id=raw_template_id)

    return SlideSpec(
        slide_id=ui_slide.id,
        purpose=purpose,
        archetype=archetype,
        layout_intent=LayoutIntent(template_key=template_key, strict_template=True),
        headline=headline,
        speaker_notes=ui_slide.speaker_notes or "",
        blocks=blocks,
    )


def _ui_block_to_planning_block(
    ui_block: ExportBlockRequest,
    existing_block: PresentationBlock | None,
    fallback_source_id: str,
) -> PresentationBlock:
    try:
        kind = PresentationBlockKind(ui_block.kind)
    except ValueError:
        kind = PresentationBlockKind.TEXT

    citations = existing_block.source_citations[:] if existing_block else []
    if ui_block.citation and not citations:
        source_id = ui_block.citation.split(":", 1)[0] if ":" in ui_block.citation else fallback_source_id
        citations = [SourceCitation(source_id=source_id or fallback_source_id, locator=ui_block.citation)]

    return PresentationBlock(
        block_id=ui_block.id,
        kind=kind,
        content=_ui_block_content(kind, ui_block),
        source_citations=citations,
        style_overrides=existing_block.style_overrides if existing_block else None,
        asset_refs=existing_block.asset_refs[:] if existing_block else [],
        x_security=existing_block.x_security if existing_block else None,
        extensions=existing_block.extensions if existing_block else None,
    )


def _ui_block_content(kind: PresentationBlockKind, ui_block: ExportBlockRequest) -> dict[str, Any]:
    text = ui_block.content or ""
    data = dict(ui_block.data) if isinstance(ui_block.data, dict) else {}

    if data and _should_preserve_ui_block_data(kind, data):
        return data

    # For text-native blocks, prefer the visible content when present so editor
    # edits cannot silently diverge from the exported slide.
    if not text.strip() and data:
        return data

    if not text.strip():
        return {"text": ""}
    if kind is PresentationBlockKind.BULLETS:
        items = [line.lstrip("-•* ").strip() for line in text.splitlines() if line.strip()]
        return {"items": items or [text.strip() or "Add content"]}
    if kind is PresentationBlockKind.KPI_CARDS:
        items = []
        for line in text.splitlines():
            raw = line.strip()
            if not raw:
                continue
            if "|" in raw:
                value, label = raw.split("|", 1)
            else:
                value, label = raw, ""
            items.append({"value": value.strip(), "label": label.strip()})
        return {"items": items or [{"value": "N/A", "label": text.strip() or "Metric"}]}
    if kind is PresentationBlockKind.TABLE:
        rows = [[cell.strip() for cell in line.split("|")] for line in text.splitlines() if line.strip()]
        if not rows:
            rows = [["Item", text.strip() or "Add detail"]]
        column_count = max(len(row) for row in rows)
        columns = [f"Column {index + 1}" for index in range(column_count)]
        normalized_rows = [row + [""] * (column_count - len(row)) for row in rows]
        return {"columns": columns, "rows": normalized_rows}
    if kind is PresentationBlockKind.CHART:
        series = []
        for line in text.splitlines():
            raw = line.strip()
            if not raw:
                continue
            if ":" in raw:
                label, value = raw.split(":", 1)
            else:
                label, value = raw, "1"
            try:
                parsed_value = float(value.strip().replace(",", "").replace("%", "").replace("$", ""))
            except ValueError:
                parsed_value = 1.0
            series.append({"label": label.strip(), "value": parsed_value})
        return {"chart_type": "bar", "series": series or [{"label": "Point 1", "value": 1.0}]}
    if kind is PresentationBlockKind.CALLOUT:
        cards = []
        for line in text.splitlines():
            raw = line.strip()
            if not raw:
                continue
            if ":" in raw:
                title, body = raw.split(":", 1)
                cards.append({"title": title.strip(), "text": body.strip()})
        if cards:
            return {"cards": cards}
        return {"text": text.strip()}
    if kind is PresentationBlockKind.QUOTE:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        return {"text": lines[0] if lines else text.strip(), "attribution": lines[1] if len(lines) > 1 else ""}
    if kind is PresentationBlockKind.IMAGE:
        return {"text": text.strip() or "Image"}
    return {"text": text.strip()}


def _should_preserve_ui_block_data(kind: PresentationBlockKind, data: dict[str, Any]) -> bool:
    asset_keys = {"local_path", "path", "file_path", "asset_path", "uri"}
    if any(isinstance(data.get(key), str) and data.get(key) for key in asset_keys):
        return True
    if kind in {PresentationBlockKind.TABLE, PresentationBlockKind.CHART, PresentationBlockKind.QUOTE}:
        return True
    if kind is PresentationBlockKind.CALLOUT and isinstance(data.get("cards"), list):
        return True
    return False


def _canonicalize_export_slide(
    template_key: str,
    headline: str,
    blocks: list[PresentationBlock],
    *,
    raw_template_id: str = "",
) -> tuple[str, list[PresentationBlock]]:
    canonical_blocks = blocks
    canonical_headline = headline

    if template_key in {"content.3col", "content.4col"}:
        target_count = 3 if template_key == "content.3col" else 4
        canonical_blocks = _expand_card_blocks(blocks, target_count)
    elif raw_template_id == "bold.photo" or template_key == "bold.photo":
        # bold.photo now redirects to impact.statement; retain the headline-extraction
        # behaviour so existing exports that used bold.photo still work correctly.
        statement = next((_extract_block_text(block) for block in blocks if block.kind is not PresentationBlockKind.IMAGE), "")
        if statement:
            canonical_headline = statement

    if template_key == "chart.takeaway" and len(canonical_blocks) >= 2:
        takeaway = canonical_blocks[1]
        if takeaway.kind is PresentationBlockKind.CALLOUT and isinstance(takeaway.content.get("cards"), list):
            canonical_blocks = [
                *canonical_blocks[:1],
                takeaway.model_copy(
                    update={
                        "content": {
                            "text": "\n".join(
                                f"{card.get('title', '').strip()}: {card.get('text', '').strip()}".strip(": ")
                                for card in takeaway.content["cards"]
                                if card.get("title") or card.get("text")
                            ).strip()
                        }
                    }
                ),
                *canonical_blocks[2:],
            ]

    return canonical_headline, canonical_blocks


def _expand_card_blocks(blocks: list[PresentationBlock], target_count: int) -> list[PresentationBlock]:
    if len(blocks) >= target_count:
        return blocks
    if not blocks:
        return blocks

    first_block = blocks[0]
    cards = first_block.content.get("cards")
    if first_block.kind is not PresentationBlockKind.CALLOUT or not isinstance(cards, list):
        return blocks

    # Only expand cards that actually have content. The UI renders empty
    # slots as dashed-border placeholders, so we deliberately stop short
    # of target_count rather than emit "Add supporting detail" filler.
    expanded_blocks: list[PresentationBlock] = []
    for index, card in enumerate(cards[:target_count]):
        if not isinstance(card, dict):
            continue
        title = str(card.get("title", "")).strip()
        body = str(card.get("text", "")).strip()
        text = "\n".join(part for part in (title, body) if part).strip()
        if not text:
            continue
        expanded_blocks.append(
            first_block.model_copy(
                update={
                    "block_id": f"{first_block.block_id}-card-{index + 1}",
                    "kind": PresentationBlockKind.TEXT,
                    "content": {"text": text},
                }
            )
        )
    return expanded_blocks


def _extract_block_text(block: PresentationBlock) -> str:
    return _stringify_block_content(block.kind, block.content).strip()


def _tone_label_from_score(score: float) -> str:
    if score >= 67:
        return "bold"
    if score <= 33:
        return "analytical"
    return "balanced"


def _build_alias_index() -> dict[str, str]:
    aliases: dict[str, str] = {}
    for alias, canonical in TEMPLATE_ALIASES.items():
        aliases.setdefault(canonical, alias)
    return aliases


def _humanize_template_name(template_key: str) -> str:
    return " ".join(part.capitalize() for part in template_key.replace(".", " ").replace("_", " ").split())


def _template_column_count(template_key: str) -> int:
    if ".3" in template_key or "3col" in template_key:
        return 3
    if ".2" in template_key or "2col" in template_key:
        return 2
    return 1


def _build_stub_pdf(deck_id: str) -> bytes:
    text = f"Auto-PPT export preview for {deck_id}"
    stream = f"BT /F1 18 Tf 40 120 Td ({_escape_pdf_text(text)}) Tj ET".encode("ascii")
    objects = [
        b"1 0 obj<< /Type /Catalog /Pages 2 0 R >>endobj",
        b"2 0 obj<< /Type /Pages /Kids [3 0 R] /Count 1 >>endobj",
        b"3 0 obj<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 180] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>endobj",
        b"4 0 obj<< /Length " + str(len(stream)).encode("ascii") + b" >>stream\n" + stream + b"\nendstream endobj",
        b"5 0 obj<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>endobj",
    ]
    parts = [b"%PDF-1.4\n"]
    offsets = [0]
    for obj in objects:
        offsets.append(sum(len(part) for part in parts))
        parts.append(obj + b"\n")
    xref_offset = sum(len(part) for part in parts)
    xref = [b"xref\n0 6\n0000000000 65535 f \n"]
    for offset in offsets[1:]:
        xref.append(f"{offset:010d} 00000 n \n".encode("ascii"))
    trailer = b"trailer<< /Size 6 /Root 1 0 R >>\nstartxref\n" + str(xref_offset).encode("ascii") + b"\n%%EOF"
    return b"".join(parts + xref + [trailer])


def _escape_pdf_text(value: str) -> str:
    return value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _serve_frontend_path(full_path: str) -> Response:
    if not WEB_INDEX.exists():
        _raise_api_error(404, 'frontend_build_not_found', 'Frontend build not found. Run `npm run build` in ui/.')

    requested = (WEB_DIR / full_path).resolve()
    try:
        requested.relative_to(WEB_DIR.resolve())
    except ValueError as exc:
        raise HTTPException(status_code=404, detail={'code': 'invalid_frontend_path', 'message': 'Invalid frontend path.'}) from exc

    if full_path and requested.exists() and requested.is_file():
        response = FileResponse(requested)
        response.headers["Cache-Control"] = "no-store"
        return response
    response = FileResponse(WEB_INDEX)
    response.headers["Cache-Control"] = "no-store"
    return response


_PREVIEW_ASSET_SAFE_ROOTS: tuple[Path, ...] = (
    (REPO_ROOT / "out" / "runtime_assets").resolve(),
    (REPO_ROOT / "out" / "tmp").resolve(),
    (REPO_ROOT / "Input" / "Assets").resolve(),
)


def _resolve_local_preview_asset(asset_path: str) -> Path:
    candidate = asset_path.strip()
    if not candidate:
        _raise_api_error(404, "asset_not_found", "Preview asset path is required.")

    parsed = urlparse(candidate)
    if parsed.scheme in {"http", "https"}:
        _raise_api_error(400, "invalid_asset_path", "Remote asset URLs are not allowed.")

    # Resolve to an absolute path. expanduser() is intentionally omitted — there
    # is no legitimate reason for a preview path to reference a home directory.
    raw = Path(candidate)
    if raw.is_absolute():
        requested = raw.resolve()
    else:
        requested = (REPO_ROOT / raw).resolve()

    # Enforce directory boundary: the resolved path must sit inside one of the
    # known safe roots. This blocks path-traversal attacks like
    # GET /api/assets/local?path=../../../../.env
    if not any(requested.is_relative_to(root) for root in _PREVIEW_ASSET_SAFE_ROOTS):
        _raise_api_error(403, "forbidden_asset_path", "Asset path is outside the allowed directories.")

    if not requested.exists() or not requested.is_file():
        _raise_api_error(404, "asset_not_found", f"Preview asset not found: {requested.name}")

    allowed_suffixes = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg"}
    if requested.suffix.lower() not in allowed_suffixes:
        guessed, _ = mimetypes.guess_type(str(requested))
        if not (guessed and guessed.startswith("image/")):
            _raise_api_error(400, "invalid_asset_type", "Only image assets can be previewed.")

    return requested


_ALIAS_BY_CANONICAL = _build_alias_index()


def _infer_chat_brief(
    prompt: str,
    default_title: str,
    *,
    content_chunk_count: int = 0,
    source_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    lowered = prompt.lower()
    source_context = source_context or {}

    # Dynamic default based on document size — more content means more slides.
    # Each content slide typically covers ~8-12 chunks of source material.
    if str(source_context.get("source_format", "")).lower() == "pptx" and source_context.get("slide_count"):
        slide_count = max(1, min(40, int(source_context["slide_count"])))
    elif content_chunk_count > 0:
        slide_count = max(6, min(20, 4 + content_chunk_count // 10))
    else:
        slide_count = 6

    # Explicit user request ("12 slides") overrides the dynamic default.
    count_match = next((match for match in re.finditer(r"(\d+)\s+slides?", lowered)), None)
    if count_match is not None:
        slide_count = max(1, min(40, int(count_match.group(1))))

    audience = "Executive audience"
    for marker in ("for ", "to "):
        if marker in lowered:
            fragment = prompt[lowered.index(marker) + len(marker):].split(".")[0].split(",")[0]
            if fragment.strip():
                audience = fragment.strip().rstrip()
                break
    if "oracle" in lowered and "consult" in lowered:
        audience = "Oracle consultants"

    tone = 50.0
    if any(term in lowered for term in ("board", "analytical", "technical", "consultants")):
        tone = 25.0
    if any(term in lowered for term in ("bold", "sales", "investor", "pitch")):
        tone = 80.0

    goal = prompt.strip()
    if len(goal.split()) > 12:
        goal = " ".join(goal.split()[:12])
    if not goal:
        goal = f"Present {default_title}"

    selected_template_id = "compare.2col" if any(term in lowered for term in ("architecture", "pipeline", "overview", "components")) else "headline.evidence"
    return {
        "goal": goal,
        "audience": audience,
        "tone": tone,
        "slide_count": slide_count,
        "selected_template_id": selected_template_id,
    }
