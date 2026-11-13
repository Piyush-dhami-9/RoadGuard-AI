"""Pascal VOC annotation parsing and conversion to YOLO detection boxes."""
import math
import xml.etree.ElementTree as ElementTree
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from .classes import class_id_for


class AnnotationError(Exception):
    """The annotation file could not be read at all."""


@dataclass(frozen=True)
class VocObject:
    label: str | None
    coordinates: tuple[str | None, str | None, str | None, str | None]  # xmin, ymin, xmax, ymax as written


@dataclass(frozen=True)
class VocAnnotation:
    filename: str | None
    declared_size: tuple[int, int] | None  # width, height as written in the XML
    objects: list[VocObject]


@dataclass(frozen=True)
class YoloBox:
    class_id: int
    x_center: float
    y_center: float
    width: float
    height: float

    def as_line(self) -> str:
        return f"{self.class_id} {self.x_center:.6f} {self.y_center:.6f} {self.width:.6f} {self.height:.6f}"


@dataclass
class Conversion:
    boxes: list[YoloBox] = field(default_factory=list)
    invalid: list[str] = field(default_factory=list)        # one reason per rejected box
    unsupported: Counter = field(default_factory=Counter)   # label -> count
    clipped: int = 0
    duplicates: int = 0


def _text(element: ElementTree.Element | None, tag: str) -> str | None:
    child = element.find(tag) if element is not None else None
    return child.text.strip() if child is not None and child.text else None


def parse_voc(xml_path: Path) -> VocAnnotation:
    try:
        root = ElementTree.parse(xml_path).getroot()
    except (ElementTree.ParseError, OSError, UnicodeError) as error:
        raise AnnotationError(f"unreadable XML: {error}") from error
    size = root.find("size")
    declared = None
    try:
        declared = (int(float(_text(size, "width"))), int(float(_text(size, "height"))))
    except (TypeError, ValueError):
        pass
    objects = []
    for item in root.iter("object"):
        box = item.find("bndbox")
        objects.append(VocObject(_text(item, "name"), tuple(_text(box, tag) for tag in ("xmin", "ymin", "xmax", "ymax"))))
    return VocAnnotation(_text(root, "filename"), declared, objects)


def convert_objects(objects: list[VocObject], image_width: int, image_height: int, min_box_pixels: float = 1.0) -> Conversion:
    """Validate VOC boxes against the real image size and convert the usable ones.

    Boxes partly outside the image are clipped. Boxes that are malformed, lie
    wholly outside, or are smaller than ``min_box_pixels`` on a side after
    clipping are rejected with a reason. Unsupported labels are counted, not converted.
    """
    result = Conversion()
    seen: set[tuple[int, float, float, float, float]] = set()
    for item in objects:
        class_id = class_id_for(item.label)
        if class_id is None:
            result.unsupported[item.label or "<missing label>"] += 1
            continue
        try:
            xmin, ymin, xmax, ymax = (float(value) for value in item.coordinates)
        except (TypeError, ValueError):
            result.invalid.append(f"{item.label}: missing or non-numeric coordinates {item.coordinates}")
            continue
        if not all(math.isfinite(value) for value in (xmin, ymin, xmax, ymax)):
            result.invalid.append(f"{item.label}: non-finite coordinates {item.coordinates}")
            continue
        if xmax <= xmin or ymax <= ymin:
            result.invalid.append(f"{item.label}: zero or negative size ({xmin:g}, {ymin:g}, {xmax:g}, {ymax:g})")
            continue
        clipped = (max(0.0, xmin), max(0.0, ymin), min(float(image_width), xmax), min(float(image_height), ymax))
        if clipped[2] <= clipped[0] or clipped[3] <= clipped[1]:
            result.invalid.append(f"{item.label}: entirely outside the {image_width}x{image_height} image ({xmin:g}, {ymin:g}, {xmax:g}, {ymax:g})")
            continue
        width, height = clipped[2] - clipped[0], clipped[3] - clipped[1]
        if width < min_box_pixels or height < min_box_pixels:
            result.invalid.append(f"{item.label}: smaller than {min_box_pixels:g} px after clipping ({width:g} x {height:g})")
            continue
        key = (class_id, *clipped)
        if key in seen:
            result.duplicates += 1
            continue
        seen.add(key)
        if clipped != (xmin, ymin, xmax, ymax):
            result.clipped += 1
        result.boxes.append(YoloBox(class_id, (clipped[0] + clipped[2]) / 2 / image_width, (clipped[1] + clipped[3]) / 2 / image_height, width / image_width, height / image_height))
    return result
