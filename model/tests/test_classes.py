import ast
import re
from pathlib import Path
import pytest
from model.training.classes import CLASS_CODES, CLASS_NAMES, RDD_CLASSES, class_id_for, names_match

REPO = Path(__file__).resolve().parents[2]


def test_class_ids_follow_the_rdd2022_label_map_order():
    assert [(item.class_id, item.code, item.name) for item in RDD_CLASSES] == [
        (0, "D00", "Longitudinal Crack"), (1, "D10", "Transverse Crack"), (2, "D20", "Alligator Crack"), (3, "D40", "Pothole")]
    assert CLASS_CODES == ["D00", "D10", "D20", "D40"]


@pytest.mark.parametrize("label, expected", [("D00", 0), ("D10", 1), ("D20", 2), ("D40", 3), (" d40 ", 3)])
def test_supported_labels_map_to_ids(label, expected):
    assert class_id_for(label) == expected


@pytest.mark.parametrize("label", ["D01", "D11", "D43", "D44", "D50", "Repair", "Block crack", "", None, "D4", "D400"])
def test_other_labels_are_unsupported(label):
    assert class_id_for(label) is None


def test_names_match_requires_exact_names_in_order():
    assert names_match(dict(enumerate(CLASS_NAMES)))
    assert names_match(list(CLASS_NAMES))
    assert not names_match({0: "Pothole", 1: "Longitudinal Crack", 2: "Transverse Crack", 3: "Alligator Crack"})  # the app's old order
    assert not names_match({0: "D00", 1: "D10", 2: "D20", 3: "D40"})
    assert not names_match(dict(enumerate(CLASS_NAMES[:3])))
    assert not names_match({index: f"class{index}" for index in range(80)})


def test_application_uses_the_same_display_names():
    """The backend and dashboard show these names; a renamed class must be renamed everywhere."""
    backend = (REPO / "backend/app/services/inference.py").read_text()
    backend_names = ast.literal_eval(re.search(r"^CLASSES = (\[.*\])$", backend, re.M).group(1))
    dashboard = (REPO / "frontend/src/pages/Dashboard.tsx").read_text()
    dashboard_names = re.findall(r"'([^']+)'", re.search(r"KNOWN_CLASSES = \[(.*)\]", dashboard).group(1))
    assert sorted(backend_names) == sorted(CLASS_NAMES)
    assert sorted(dashboard_names) == sorted(CLASS_NAMES)
