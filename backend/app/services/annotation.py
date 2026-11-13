"""Drawing detections onto an inspection image."""
import cv2
import numpy as np
from .yolo_detector import Detection

# BGR, one colour per class id; the fallback is for anything unexpected.
CLASS_COLORS = {0: (44, 190, 246), 1: (245, 142, 55), 2: (200, 90, 220), 3: (60, 70, 235)}
FALLBACK_COLOR = (160, 160, 160)


def draw_detections(image: np.ndarray, detections: list[Detection]) -> np.ndarray:
    """A copy of the image with a labelled box per detection. With no detections the copy is unchanged."""
    annotated = image.copy()
    height, width = annotated.shape[:2]
    scale = max(0.4, min(width, height) / 900)
    thickness = max(2, round(scale * 2.5))
    for detection in detections:
        color = CLASS_COLORS.get(detection.class_id, FALLBACK_COLOR)
        x1, y1, x2, y2 = (int(round(detection.bbox[key])) for key in ("x1", "y1", "x2", "y2"))
        cv2.rectangle(annotated, (x1, y1), (x2, y2), color, thickness)
        label = f"{detection.class_name} {detection.confidence:.0%}"
        (text_width, text_height), baseline = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, scale, max(1, thickness - 1))
        # Above the box when there is room, otherwise just inside its top edge.
        top = y1 - text_height - baseline - 6 if y1 - text_height - baseline - 6 >= 0 else y1
        left = min(max(x1, 0), max(0, width - text_width - 8))
        cv2.rectangle(annotated, (left, top), (left + text_width + 8, top + text_height + baseline + 6), color, -1)
        cv2.putText(annotated, label, (left + 4, top + text_height + 3), cv2.FONT_HERSHEY_SIMPLEX, scale, (255, 255, 255), max(1, thickness - 1), cv2.LINE_AA)
    return annotated
