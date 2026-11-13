"""YOLO11 object detection: loading the weights once and turning model output into detections."""
import json
import logging
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any
import numpy as np
from .damage_classes import CLASS_NAMES, class_table_matches

logger = logging.getLogger(__name__)
MIN_BOX_PIXELS = 1.0


class ModelLoadError(Exception):
    """The weights cannot be used. The message is safe to show to an operator."""


@dataclass
class Detection:
    class_id: int | None
    class_name: str
    confidence: float
    bbox: dict[str, float]  # x1, y1, x2, y2 in image pixels
    area: float             # region area in image pixels (bounding-box area for YOLO detections)
    length: float           # long side of the bounding box, image pixels
    width: float            # short side of the bounding box, image pixels


def load_ultralytics_model(weights_path: Path) -> Any:
    from ultralytics import YOLO
    return YOLO(str(weights_path))


def resolve_device(requested: str) -> str:
    """'auto' picks CUDA, then Apple MPS, then CPU, from what this machine has. Anything else is used as given."""
    if requested != "auto":
        return requested
    import torch
    if torch.cuda.is_available():
        return "cuda:0"
    if getattr(torch.backends, "mps", None) is not None and torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def smoke_test_record(weights_path: Path) -> bool:
    """True when the training pipeline marked these weights as a smoke test (pipeline check, not a trained model)."""
    for record in (weights_path.with_suffix(".json"), weights_path.parent.parent / "training_summary.json"):
        try:
            if record.is_file() and json.loads(record.read_text()).get("smoke_test") is True:
                return True
        except (OSError, ValueError, AttributeError):
            continue
    return False


def _values(tensor: Any) -> list:
    return tensor.tolist() if tensor is not None else []


def extract_detections(result: Any, class_names: dict[int, str], confidence_threshold: float, image_shape: tuple[int, ...]) -> list[Detection]:
    """Bounding boxes, class and confidence from one Ultralytics result, most confident first.

    Boxes below the confidence threshold, with an unknown class, or with no
    area inside the image are left out. Coordinates are clipped to the image.
    """
    boxes = getattr(result, "boxes", None)
    if boxes is None:
        return []
    height, width = image_shape[:2]
    detections: list[Detection] = []
    for (x1, y1, x2, y2), confidence, class_value in zip(_values(boxes.xyxy), _values(boxes.conf), _values(boxes.cls)):
        class_id = int(class_value)
        if confidence < confidence_threshold:
            continue
        if class_id not in class_names:
            logger.warning("Ignoring a detection with unknown class id %s", class_id)
            continue
        x1, x2 = sorted((min(max(x1, 0.0), float(width)), min(max(x2, 0.0), float(width))))
        y1, y2 = sorted((min(max(y1, 0.0), float(height)), min(max(y2, 0.0), float(height))))
        box_width, box_height = x2 - x1, y2 - y1
        if box_width < MIN_BOX_PIXELS or box_height < MIN_BOX_PIXELS:
            continue
        detections.append(Detection(
            class_id=class_id,
            class_name=class_names[class_id],
            confidence=round(float(confidence), 4),
            bbox={"x1": round(x1, 1), "y1": round(y1, 1), "x2": round(x2, 1), "y2": round(y2, 1)},
            area=round(box_width * box_height, 1),
            length=round(max(box_width, box_height), 1),
            width=round(min(box_width, box_height), 1),
        ))
    return sorted(detections, key=lambda item: item.confidence, reverse=True)


class YoloDetector:
    """A YOLO11 detection model, loaded once and reused for every request."""

    def __init__(self, weights_path: Path, device: str = "auto", confidence_threshold: float = 0.25, image_size: int = 640):
        if not weights_path.is_file():
            raise ModelLoadError(f"No weights file exists at {weights_path}.")
        if smoke_test_record(weights_path):
            raise ModelLoadError(f"{weights_path} comes from a smoke-test run. Smoke-test weights only prove the training pipeline runs; they are not a trained model.")
        try:
            model = load_ultralytics_model(weights_path)
        except ImportError as error:
            raise ModelLoadError(f"The 'ultralytics' package is not installed in this environment ({error}). Install it, or build the Docker image with INSTALL_MODEL_DEPS=true.") from error
        except Exception as error:
            logger.exception("Could not load model weights from %s", weights_path)
            raise ModelLoadError(f"{weights_path} is not a loadable Ultralytics model ({type(error).__name__}: {error}).") from error
        task = getattr(model, "task", None)
        if task != "detect":
            raise ModelLoadError(f"{weights_path} is a '{task}' model. RoadGuard needs YOLO11 object-detection weights.")
        names = getattr(model, "names", None)
        if not class_table_matches(names):
            found = len(names) if hasattr(names, "__len__") else "unknown"
            raise ModelLoadError(f"{weights_path} was not trained on RoadGuard's classes: expected {CLASS_NAMES}, found {found} classes. A generic pretrained checkpoint is not a road-damage model.")
        try:
            self.device = resolve_device(device)
        except Exception as error:
            raise ModelLoadError(f"Could not select an inference device ({type(error).__name__}: {error}).") from error
        self.model = model
        self.task = task
        self.class_names = dict(CLASS_NAMES)
        self.confidence_threshold = confidence_threshold
        self.image_size = image_size
        self._lock = threading.Lock()  # one prediction at a time: the Ultralytics predictor is not thread-safe
        try:
            self.predict(np.zeros((64, 64, 3), np.uint8))
        except Exception as error:
            logger.exception("Model loaded from %s but failed a test prediction", weights_path)
            raise ModelLoadError(f"{weights_path} loaded but failed a test prediction on device '{self.device}' ({type(error).__name__}: {error}).") from error

    def predict(self, image: np.ndarray) -> list[Detection]:
        with self._lock:
            results = self.model.predict(source=image, conf=self.confidence_threshold, imgsz=self.image_size, device=self.device, verbose=False)
        return extract_detections(results[0], self.class_names, self.confidence_threshold, image.shape)
