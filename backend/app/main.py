import logging
from contextlib import asynccontextmanager
from dataclasses import asdict
from typing import Literal
from fastapi import Depends, FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from .core.config import settings
from .db import database_is_reachable, get_session, init_db
from .models import Inspection
from .schemas import DeleteResponse, ErrorResponse, HealthResponse, InspectionResponse
from .services.analysis import analyze_upload
from .services.images import UploadRejected, remove_files, stored_file
from .services.inference import InferenceService, ModelUnavailableError
from .services.report import create_report

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("roadguard")
inference = InferenceService(settings.weights_path, settings.inference_mode, settings.app_env, settings.inference_device,
                             settings.confidence_threshold, settings.inference_image_size)
# Multipart framing adds a little to the file itself; nginx is configured to the same total.
MAX_BODY_BYTES = settings.max_upload_bytes + 1024 * 1024
NOT_FOUND = {404: {"model": ErrorResponse, "description": "Inspection not found"}}


class BodySizeLimitMiddleware:
    """Refuse oversized request bodies before they are buffered to memory or disk."""

    def __init__(self, app, max_bytes: int):
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] not in ("POST", "PUT", "PATCH"):
            return await self.app(scope, receive, send)
        too_large = HTTPException(413, f"The image exceeds the {settings.max_upload_mb} MB upload limit")
        declared = dict(scope["headers"]).get(b"content-length", b"")
        if declared.isdigit() and int(declared) > self.max_bytes:
            return await JSONResponse({"detail": too_large.detail}, status_code=413)(scope, receive, send)
        received = 0

        async def limited_receive():
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    raise too_large
            return message

        await self.app(scope, limited_receive, send)


@asynccontextmanager
async def lifespan(_: FastAPI):
    await init_db()
    yield


app = FastAPI(
    title="RoadGuard AI API",
    version="1.1.0",
    lifespan=lifespan,
    description="Road-surface inspection API. Every inspection records whether it was produced by a trained model or by the DEMO placeholder detector. Severity values are estimated indicators from image-space measurements, not certified engineering assessments.",
)
app.add_middleware(BodySizeLimitMiddleware, max_bytes=MAX_BODY_BYTES)
app.add_middleware(CORSMiddleware, allow_origins=settings.origins, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])


@app.exception_handler(UploadRejected)
async def upload_rejected(_: Request, error: UploadRejected) -> JSONResponse:
    return JSONResponse({"detail": error.detail}, status_code=error.status_code)


@app.exception_handler(ModelUnavailableError)
async def model_unavailable(_: Request, error: ModelUnavailableError) -> JSONResponse:
    return JSONResponse({"detail": f"Inspection is unavailable: {error}"}, status_code=503)


@app.exception_handler(Exception)
async def unexpected_error(request: Request, error: Exception) -> JSONResponse:
    logger.exception("Unhandled error on %s %s", request.method, request.url.path, exc_info=error)
    return JSONResponse({"detail": "Internal server error"}, status_code=500)


async def get_inspection_or_404(inspection_id: int, session: AsyncSession = Depends(get_session)) -> Inspection:
    result = await session.execute(select(Inspection).options(selectinload(Inspection.damages)).where(Inspection.id == inspection_id))
    record = result.scalar_one_or_none()
    if record is None:
        raise HTTPException(404, "Inspection not found")
    return record


@app.get("/health", response_model=HealthResponse, tags=["system"], summary="Service, database and model status",
         responses={503: {"model": HealthResponse, "description": "The database is unreachable"}})
async def health():
    database_ok = await database_is_reachable()
    status = inference.status
    body = HealthResponse(
        status="ok" if database_ok and status.mode != "unavailable" else "degraded",
        database="ok" if database_ok else "unavailable",
        inference_mode=status.mode,
        model=asdict(status),
        max_upload_mb=settings.max_upload_mb,
    )
    return JSONResponse(body.model_dump(), status_code=200 if database_ok else 503)


@app.post("/detect", response_model=InspectionResponse, tags=["inspections"], summary="Upload a road image and store its inspection",
          responses={400: {"model": ErrorResponse, "description": "Empty, corrupt, too small or oversized image"},
                     413: {"model": ErrorResponse, "description": "Upload exceeds the size limit"},
                     415: {"model": ErrorResponse, "description": "Not a JPEG, PNG or WebP image"},
                     503: {"model": ErrorResponse, "description": "A trained model is required but unavailable"}})
async def detect(file: UploadFile = File(..., description="JPEG, PNG or WebP road image"), session: AsyncSession = Depends(get_session)):
    """The file type is determined from its content. `inference_mode` in the response states whether the result is `demo` or `trained`."""
    content = await file.read(settings.max_upload_bytes + 1)
    result = await run_in_threadpool(analyze_upload, content, inference)
    record = result.inspection
    try:
        session.add(record)
        await session.commit()
    except Exception:
        await session.rollback()
        remove_files(*result.files)
        raise
    logger.info("Inspection %s stored: mode=%s damages=%s severity=%s", record.id, record.inference_mode, record.damage_count, record.overall_severity)
    return record


@app.get("/inspections", response_model=list[InspectionResponse], tags=["inspections"], summary="Inspection history, newest first")
async def inspections(limit: int = Query(200, ge=1, le=500), offset: int = Query(0, ge=0), session: AsyncSession = Depends(get_session)):
    query = select(Inspection).options(selectinload(Inspection.damages)).order_by(Inspection.timestamp.desc(), Inspection.id.desc()).limit(limit).offset(offset)
    return list((await session.execute(query)).scalars().all())


@app.get("/inspection/{inspection_id}", response_model=InspectionResponse, tags=["inspections"], summary="One inspection with its damage items", responses=NOT_FOUND)
async def inspection(record: Inspection = Depends(get_inspection_or_404)):
    return record


@app.get("/inspection/{inspection_id}/image/{kind}", tags=["inspections"], summary="The original or annotated image of an inspection",
         response_class=FileResponse, responses={200: {"content": {"image/jpeg": {}}}, **NOT_FOUND})
async def inspection_image(kind: Literal["original", "annotated"], record: Inspection = Depends(get_inspection_or_404)):
    path = stored_file(record.annotated_image_path if kind == "annotated" else record.image_path)
    if path is None:
        raise HTTPException(404, "The image file is no longer available")
    return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=3600"})


@app.delete("/inspection/{inspection_id}", response_model=DeleteResponse, tags=["inspections"], summary="Delete an inspection and its stored images", responses=NOT_FOUND)
async def delete_inspection(inspection_id: int, record: Inspection = Depends(get_inspection_or_404), session: AsyncSession = Depends(get_session)):
    files = (stored_file(record.image_path), stored_file(record.annotated_image_path))
    await session.delete(record)
    await session.commit()
    remove_files(*files)
    logger.info("Inspection %s deleted", inspection_id)
    return {"deleted": inspection_id}


REPORT_DOCS = dict(tags=["reports"], summary="Download the PDF report of an inspection", response_class=Response,
                   responses={200: {"content": {"application/pdf": {}}}, **NOT_FOUND})


@app.get("/report/{inspection_id}", **REPORT_DOCS)
@app.post("/report/{inspection_id}", **REPORT_DOCS)
async def report(inspection_id: int, record: Inspection = Depends(get_inspection_or_404)):
    """GET is the download link; POST is kept for existing clients."""
    pdf = await run_in_threadpool(create_report, record)
    return Response(pdf, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="roadguard-inspection-{inspection_id}.pdf"'})
