import logging
from contextlib import asynccontextmanager
from pathlib import Path
import cv2
import numpy as np
from fastapi import Depends, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from .core.config import settings
from .db import get_session, init_db
from .models import Damage, Inspection
from .schemas import InspectionResponse
from .services.inference import InferenceService
from .services.report import create_report
from .services.severity import assess, priority

logging.basicConfig(level=logging.INFO)
inference = InferenceService(settings.model_weights)

@asynccontextmanager
async def lifespan(_: FastAPI):
    await init_db()
    yield

app = FastAPI(title="RoadGuard AI API", version="1.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=settings.origins, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

@app.get("/health")
async def health():
    return {"status": "ok", "inference_mode": "yolo11-segmentation" if inference.model else "opencv-demo-fallback"}

@app.post("/detect", response_model=InspectionResponse)
async def detect(file: UploadFile = File(...), session: AsyncSession = Depends(get_session)):
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(415, "Please upload an image file")
    content = await file.read()
    image = cv2.imdecode(np.frombuffer(content, np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise HTTPException(400, "The image could not be decoded")
    file_name = f"{__import__('uuid').uuid4().hex}.jpg"
    image_path = settings.upload_dir / file_name
    cv2.imwrite(str(image_path), image)
    detections, overlay = inference.detect(image)
    annotated_path = settings.upload_dir / f"annotated-{file_name}"
    cv2.imwrite(str(annotated_path), overlay)
    surface_area = float(image.shape[0] * image.shape[1])
    scored = [assess(d.area, d.width, d.length, surface_area) for d in detections]
    max_score = max((item.score for item in scored), default=0)
    overall = "High" if max_score > 70 else "Medium" if max_score > 30 else "Low"
    record = Inspection(image_path=str(image_path), annotated_image_path=str(annotated_path), damage_count=len(detections), overall_severity=overall, priority_score=priority(max_score, max((d.confidence for d in detections), default=0), len(detections)))
    record.damages = [Damage(class_name=d.class_name, confidence=d.confidence, area=d.area, length=d.length, width=d.width, severity=result.level, severity_score=result.score, bbox=d.bbox) for d, result in zip(detections, scored)]
    session.add(record)
    await session.commit()
    result = await session.execute(select(Inspection).options(selectinload(Inspection.damages)).where(Inspection.id == record.id))
    return result.scalar_one()

@app.get("/inspections", response_model=list[InspectionResponse])
async def inspections(session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(Inspection).options(selectinload(Inspection.damages)).order_by(Inspection.timestamp.desc()))
    return list(result.scalars().all())

@app.get("/inspection/{inspection_id}", response_model=InspectionResponse)
async def inspection(inspection_id: int, session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(Inspection).options(selectinload(Inspection.damages)).where(Inspection.id == inspection_id))
    record = result.scalar_one_or_none()
    if record is None:
        raise HTTPException(404, "Inspection not found")
    return record

@app.delete("/inspection/{inspection_id}")
async def delete_inspection(inspection_id: int, session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(Inspection).options(selectinload(Inspection.damages)).where(Inspection.id == inspection_id))
    record = result.scalar_one_or_none()
    if record is None:
        raise HTTPException(404, "Inspection not found")
    await session.delete(record)
    await session.commit()
    return {"deleted": inspection_id}

@app.post("/report/{inspection_id}")
async def report(inspection_id: int, session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(Inspection).options(selectinload(Inspection.damages)).where(Inspection.id == inspection_id))
    record = result.scalar_one_or_none()
    if record is None:
        raise HTTPException(404, "Inspection not found")
    path = create_report(record)
    return FileResponse(path, media_type="application/pdf", filename=path.name)
