"""The damage classes the application understands.

IDs follow the RDD2022 label map and must match the class table inside the
trained weights exactly (see model/training/classes.py, which is tested against
this file). Weights with any other class table are refused at load time.
"""
DAMAGE_CLASSES = (
    (0, "D00", "Longitudinal Crack"),
    (1, "D10", "Transverse Crack"),
    (2, "D20", "Alligator Crack"),
    (3, "D40", "Pothole"),
)
CLASS_NAMES: dict[int, str] = {class_id: name for class_id, _, name in DAMAGE_CLASSES}
CLASS_IDS: dict[str, int] = {name: class_id for class_id, _, name in DAMAGE_CLASSES}


def class_table_matches(model_names: object) -> bool:
    """True when a model's id -> name table is exactly the application's."""
    if isinstance(model_names, (list, tuple)):
        model_names = dict(enumerate(model_names))
    return isinstance(model_names, dict) and {int(key): value for key, value in model_names.items()} == CLASS_NAMES
