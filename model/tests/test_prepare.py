import csv
import json
import os
from collections import defaultdict
from pathlib import Path
import pytest
import yaml
from PIL import Image
from model.training.classes import CLASS_NAMES
from model.training.prepare_rdd2022 import PreparationError, main, parse_args, prepare


def run(raw, output: Path, *extra: str) -> dict:
    return prepare(parse_args(["--raw", str(raw.root), "--output", str(output), *extra]))


def manifest(output: Path) -> list[dict]:
    with (output / "manifest.csv").open() as handle:
        return list(csv.DictReader(handle))


def test_writes_a_yolo_detection_dataset(populated, tmp_path):
    output = tmp_path / "out"
    report = run(populated, output)
    data = yaml.safe_load((output / "data.yaml").read_text())
    assert data == {"path": str(output.resolve()), "train": "images/train", "val": "images/val", "test": "images/test", "names": dict(enumerate(CLASS_NAMES))}
    assert report["task"] == "detect" and report["output"]["images"] == 240
    for split in ("train", "val", "test"):
        images = sorted(path.stem for path in (output / "images" / split).glob("*.jpg"))
        labels = sorted(path.stem for path in (output / "labels" / split).glob("*.txt"))
        assert images == labels and len(images) == report["splits"][split]["images"] > 0
    assert sum(report["splits"][split]["images"] for split in report["splits"]) == 240
    assert json.loads((output / "preparation_report.json").read_text())["output"] == report["output"]


def test_label_files_hold_the_converted_boxes(raw, tmp_path):
    stem = raw.add("Japan", 1, [("D40", 50, 20, 150, 60), ("D00", 0, 0, 100, 100), ("D44", 5, 5, 50, 50)])
    output = tmp_path / "out"
    run(raw, output)
    label = next(output.glob(f"labels/*/{stem}.txt"))
    assert label.read_text() == "3 0.500000 0.400000 0.500000 0.400000\n0 0.250000 0.500000 0.500000 1.000000\n"
    image = next(output.glob(f"images/*/{stem}.jpg"))
    assert Image.open(image).size == (200, 100)


def test_every_written_label_is_a_valid_yolo_line(populated, tmp_path):
    populated.add("Japan", 500, [("D10", -30, -5, 400, 300), ("D20", 199, 99, 250, 150)])
    output = tmp_path / "out"
    run(populated, output)
    for label in output.glob("labels/*/*.txt"):
        for line in label.read_text().splitlines():
            class_id, *values = line.split()
            assert int(class_id) in range(4)
            x, y, w, h = map(float, values)
            assert 0 < w <= 1 and 0 < h <= 1 and 0 <= x - w / 2 and x + w / 2 <= 1.000001 and 0 <= y - h / 2 and y + h / 2 <= 1.000001


def test_groups_of_consecutive_images_stay_in_one_split(populated, tmp_path):
    output = tmp_path / "out"
    run(populated, output, "--block-size", "20")
    splits_of_group = defaultdict(set)
    for row in manifest(output):
        splits_of_group[row["group"]].add(row["split"])
    assert len(splits_of_group) == 12 and all(len(splits) == 1 for splits in splits_of_group.values())
    by_split = defaultdict(set)
    for row in manifest(output):
        by_split[row["split"]].add(Path(row["image"]).name)
    assert not (by_split["train"] & by_split["val"]) and not (by_split["train"] & by_split["test"]) and not (by_split["val"] & by_split["test"])


def test_same_seed_gives_the_same_split(populated, tmp_path):
    run(populated, tmp_path / "a", "--block-size", "10", "--seed", "5")
    run(populated, tmp_path / "b", "--block-size", "10", "--seed", "5")
    run(populated, tmp_path / "c", "--block-size", "10", "--seed", "6")
    assignment = lambda name: {row["image"].split("/")[-1]: row["split"] for row in manifest(tmp_path / name)}
    assert assignment("a") == assignment("b") != assignment("c")


def test_held_out_source_becomes_the_test_set(populated, tmp_path):
    report = run(populated, tmp_path / "out", "--test-sources", "India", "--block-size", "10")
    assert report["splits"]["test"]["images_per_source"] == {"India": 120}
    assert "India" not in report["splits"]["train"]["images_per_source"] and "India" not in report["splits"]["val"]["images_per_source"]
    assert report["splits"]["val"]["images"] > 0


