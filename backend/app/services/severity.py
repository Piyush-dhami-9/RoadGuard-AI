"""Estimated severity and repair priority from detection bounding boxes.

Everything here is computed from sizes *relative to the image*. A bounding box
says how much of the photograph a damage region occupies, not how large the
damage is on the road: that depends on camera height, angle and lens, none of
which are known. The results are an estimated indicator for triage, not a
physical measurement and not a certified engineering assessment.

The method, in full (constants below):

  Per damage region
    area_share   = box area / image area, saturating at AREA_REFERENCE
    extent_share = box long side / longer image side, saturating at EXTENT_REFERENCE
    score        = 100 x class_weight x (area_weight x area_share + extent_weight x extent_share)
  Cracks are scored mostly on extent (a diagonal crack has a large box but little
  damaged surface); potholes and alligator cracking mostly on area.

  Per inspection
    score    = worst region score
               + up to COVERAGE_BONUS as the boxes together cover COVERAGE_REFERENCE of the image
               + COUNT_BONUS_EACH per additional region, up to COUNT_BONUS_MAX
    level    = Low / Medium / High / Critical from LEVEL_LIMITS
    priority = score x (0.5 + 0.5 x confidence of the worst region)

  Confidence therefore lowers priority for uncertain detections and never raises it.
"""
from dataclasses import dataclass
import numpy as np

AREA_REFERENCE = 0.10      # a box covering 10% of the image counts as full area
EXTENT_REFERENCE = 0.50    # a box spanning half the longer image side counts as full extent
# class name -> (class weight, area weight, extent weight)
CLASS_PROFILES = {
    "Pothole": (1.00, 0.6, 0.4),
    "Alligator Crack": (1.00, 0.6, 0.4),
    "Longitudinal Crack": (0.75, 0.3, 0.7),
    "Transverse Crack": (0.75, 0.3, 0.7),
}
DEFAULT_PROFILE = (0.75, 0.5, 0.5)
COVERAGE_REFERENCE = 0.30
COVERAGE_BONUS = 10.0
COUNT_BONUS_EACH = 2.0
COUNT_BONUS_MAX = 10.0
LEVEL_LIMITS = (("Low", 25.0), ("Medium", 50.0), ("High", 75.0))  # above the last limit: Critical
ACTIONS = {"Low": "Monitor", "Medium": "Schedule Repair", "High": "Immediate Repair", "Critical": "Urgent Repair"}
COVERAGE_GRID = 256


@dataclass(frozen=True)
class SeverityResult:
    score: float
    level: str
    action: str


def level_for(score: float) -> str:
    for level, limit in LEVEL_LIMITS:
        if score <= limit:
            return level
    return "Critical"


def _result(score: float) -> SeverityResult:
    score = round(min(100.0, max(0.0, score)), 1)
    level = level_for(score)
    return SeverityResult(score, level, ACTIONS[level])


def assess_damage(class_name: str, box_width: float, box_height: float, image_width: int, image_height: int) -> SeverityResult:
    """Estimated severity of one region from its bounding box relative to the image."""
    class_weight, area_weight, extent_weight = CLASS_PROFILES.get(class_name, DEFAULT_PROFILE)
    image_area = max(1.0, float(image_width) * float(image_height))
    area_share = min(1.0, (box_width * box_height / image_area) / AREA_REFERENCE)
    extent_share = min(1.0, (max(box_width, box_height) / max(1.0, float(max(image_width, image_height)))) / EXTENT_REFERENCE)
    return _result(100.0 * class_weight * (area_weight * area_share + extent_weight * extent_share))


def coverage(boxes: list[dict[str, float]], image_width: int, image_height: int) -> float:
    """Share of the image covered by at least one box (overlaps counted once), from 0 to 1."""
    if not boxes or image_width <= 0 or image_height <= 0:
        return 0.0
    grid = np.zeros((COVERAGE_GRID, COVERAGE_GRID), bool)
    for box in boxes:
        x1, x2 = (int(round(min(max(box[key] / image_width, 0.0), 1.0) * COVERAGE_GRID)) for key in ("x1", "x2"))
        y1, y2 = (int(round(min(max(box[key] / image_height, 0.0), 1.0) * COVERAGE_GRID)) for key in ("y1", "y2"))
        grid[y1:max(y2, y1 + 1), x1:max(x2, x1 + 1)] = True
    return float(grid.mean())


def assess_inspection(damage_scores: list[float], covered_share: float) -> SeverityResult:
    """Estimated severity of a whole image from its regions' scores, their number and the area they cover."""
    if not damage_scores:
        return _result(0.0)
    coverage_bonus = COVERAGE_BONUS * min(1.0, covered_share / COVERAGE_REFERENCE)
    count_bonus = min(COUNT_BONUS_MAX, COUNT_BONUS_EACH * (len(damage_scores) - 1))
    return _result(max(damage_scores) + coverage_bonus + count_bonus)


def priority(inspection_score: float, worst_confidence: float) -> float:
    """Repair-priority indicator, 0 to 100: the inspection score discounted by uncertainty in its worst region."""
    return round(min(100.0, max(0.0, inspection_score * (0.5 + 0.5 * min(1.0, max(0.0, worst_confidence))))), 1)
