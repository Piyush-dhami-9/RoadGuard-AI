"""The image-to-inspection pipeline: decode, detect, score, store. CPU-bound; call from a worker thread."""
from dataclasses import dataclass
from pathlib import Path
from ..models import Damage, Inspection
from .images import decode_upload, save_inspection_images
from .inference import InferenceService
from .severity import assess_damage, assess_inspection, coverage, priority


@dataclass
class AnalysisResult:
    inspection: Inspection
    files: tuple[Path, Path]


def analyze_upload(content: bytes, inference: InferenceService) -> AnalysisResult:
    image = decode_upload(content)
    height, width = image.shape[:2]
    detections, annotated = inference.detect(image)
    scored = [assess_damage(d.class_name, d.bbox["x2"] - d.bbox["x1"], d.bbox["y2"] - d.bbox["y1"], width, height) for d in detections]
    overall = assess_inspection([item.score for item in scored], coverage([d.bbox for d in detections], width, height))
    worst = max(zip(scored, detections), key=lambda pair: pair[0].score, default=None)
    image_path, annotated_path = save_inspection_images(image, annotated)
    status = inference.status
    inspection = Inspection(
        image_path=str(image_path),
        annotated_image_path=str(annotated_path),
        damage_count=len(detections),
        overall_severity=overall.level,
        priority_score=priority(overall.score, worst[1].confidence) if worst else 0.0,
        inference_mode=status.mode,
        model_name=status.model_name,
        model_version=status.model_version,
    )
    inspection.damages = [
        Damage(class_name=d.class_name, confidence=d.confidence, area=d.area, length=d.length, width=d.width, severity=result.level, severity_score=result.score, bbox=d.bbox)
        for d, result in zip(detections, scored)
    ]
    return AnalysisResult(inspection, (image_path, annotated_path))
