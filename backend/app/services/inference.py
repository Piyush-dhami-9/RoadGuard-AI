import hashlib
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any
import cv2
import numpy as np

logger = logging.getLogger(__name__)
CLASSES = ["Pothole", "Longitudinal Crack", "Transverse Crack", "Alligator Crack"]
DEMO_MODEL_NAME = "opencv-threshold-demo"
DEMO_MODEL_VERSION = "1"
DEMO_BANNER = "DEMO - PLACEHOLDER DETECTOR, NOT AN AI PREDICTION"


class ModelUnavailableError(RuntimeError):
    """A trained model is required but could not be used."""


@dataclass(frozen=True)
class ModelStatus:
    mode: str  # "demo" | "trained" | "unavailable"
    model_name: str | None
    model_version: str | None
    detail: str


def load_yolo(weights_path: Path) -> Any:
    from ultralytics import YOLO
    return YOLO(str(weights_path))


def weights_fingerprint(weights_path: Path) -> str:
    digest = hashlib.sha256()
    with weights_path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()[:12]


@dataclass
class Detection:
    class_name: str
    confidence: float
    bbox: dict[str, float]
    area: float
    length: float
    width: float
    mask: np.ndarray


class InferenceService:
    def __init__(self, weights: str, mode: str = "auto", app_env: str = "development"):
        self.model: Any = None
        self.status = self._initialise(Path(weights), mode, app_env)
        log = logger.error if self.status.mode == "unavailable" else logger.info
        log("Inference mode: %s (%s)", self.status.mode.upper(), self.status.detail)

    def _initialise(self, weights_path: Path, mode: str, app_env: str) -> ModelStatus:
        demo = lambda reason: ModelStatus("demo", DEMO_MODEL_NAME, DEMO_MODEL_VERSION, f"{reason}. Results come from a brightness-threshold placeholder, not a trained model.")
        unavailable = lambda reason: ModelStatus("unavailable", None, None, reason)
        if mode == "demo":
            return demo("Demo mode selected with INFERENCE_MODE=demo")
        if not weights_path.is_file():
            if mode == "auto" and app_env != "production":
                return demo(f"No trained weights found at {weights_path}")
            return unavailable(f"A trained model is required but no weights file exists at {weights_path}. Set INFERENCE_MODE=demo to run the placeholder detector deliberately.")
        # Weights were supplied: from here on a failure is reported, never papered over with demo output.
        try:
            model = load_yolo(weights_path)
        except Exception as error:
            logger.exception("Could not load model weights from %s", weights_path)
            return unavailable(f"Weights at {weights_path} failed to load ({type(error).__name__}: {error})")
        task = getattr(model, "task", None)
        if task != "segment":
            return unavailable(f"Weights at {weights_path} are a '{task}' model; the current pipeline only supports segmentation weights.")
        self.model = model
        return ModelStatus("trained", weights_path.name, weights_fingerprint(weights_path), f"Trained YOLO {task} model loaded from {weights_path}")

    def detect(self, image: np.ndarray) -> tuple[list[Detection], np.ndarray]:
        if self.status.mode == "unavailable":
            raise ModelUnavailableError(self.status.detail)
        if self.model is not None:
            return self._yolo(image)
        detections, overlay = self._demo(image)
        return detections, self._stamp_demo_banner(overlay)

    @staticmethod
    def _stamp_demo_banner(overlay: np.ndarray) -> np.ndarray:
        height, width = overlay.shape[:2]
        scale = max(0.35, width / 1500)
        thickness = max(1, round(scale * 2))
        (_, text_height), baseline = cv2.getTextSize(DEMO_BANNER, cv2.FONT_HERSHEY_SIMPLEX, scale, thickness)
        band = min(height, text_height + baseline + round(14 * scale) + 6)
        cv2.rectangle(overlay, (0, 0), (width, band), (30, 30, 200), -1)
        cv2.putText(overlay, DEMO_BANNER, (8, band - baseline - 4), cv2.FONT_HERSHEY_SIMPLEX, scale, (255, 255, 255), thickness, cv2.LINE_AA)
        return overlay

    def _yolo(self, image: np.ndarray) -> tuple[list[Detection], np.ndarray]:
        result = self.model(image, verbose=False)[0]
        detections: list[Detection] = []
        overlay = image.copy()
        masks = result.masks.data.cpu().numpy() if result.masks is not None else []
        for index, box in enumerate(result.boxes):
            x1, y1, x2, y2 = box.xyxy[0].tolist()
            mask = cv2.resize((masks[index] > 0.5).astype(np.uint8), (image.shape[1], image.shape[0])) if index < len(masks) else np.zeros(image.shape[:2], np.uint8)
            detections.append(Detection(CLASSES[int(box.cls)], float(box.conf), {"x1": x1, "y1": y1, "x2": x2, "y2": y2}, float(mask.sum()), float(max(x2-x1, y2-y1)), float(min(x2-x1, y2-y1)), mask))
            overlay[mask > 0] = (overlay[mask > 0] * 0.55 + np.array([35, 160, 240]) * 0.45).astype(np.uint8)
            cv2.rectangle(overlay, (int(x1), int(y1)), (int(x2), int(y2)), (35, 160, 240), 2)
        return detections, overlay

    def _demo(self, image: np.ndarray) -> tuple[list[Detection], np.ndarray]:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        dark = cv2.threshold(gray, 88, 255, cv2.THRESH_BINARY_INV)[1]
        kernel = np.ones((9, 9), np.uint8)
        mask = cv2.morphologyEx(dark, cv2.MORPH_OPEN, kernel)
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        overlay = image.copy()
        detections: list[Detection] = []
        minimum = max(300, image.shape[0] * image.shape[1] * 0.004)
        for index, contour in enumerate(sorted(contours, key=cv2.contourArea, reverse=True)[:4]):
            area = cv2.contourArea(contour)
            if area < minimum:
                continue
            x, y, w, h = cv2.boundingRect(contour)
            candidate_mask = np.zeros(gray.shape, np.uint8)
            cv2.drawContours(candidate_mask, [contour], -1, 1, -1)
            class_name = CLASSES[index % len(CLASSES)]
            detection = Detection(class_name, round(min(0.96, 0.62 + area / (image.shape[0] * image.shape[1])), 2), {"x1": x, "y1": y, "x2": x+w, "y2": y+h}, area, float(max(w, h)), float(min(w, h)), candidate_mask)
            detections.append(detection)
            color = (44, 190, 246) if index % 2 == 0 else (245, 142, 55)
            overlay[candidate_mask > 0] = (overlay[candidate_mask > 0] * 0.5 + np.array(color) * 0.5).astype(np.uint8)
            cv2.rectangle(overlay, (x, y), (x+w, y+h), color, 3)
            cv2.putText(overlay, f"{class_name} {detection.confidence:.0%}", (x, max(25, y-8)), cv2.FONT_HERSHEY_SIMPLEX, 0.65, color, 2)
        return detections, overlay
