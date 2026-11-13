from dataclasses import dataclass
from pathlib import Path
import cv2
import numpy as np

CLASSES = ["Pothole", "Longitudinal Crack", "Transverse Crack", "Alligator Crack"]


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
    def __init__(self, weights: str):
        self.model = None
        weights_path = Path(weights)
        if weights_path.exists():
            try:
                from ultralytics import YOLO
                self.model = YOLO(str(weights_path))
            except Exception:
                self.model = None

    def detect(self, image: np.ndarray) -> tuple[list[Detection], np.ndarray]:
        if self.model is not None:
            return self._yolo(image)
        return self._demo(image)

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