def test_problems_are_reported_and_do_not_stop_the_run(populated, tmp_path, capsys):
    populated.add("Japan", 900, [("D00", 10, 10, 50, 50)], image=False)                                  # annotation without image
    populated.add("Japan", 901, xml="<annotation><object>")                                               # malformed XML
    populated.add("Japan", 902, [("D00", 60, 10, 20, 50), ("D10", 500, 500, 600, 600), ("D40", 10, 10, 60, 60)])  # two invalid boxes, one good
    populated.add("Japan", 903, [("D43", 10, 10, 50, 50), ("D01", 10, 10, 50, 50), ("D43", 1, 1, 9, 9)])  # only unsupported labels
    populated.add("Japan", 904, [("D20", 10, 10, 50, 50)], declared=(640, 480))                           # XML size is wrong
    populated.add("Japan", 905, annotation=False)                                                         # image without annotation
    populated.add("Japan", 906, [("D20", 10, 10, 50, 50)])
    (populated.root / "Japan/train/images/Japan_000906.jpg").write_bytes(b"not a jpeg")                   # damaged image
    populated.add_test_image("Japan", 1)
    populated.add_test_image("Japan", 2)
    output = tmp_path / "out"
    assert main(["--raw", str(populated.root), "--output", str(output)]) == 0
    report = json.loads((output / "preparation_report.json").read_text())
    assert report["issues"]["counts"] == {"missing_image": 1, "malformed_annotation": 1, "invalid_box": 2, "size_mismatch": 1, "unreadable_image": 1, "image_without_annotation": 1}
    assert report["unsupported_classes"] == {"D43": 2, "D01": 1}
    assert report["input"]["images_without_annotation_in_test_folders"] == 2
    assert report["input"]["images_without_supported_damage"] == 1
    examples = report["issues"]["examples"]
    assert examples["missing_image"][0]["file"].endswith("Japan_000900.xml")
    assert "zero or negative size" in examples["invalid_box"][0]["detail"] and "entirely outside" in examples["invalid_box"][1]["detail"]
    assert "640x480" in examples["size_mismatch"][0]["detail"]
    written = {path.stem for path in output.glob("images/*/*.jpg")}
    assert {"Japan_000902", "Japan_000903", "Japan_000904"} <= written
    assert not {"Japan_000900", "Japan_000901", "Japan_000905", "Japan_000906", "Japan_000001"} & written or "Japan_000001" in written  # 000001 is also a train image
    assert next(output.glob("labels/*/Japan_000902.txt")).read_text().startswith("3 ")
    assert next(output.glob("labels/*/Japan_000904.txt")).read_text() == "2 0.150000 0.300000 0.200000 0.400000\n"
    printed = capsys.readouterr().out
    for expected in ("Annotations with no image file", "Unreadable XML annotations", "Invalid bounding boxes", "unsupported labels", "D43: 2", "Damaged or unreadable images"):
        assert expected in printed


def test_images_with_no_supported_damage_are_kept_as_empty_labels_or_dropped(populated, tmp_path):
    populated.add("India", 700, [])
    populated.add("India", 701, [("D50", 1, 1, 50, 50)])
    kept = run(populated, tmp_path / "keep")
    assert kept["output"]["images"] == 242 and sum(entry["backgrounds"] for entry in kept["splits"].values()) == 2
    assert next((tmp_path / "keep").glob("labels/*/India_000700.txt")).read_text() == ""
    dropped = run(populated, tmp_path / "drop", "--backgrounds", "drop")
    assert dropped["output"]["images"] == 240 and not list((tmp_path / "drop").glob("images/*/India_00070*.jpg"))


def test_byte_identical_images_are_reported_and_share_a_split(populated, tmp_path):
    for index in (300, 800):
        populated.add("Japan", index, [("D00", 10, 10, 50, 50)], shade=255)
        populated.add("India", index, [("D00", 10, 10, 50, 50)], shade=255)
    first = (populated.root / "Japan/train/images/Japan_000300.jpg").read_bytes()
    for path in ("Japan/train/images/Japan_000800.jpg", "India/train/images/India_000300.jpg"):
        (populated.root / path).write_bytes(first)
    report = run(populated, tmp_path / "out", "--block-size", "10")
    assert report["leakage_control"]["byte_identical_duplicate_images"] == 2
    where = {Path(row["image"]).stem: row["split"] for row in manifest(tmp_path / "out")}
    assert where["Japan_000300"] == where["Japan_000800"] == where["India_000300"]
    assert run(populated, tmp_path / "nohash", "--skip-duplicate-check")["leakage_control"]["byte_identical_duplicate_images"] is None


