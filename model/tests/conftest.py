"""Builds small directory trees laid out like the real RDD2022 release."""
from pathlib import Path
import pytest
from PIL import Image

OBJECT = "<object><name>{label}</name><bndbox><xmin>{xmin}</xmin><ymin>{ymin}</ymin><xmax>{xmax}</xmax><ymax>{ymax}</ymax></bndbox></object>"


def voc_xml(filename: str, objects: list[tuple], size: tuple[int, int] = (200, 100)) -> str:
    body = "".join(OBJECT.format(label=label, xmin=xmin, ymin=ymin, xmax=xmax, ymax=ymax) for label, xmin, ymin, xmax, ymax in objects)
    return f"<annotation><filename>{filename}</filename><size><width>{size[0]}</width><height>{size[1]}</height><depth>3</depth></size>{body}</annotation>"


class RawDataset:
    def __init__(self, root: Path):
        self.root = root

    def add(self, source: str, index: int, objects: list[tuple] | None = None, *, image: bool = True, annotation: bool = True,
            size: tuple[int, int] = (200, 100), declared: tuple[int, int] | None = None, shade: int | None = None, xml: str | None = None) -> str:
        stem = f"{source}_{index:06d}"
        if image:
            folder = self.root / source / "train" / "images"
            folder.mkdir(parents=True, exist_ok=True)
            # A distinct shade per image keeps files from being byte-identical by accident.
            Image.new("RGB", size, ((index * 7) % 256 if shade is None else shade, (index // 36 * 11) % 256, sum(map(ord, source)) % 256)).save(folder / f"{stem}.jpg")
        if annotation:
            folder = self.root / source / "train" / "annotations" / "xmls"
            folder.mkdir(parents=True, exist_ok=True)
            (folder / f"{stem}.xml").write_text(xml if xml is not None else voc_xml(f"{stem}.jpg", objects or [], declared or size))
        return stem

    def add_test_image(self, source: str, index: int) -> None:
        folder = self.root / source / "test" / "images"
        folder.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (200, 100), (index % 256, 0, 0)).save(folder / f"{source}_{index:06d}.jpg")


@pytest.fixture
def raw(tmp_path) -> RawDataset:
    return RawDataset(tmp_path / "raw")


@pytest.fixture
def populated(raw) -> RawDataset:
    """Two sources, 120 images each, every class present, a box in each image."""
    labels = ["D00", "D10", "D20", "D40"]
    for source in ("Japan", "India"):
        for index in range(120):
            raw.add(source, index, [(labels[index % 4], 20, 10, 120, 60)])
    return raw
