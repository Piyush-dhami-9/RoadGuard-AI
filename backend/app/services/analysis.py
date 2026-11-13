"""The image-to-inspection pipeline: decode, detect, score, store. CPU-bound; call from a worker thread."""
from dataclasses import dataclass
from pathlib import Path
from ..models import Damage, Inspection
from .images import decode_upload, save_inspection_images
from .inference import InferenceService
from .severity import assess, level_for, priority


@dataclass
class AnalysisResult:
    inspection: Inspection
    files: tuple[Path, Path]


def analyze_upload(content: bytes, inference: InferenceService) -> AnalysisResult:
    image = decode_upload(content)
    detections, overlay = inference.detect(image)
    surface_area = float(image.shape[0] * image.shape[1])
    scored = [assess(d.area, d.width, d.length, surface_area) for d in detections]
    max_score = max((item.score for item in scored), default=0)
    top_confidence = max((d.confidence for d in detections), default=0)
    image_path, annotated_path = save_inspection_images(image, overlay)
    status = inference.status
    inspection = Inspection(
        image_path=str(image_path),
        annotated_image_path=str(annotated_path),
        damage_count=len(detections),
        overall_severity=level_for(max_score),
        priority_score=priority(max_score, top_confidence, len(detections)),
        inference_mode=status.mode,
        model_name=status.model_name,
        model_version=status.model_version,
    )
    inspection.damages = [
        Damage(class_name=d.class_name, confidence=d.confidence, area=d.area, length=d.length, width=d.width, severity=result.level, severity_score=result.score, bbox=d.bbox)
        for d, result in zip(detections, scored)
    ]
    return AnalysisResult(inspection, (image_path, annotated_path))
