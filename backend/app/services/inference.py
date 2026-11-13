"""Chooses and runs the detector: the trained YOLO11 model, or the labelled DEMO placeholder.

The two are never swapped silently. If YOLO is selected and its weights cannot
be used, the service is 'unavailable' and says why; it does not produce demo output.
"""
import hashlib
import logging
from dataclasses import dataclass, field
from pathlib import Path
import cv2
import numpy as np
from .annotation import draw_detections
from .damage_classes import CLASS_IDS, CLASS_NAMES
from .yolo_detector import Detection, ModelLoadError, YoloDetector

logger = logging.getLogger(__name__)
# The placeholder hands out class names in this fixed rotation; it does not recognise anything.
DEMO_CLASS_CYCLE = ["Pothole", "Longitudinal Crack", "Transverse Crack", "Alligator Crack"]
DEMO_MODEL_NAME = "opencv-threshold-demo"
DEMO_MODEL_VERSION = "1"
DEMO_BANNER = "DEMO - PLACEHOLDER DETECTOR, NOT AN AI PREDICTION"
YOLO_MODES = ("yolo", "trained")  # 'trained' is the earlier name for the same setting


class ModelUnavailableError(RuntimeError):
    """A trained model is required but could not be used."""


@dataclass(frozen=True)
class ModelStatus:
    mode: str                      # what results are produced by: "demo" | "trained" | "unavailable"
    model_name: str | None
    model_version: str | None
    detail: str
    configured_mode: str = "auto"  # the INFERENCE_MODE setting as given
    loaded: bool = False           # True only when a trained YOLO model is in memory and passed a test prediction
    task: str | None = None
    device: str | None = None
    confidence_threshold: float | None = None
    classes: dict[int, str] = field(default_factory=dict)


def weights_fingerprint(weights_path: Path) -> str:
    digest = hashlib.sha256()
    with weights_path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()[:12]


class InferenceService:
    def __init__(self, weights: str | Path, mode: str = "auto", app_env: str = "development", device: str = "auto",
                 confidence_threshold: float = 0.25, image_size: int = 640):
        self.detector: YoloDetector | None = None
        self.status = self._initialise(Path(weights), mode, app_env, device, confidence_threshold, image_size)
        if self.status.loaded and confidence_threshold < 0.1:
            logger.warning("CONFIDENCE_THRESHOLD is %s: very low-confidence boxes will be reported as detections", confidence_threshold)
        log = logger.error if self.status.mode == "unavailable" else logger.info
        log("Inference mode: %s (%s)", self.status.mode.upper(), self.status.detail)

    def _initialise(self, weights_path: Path, mode: str, app_env: str, device: str, confidence_threshold: float, image_size: int) -> ModelStatus:
        demo = lambda reason: ModelStatus("demo", DEMO_MODEL_NAME, DEMO_MODEL_VERSION, f"{reason}. Results come from a brightness-threshold placeholder, not a trained model.", configured_mode=mode)
        unavailable = lambda reason: ModelStatus("unavailable", None, None, reason, configured_mode=mode)
        if mode == "demo":
            return demo("Demo mode selected with INFERENCE_MODE=demo")
        if mode == "auto" and not weights_path.is_file():
            if app_env != "production":
                return demo(f"No trained weights found at {weights_path}")
            return unavailable(f"No weights file exists at {weights_path} and this is a production environment. Set INFERENCE_MODE=yolo with trained weights, or INFERENCE_MODE=demo to run the placeholder detector deliberately.")
        # YOLO was selected, or weights were supplied: from here on a failure is reported, never replaced with demo output.
        try:
            self.detector = YoloDetector(weights_path, device, confidence_threshold, image_size)
        except ModelLoadError as error:
            return unavailable(f"YOLO inference is not available: {error} No inspections can be run until this is fixed; set INFERENCE_MODE=demo to use the placeholder detector deliberately.")
        return ModelStatus(
            "trained", weights_path.name, weights_fingerprint(weights_path),
            f"YOLO11 detection model loaded from {weights_path} on device '{self.detector.device}' with confidence threshold {confidence_threshold}",
            configured_mode=mode, loaded=True, task=self.detector.task, device=self.detector.device,
            confidence_threshold=confidence_threshold, classes=dict(CLASS_NAMES),
        )

    def detect(self, image: np.ndarray) -> tuple[list[Detection], np.ndarray]:
        """Detections and the annotated image. Raises ModelUnavailableError when no detector may be used."""
        if self.status.mode == "unavailable":
            raise ModelUnavailableError(self.status.detail)
        if self.detector is not None:
            detections = self.detector.predict(image)
            return detections, draw_detections(image, detections)
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
            class_name = DEMO_CLASS_CYCLE[index % len(DEMO_CLASS_CYCLE)]
            detection = Detection(CLASS_IDS[class_name], class_name, round(min(0.96, 0.62 + area / (image.shape[0] * image.shape[1])), 2), {"x1": float(x), "y1": float(y), "x2": float(x + w), "y2": float(y + h)}, float(area), float(max(w, h)), float(min(w, h)))
            detections.append(detection)
            color = (44, 190, 246) if index % 2 == 0 else (245, 142, 55)
            overlay[candidate_mask > 0] = (overlay[candidate_mask > 0] * 0.5 + np.array(color) * 0.5).astype(np.uint8)
            cv2.rectangle(overlay, (x, y), (x+w, y+h), color, 3)
            cv2.putText(overlay, f"{class_name} {detection.confidence:.0%}", (x, max(25, y-8)), cv2.FONT_HERSHEY_SIMPLEX, 0.65, color, 2)
        return detections, overlay