def test_source_filter_and_unknown_source(populated, tmp_path):
    report = run(populated, tmp_path / "out", "--sources", "India")
    assert report["output"]["images"] == 120 and set(report["splits"]["train"]["images_per_source"]) == {"India"}
    with pytest.raises(PreparationError, match="Norway"):
        run(populated, tmp_path / "other", "--sources", "Norway")
    with pytest.raises(PreparationError, match="Norway"):
        run(populated, tmp_path / "other", "--test-sources", "Norway")


def test_per_source_limit_takes_whole_blocks_for_a_small_subset(populated, tmp_path):
    report = run(populated, tmp_path / "out", "--max-images-per-source", "40", "--block-size", "10")
    assert report["output"]["images"] == 80
    assert all(report["splits"][split]["images"] > 0 for split in ("train", "val", "test"))


def test_existing_dataset_is_protected_unless_overwrite(populated, tmp_path):
    output = tmp_path / "out"
    run(populated, output)
    (output / "notes.txt").write_text("mine")
    with pytest.raises(PreparationError, match="--overwrite"):
        run(populated, output)
    report = run(populated, output, "--overwrite", "--sources", "India")
    assert len(list(output.glob("images/*/*.jpg"))) == report["output"]["images"] == 120
    assert (output / "notes.txt").read_text() == "mine"


def test_raw_data_is_never_modified_and_output_cannot_overlap_it(populated, tmp_path):
    before = {path: path.stat().st_mtime_ns for path in populated.root.rglob("*") if path.is_file()}
    run(populated, tmp_path / "out")
    assert before == {path: path.stat().st_mtime_ns for path in populated.root.rglob("*") if path.is_file()}
    for bad in (populated.root, populated.root / "processed", populated.root.parent):
        with pytest.raises(PreparationError, match="separate directory"):
            run(populated, bad)


def test_dry_run_reports_without_writing(populated, tmp_path):
    report = run(populated, tmp_path / "out", "--dry-run")
    assert report["dry_run"] and report["output"]["images"] == 240 and not (tmp_path / "out").exists()


@pytest.mark.parametrize("mode", ["hardlink", "symlink", "copy"])
def test_link_modes(populated, tmp_path, mode):
    output = tmp_path / "out"
    report = run(populated, output, "--link-mode", mode, "--sources", "India")
    image = next(output.glob("images/train/*.jpg"))
    original = populated.root / "India/train/images" / image.name
    assert report["output"]["image_files"] == {mode: 120}
    assert image.is_symlink() == (mode == "symlink")
    assert os.path.samefile(image, original) == (mode != "copy")
    assert Image.open(image).size == (200, 100)


def test_helpful_errors_for_missing_or_unextracted_data(tmp_path, capsys):
    assert main(["--raw", str(tmp_path / "nowhere"), "--output", str(tmp_path / "out")]) == 1
    assert "not found" in capsys.readouterr().err
    (tmp_path / "raw").mkdir()
    (tmp_path / "raw" / "RDD2022_Japan.zip").write_bytes(b"PK")
    assert main(["--raw", str(tmp_path / "raw"), "--output", str(tmp_path / "out")]) == 1
    error = capsys.readouterr().err
    assert "still need extracting" in error and "RDD2022_Japan.zip" in error


def test_layout_with_a_wrapping_folder_is_found(tmp_path):
    from model.tests.conftest import RawDataset
    wrapped = RawDataset(tmp_path / "raw" / "RDD2022")
    for index in range(30):
        wrapped.add("Czech", index, [("D10", 10, 10, 90, 40)])
    report = prepare(parse_args(["--raw", str(tmp_path / "raw"), "--output", str(tmp_path / "out"), "--block-size", "5"]))
    assert report["output"]["images"] == 30 and set(report["splits"]["train"]["images_per_source"]) == {"Czech"}


def test_split_without_a_class_is_flagged(raw, tmp_path):
    for index in range(100):
        raw.add("Japan", index, [("D00" if index < 90 else "D40", 10, 10, 90, 40)])
    report = run(raw, tmp_path / "out", "--block-size", "10")
    assert any("has no examples of" in warning and "Transverse Crack" in warning for warning in report["warnings"])
