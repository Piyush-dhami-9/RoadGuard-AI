"""Class mapping, bounding-box extraction, confidence filtering and annotation, on mocked model output."""
from types import SimpleNamespace
import numpy as np
import pytest
from app.services.annotation import CLASS_COLORS, draw_detections
from app.services.damage_classes import CLASS_IDS, CLASS_NAMES, DAMAGE_CLASSES, class_table_matches
from app.services.yolo_detector import Detection, ModelLoadError, YoloDetector, extract_detections
from tests.conftest import WORKDIR, road_image

SHAPE = (720, 1280, 3)


def result(*boxes: tuple) -> SimpleNamespace:
    rows = np.array(boxes, dtype=float).reshape(-1, 6)
    return SimpleNamespace(boxes=SimpleNamespace(xyxy=rows[:, :4], conf=rows[:, 4], cls=rows[:, 5]))


def extract(*boxes: tuple, threshold: float = 0.25) -> list[Detection]:
    return extract_detections(result(*boxes), CLASS_NAMES, threshold, SHAPE)


# ---- class mapping -----------------------------------------------------------

def test_class_ids_match_the_training_pipeline():
    assert DAMAGE_CLASSES == ((0, "D00", "Longitudinal Crack"), (1, "D10", "Transverse Crack"), (2, "D20", "Alligator Crack"), (3, "D40", "Pothole"))
    assert CLASS_NAMES == {0: "Longitudinal Crack", 1: "Transverse Crack", 2: "Alligator Crack", 3: "Pothole"}
    assert CLASS_IDS == {"Longitudinal Crack": 0, "Transverse Crack": 1, "Alligator Crack": 2, "Pothole": 3}


def test_class_table_must_match_exactly():
    assert class_table_matches(dict(CLASS_NAMES)) and class_table_matches(list(CLASS_NAMES.values())) and class_table_matches({"0": "Longitudinal Crack", "1": "Transverse Crack", "2": "Alligator Crack", "3": "Pothole"})
    assert not class_table_matches({0: "Pothole", 1: "Longitudinal Crack", 2: "Transverse Crack", 3: "Alligator Crack"})
    assert not class_table_matches({**CLASS_NAMES, 4: "Repair"}) and not class_table_matches(None) and not class_table_matches({})


@pytest.mark.parametrize("class_id, name", list(CLASS_NAMES.items()))
def test_each_class_id_is_reported_with_its_name(class_id, name):
    detection = extract((10, 10, 110, 60, 0.8, class_id))[0]
    assert (detection.class_id, detection.class_name) == (class_id, name)


def test_detections_with_an_unknown_class_id_are_ignored():
    assert [d.class_id for d in extract((10, 10, 110, 60, 0.9, 7), (10, 10, 110, 60, 0.8, 2))] == [2]


# ---- bounding-box extraction -----------------------------------------------------

def test_boxes_classes_and_confidences_are_extracted():
    pothole, crack = extract((100.4, 200.6, 500.2, 420.9, 0.912345, 3), (600, 50, 660, 700, 0.5, 0))
    assert pothole == Detection(3, "Pothole", 0.9123, {"x1": 100.4, "y1": 200.6, "x2": 500.2, "y2": 420.9}, 88075.9, 399.8, 220.3)
    assert crack.bbox == {"x1": 600.0, "y1": 50.0, "x2": 660.0, "y2": 700.0}
    assert (crack.area, crack.length, crack.width) == (39000.0, 650.0, 60.0), "length is the long side whichever way the box runs"


def test_detections_are_ordered_by_confidence():
    assert [d.confidence for d in extract((0, 0, 50, 50, 0.4, 0), (0, 0, 50, 50, 0.9, 1), (0, 0, 50, 50, 0.6, 2))] == [0.9, 0.6, 0.4]


def test_boxes_are_clipped_to_the_image_and_empty_ones_dropped():
    clipped, = extract((-40, -20, 300, 200, 0.9, 3), (1300, 100, 1400, 200, 0.9, 3), (500, 500, 500.4, 600, 0.9, 3))
    assert clipped.bbox == {"x1": 0.0, "y1": 0.0, "x2": 300.0, "y2": 200.0} and clipped.area == 60000.0
    edge, = extract((1200, 650, 1500, 900, 0.9, 1))
    assert edge.bbox == {"x1": 1200.0, "y1": 650.0, "x2": 1280.0, "y2": 720.0}


