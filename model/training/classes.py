"""The single definition of RoadGuard's damage classes.

Class IDs follow the RDD2022 label map order (D00, D10, D20, D40). The display
names are written into data.yaml, and from there into the trained weights, so
the application reads them from the model instead of keeping its own list.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class DamageClass:
    class_id: int
    code: str
    name: str


RDD_CLASSES: tuple[DamageClass, ...] = (
    DamageClass(0, "D00", "Longitudinal Crack"),
    DamageClass(1, "D10", "Transverse Crack"),
    DamageClass(2, "D20", "Alligator Crack"),
    DamageClass(3, "D40", "Pothole"),
)
CLASS_NAMES: list[str] = [item.name for item in RDD_CLASSES]
CLASS_CODES: list[str] = [item.code for item in RDD_CLASSES]
_CODE_TO_ID = {item.code: item.class_id for item in RDD_CLASSES}


def class_id_for(label: str | None) -> int | None:
    """YOLO class ID for an RDD2022 label code, or None when the label is not one of the four supported classes."""
    if label is None:
        return None
    return _CODE_TO_ID.get(label.strip().upper())


def names_match(model_names: dict[int, str] | list[str]) -> bool:
    """True when a model's or dataset's class table is exactly RoadGuard's, in order."""
    ordered = [model_names[key] for key in sorted(model_names)] if isinstance(model_names, dict) else list(model_names)
    return ordered == CLASS_NAMES
