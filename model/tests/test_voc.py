import pytest
from model.training.voc import AnnotationError, VocObject, convert_objects, parse_voc
from model.tests.conftest import voc_xml


def obj(label, xmin, ymin, xmax, ymax) -> VocObject:
    return VocObject(label, (str(xmin), str(ymin), str(xmax), str(ymax)))


def test_parse_reads_filename_size_and_objects(tmp_path):
    path = tmp_path / "a.xml"
    path.write_text(voc_xml("a.jpg", [("D00", 10, 20, 110, 70), ("D40", 1.5, 2.5, 30.5, 40.5)], (600, 400)))
    parsed = parse_voc(path)
    assert parsed.filename == "a.jpg" and parsed.declared_size == (600, 400)
    assert parsed.objects == [VocObject("D00", ("10", "20", "110", "70")), VocObject("D40", ("1.5", "2.5", "30.5", "40.5"))]


def test_parse_tolerates_missing_size_and_bndbox(tmp_path):
    path = tmp_path / "a.xml"
    path.write_text("<annotation><object><name>D10</name></object></annotation>")
    parsed = parse_voc(path)
    assert parsed.declared_size is None and parsed.objects == [VocObject("D10", (None, None, None, None))]


@pytest.mark.parametrize("content", ["", "<annotation><object>", "not xml at all"])
def test_parse_rejects_unreadable_xml(tmp_path, content):
    path = tmp_path / "bad.xml"
    path.write_text(content)
    with pytest.raises(AnnotationError):
        parse_voc(path)


def test_box_is_converted_to_normalised_centre_format():
    result = convert_objects([obj("D20", 50, 20, 150, 60)], 200, 100)
    box = result.boxes[0]
    assert (box.class_id, box.x_center, box.y_center, box.width, box.height) == (2, 0.5, 0.4, 0.5, 0.4)
    assert box.as_line() == "2 0.500000 0.400000 0.500000 0.400000"


def test_every_class_keeps_its_id_through_conversion():
    result = convert_objects([obj(code, 10, 10, 50, 50) for code in ("D00", "D10", "D20", "D40")], 200, 100)
    assert [box.class_id for box in result.boxes] == [0, 1, 2, 3]


def test_unsupported_labels_are_counted_not_converted():
    result = convert_objects([obj("D00", 10, 10, 50, 50), obj("D43", 10, 10, 50, 50), obj("Repair", 1, 1, 5, 5), obj("D43", 2, 2, 9, 9), obj(None, 1, 1, 5, 5)], 200, 100)
    assert len(result.boxes) == 1
    assert dict(result.unsupported) == {"D43": 2, "Repair": 1, "<missing label>": 1}
    assert result.invalid == []


@pytest.mark.parametrize("coordinates, reason", [
    ((50, 20, 50, 60), "zero or negative size"),
    ((150, 20, 50, 60), "zero or negative size"),
    ((10, 60, 50, 20), "zero or negative size"),
    ((250, 20, 300, 60), "entirely outside"),
    ((-50, -40, -1, -2), "entirely outside"),
    (("abc", 20, 50, 60), "non-numeric"),
    ((None, None, None, None), "non-numeric"),
    (("nan", 20, 50, 60), "non-finite"),
    ((10, 10, 10.4, 50), "smaller than"),
])
def test_invalid_boxes_are_rejected_with_a_reason(coordinates, reason):
    result = convert_objects([VocObject("D00", tuple(None if value is None else str(value) for value in coordinates))], 200, 100)
    assert result.boxes == []
    assert len(result.invalid) == 1 and reason in result.invalid[0]


def test_boxes_past_the_edge_are_clipped_and_stay_in_range():
    result = convert_objects([obj("D40", -20, -10, 100, 50), obj("D10", 150, 50, 260, 140)], 200, 100)
    assert result.clipped == 2 and result.invalid == []
    first, second = result.boxes
    assert (first.x_center, first.y_center, first.width, first.height) == (0.25, 0.25, 0.5, 0.5)
    assert (second.x_center, second.y_center, second.width, second.height) == (0.875, 0.75, 0.25, 0.5)
    for box in result.boxes:
        assert 0 <= box.x_center - box.width / 2 and box.x_center + box.width / 2 <= 1
        assert 0 <= box.y_center - box.height / 2 and box.y_center + box.height / 2 <= 1


def test_repeated_boxes_are_removed_but_same_box_with_other_class_is_kept():
    result = convert_objects([obj("D00", 10, 10, 50, 50), obj("D00", 10, 10, 50, 50), obj("D10", 10, 10, 50, 50)], 200, 100)
    assert [box.class_id for box in result.boxes] == [0, 1] and result.duplicates == 1


def test_minimum_box_size_is_configurable():
    assert convert_objects([obj("D00", 10, 10, 13, 50)], 200, 100, min_box_pixels=4).boxes == []
    assert len(convert_objects([obj("D00", 10, 10, 13, 50)], 200, 100, min_box_pixels=2).boxes) == 1