def test_torch_like_tensors_are_accepted():
    class Tensor:
        def __init__(self, values):
            self.values = values

        def tolist(self):
            return self.values
    output = SimpleNamespace(boxes=SimpleNamespace(xyxy=Tensor([[10.0, 20.0, 110.0, 70.0]]), conf=Tensor([0.75]), cls=Tensor([2.0])))
    detection, = extract_detections(output, CLASS_NAMES, 0.25, SHAPE)
    assert (detection.class_name, detection.confidence, detection.area) == ("Alligator Crack", 0.75, 5000.0)


# ---- confidence filtering ---------------------------------------------------------

def test_detections_below_the_threshold_are_removed():
    boxes = [(0, 0, 50, 50, confidence, 0) for confidence in (0.10, 0.249, 0.25, 0.60, 0.95)]
    assert [d.confidence for d in extract(*boxes, threshold=0.25)] == [0.95, 0.6, 0.25]
    assert [d.confidence for d in extract(*boxes, threshold=0.7)] == [0.95]
    assert len(extract(*boxes, threshold=0.0)) == 5


def test_threshold_is_passed_to_the_model_and_applied_to_its_output(fake_yolo):
    weights = WORKDIR / "w.pt"
    weights.write_bytes(b"x")
    model = fake_yolo([(0, 0, 100, 100, 0.9, 3), (0, 0, 100, 100, 0.3, 3)])
    detector = YoloDetector(weights, "cpu", confidence_threshold=0.5, image_size=320)
    assert [d.confidence for d in detector.predict(road_image())] == [0.9]
    assert model.calls[-1]["conf"] == 0.5 and model.calls[-1]["imgsz"] == 320
    weights.unlink()


# ---- no detections ----------------------------------------------------------------

def test_no_detections_gives_an_empty_list():
    assert extract() == []
    assert extract_detections(SimpleNamespace(boxes=None), CLASS_NAMES, 0.25, SHAPE) == []
    assert extract_detections(SimpleNamespace(), CLASS_NAMES, 0.25, SHAPE) == []
    assert extract((0, 0, 50, 50, 0.1, 0)) == []


def test_missing_weights_raise_a_load_error():
    with pytest.raises(ModelLoadError, match="No weights file exists"):
        YoloDetector(WORKDIR / "nope.pt", "cpu")


# ---- annotated image ---------------------------------------------------------------

def test_annotated_image_draws_each_box_in_its_class_colour_and_leaves_the_input_untouched():
    image = np.full(SHAPE, 150, np.uint8)
    original = image.copy()
    detections = extract((100, 200, 500, 420, 0.9, 3), (700, 100, 760, 600, 0.6, 0))
    annotated = draw_detections(image, detections)
    assert np.array_equal(image, original), "the stored original must not be drawn on"
    assert annotated.shape == image.shape and annotated.dtype == np.uint8
    assert tuple(annotated[300, 100]) == CLASS_COLORS[3] and tuple(annotated[420, 300]) == CLASS_COLORS[3]
    assert tuple(annotated[350, 700]) == CLASS_COLORS[0]
    assert tuple(annotated[300, 300]) == (150, 150, 150), "boxes are outlines; the damage itself stays visible"
    assert (annotated[170:200, 100:330] != 150).any(), "a label is drawn above the box"


def test_annotated_image_without_detections_equals_the_input():
    image = road_image()
    annotated = draw_detections(image, [])
    assert np.array_equal(annotated, image) and annotated is not image


def test_labels_stay_inside_the_image_at_the_edges():
    image = np.full((200, 300, 3), 150, np.uint8)
    annotated = draw_detections(image, extract_detections(result((0, 0, 60, 40, 0.9, 2), (250, 150, 300, 200, 0.8, 1)), CLASS_NAMES, 0.25, image.shape))
    assert annotated.shape == (200, 300, 3)
