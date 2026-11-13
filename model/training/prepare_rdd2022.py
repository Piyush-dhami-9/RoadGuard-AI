"""Convert RDD2022 (images + Pascal VOC XML) into a YOLO detection dataset.

Run from the repository root:

    python -m model.training.prepare_rdd2022 --raw datasets/rdd2022/raw --output datasets/rdd2022/processed

Nothing in the raw directory is modified. See docs/MODEL_TRAINING.md.
"""
import argparse
import csv
import hashlib
import json
import os
import random
import shutil
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
import yaml
from PIL import Image
from .classes import CLASS_CODES, CLASS_NAMES, RDD_CLASSES
from .splits import SPLITS, SplitItem, source_and_index, split_items
from .voc import AnnotationError, YoloBox, convert_objects, parse_voc

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png"}
GENERATED = ("images", "labels", "data.yaml", "preparation_report.json", "manifest.csv")
EXAMPLES_KEPT = 200  # per issue type in the JSON report; counts are always complete


class PreparationError(Exception):
    """The dataset could not be prepared; the message says what to fix."""


@dataclass
class Record:
    key: str
    source: str
    index: int | None
    image_path: Path
    boxes: list[YoloBox]
    content_hash: str | None = None


@dataclass
class Issues:
    counts: Counter = field(default_factory=Counter)
    examples: dict[str, list[dict]] = field(default_factory=lambda: defaultdict(list))

    def add(self, kind: str, file: Path | str, detail: str = "", count: int = 1) -> None:
        self.counts[kind] += count
        if len(self.examples[kind]) < EXAMPLES_KEPT:
            self.examples[kind].append({"file": str(file), "detail": detail} if detail else {"file": str(file)})


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--raw", type=Path, default=Path("datasets/rdd2022/raw"), help="directory holding the extracted RDD2022 country folders")
    parser.add_argument("--output", type=Path, default=Path("datasets/rdd2022/processed"), help="where the YOLO dataset is written")
    parser.add_argument("--sources", nargs="+", metavar="NAME", help="only use these sources, e.g. Japan India (default: all found)")
    parser.add_argument("--val-fraction", type=float, default=0.1)
    parser.add_argument("--test-fraction", type=float, default=0.1)
    parser.add_argument("--test-sources", nargs="+", default=[], metavar="NAME", help="hold these sources out entirely as the test set")
    parser.add_argument("--block-size", type=int, default=50, help="consecutive image numbers kept together in one split (default: 50)")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--backgrounds", choices=("keep", "drop"), default="keep", help="images with no supported damage: keep as negatives or drop")
    parser.add_argument("--max-images-per-source", type=int, metavar="N", help="use about N images per source, taken as whole groups (for smoke tests)")
    parser.add_argument("--min-box-pixels", type=float, default=1.0, help="reject boxes smaller than this on either side")
    parser.add_argument("--link-mode", choices=("hardlink", "symlink", "copy"), default="hardlink", help="how images reach the output; hardlink uses no extra disk and falls back to copy")
    parser.add_argument("--skip-duplicate-check", action="store_true", help="do not hash image files to find byte-identical duplicates")
    parser.add_argument("--overwrite", action="store_true", help="replace a previously generated dataset in --output")
    parser.add_argument("--dry-run", action="store_true", help="validate and report without writing a dataset")
    return parser.parse_args(argv)


def discover(raw: Path) -> tuple[list[Path], dict[str, list[Path]]]:
    if not raw.is_dir():
        raise PreparationError(f"Raw dataset directory not found: {raw}")
    annotations, images = [], defaultdict(list)
    archives = []
    for path in sorted(raw.rglob("*")):
        if not path.is_file() or path.name.startswith("."):
            continue
        suffix = path.suffix.lower()
        if suffix == ".xml":
            annotations.append(path)
        elif suffix in IMAGE_SUFFIXES:
            images[path.stem].append(path)
        elif suffix == ".zip":
            archives.append(path)
    if not annotations:
        hint = f" Found {len(archives)} zip archive(s) that still need extracting, e.g. {archives[0].name}." if archives else ""
        raise PreparationError(f"No Pascal VOC .xml annotations found under {raw}.{hint} Expected <Country>/train/annotations/xmls/*.xml and <Country>/train/images/*.jpg.")
    return annotations, images


def image_for(annotation: Path, candidates: list[Path]) -> Path | None:
    """The image with the annotation's name that sits closest to it in the directory tree."""
    if not candidates:
        return None
    shared = lambda image: len(os.path.commonpath([annotation.parent, image.parent]))
    return max(candidates, key=lambda image: (shared(image), -len(image.parts)))


def file_hash(path: Path) -> str:
    digest = hashlib.sha1()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_records(raw: Path, args: argparse.Namespace, issues: Issues, unsupported: Counter) -> tuple[list[Record], dict]:
    annotations, images = discover(raw)
    wanted = set(args.sources) if args.sources else None
    records: list[Record] = []
    used_images: set[Path] = set()
    stats = Counter()
    seen_sources: set[str] = set()
    for annotation in annotations:
        relative = annotation.relative_to(raw)
        source, index = source_and_index(annotation.stem, relative.parts[0] if len(relative.parts) > 1 else "unknown")
        seen_sources.add(source)
        if wanted is not None and source not in wanted:
            continue
        stats["annotation_files"] += 1
        image_path = image_for(annotation, images.get(annotation.stem, []))
        if image_path is None:
            issues.add("missing_image", relative, "no image file with this name")
            continue
        used_images.add(image_path)
        try:
            parsed = parse_voc(annotation)
        except AnnotationError as error:
            issues.add("malformed_annotation", relative, str(error))
            continue
        try:
            with Image.open(image_path) as image:
                width, height = image.size
                image.verify()
        except Exception as error:  # Pillow raises many types for damaged files
            issues.add("unreadable_image", image_path.relative_to(raw), f"{type(error).__name__}: {error}")
            continue
        if parsed.declared_size is not None and parsed.declared_size != (width, height):
            issues.add("size_mismatch", relative, f"XML says {parsed.declared_size[0]}x{parsed.declared_size[1]}, image is {width}x{height}; the image size was used")
        converted = convert_objects(parsed.objects, width, height, args.min_box_pixels)
        unsupported.update(converted.unsupported)
        for reason in converted.invalid:
            issues.add("invalid_box", relative, reason)
        if converted.clipped:
            issues.add("clipped_box", relative, f"{converted.clipped} box(es) extended past the image edge and were clipped", converted.clipped)
        if converted.duplicates:
            issues.add("duplicate_box", relative, f"{converted.duplicates} repeated box(es) removed", converted.duplicates)
        if not converted.boxes:
            stats["images_without_supported_damage"] += 1
            if args.backgrounds == "drop":
                continue
        records.append(Record(str(relative), source, index, image_path, converted.boxes))
    if wanted is not None and wanted - seen_sources:
        raise PreparationError(f"Requested source(s) not found: {sorted(wanted - seen_sources)}. Sources present: {sorted(seen_sources)}")

    unlabelled = [path for paths in images.values() for path in paths if path not in used_images]
    if wanted is not None:
        unlabelled = [path for path in unlabelled if source_and_index(path.stem, path.relative_to(raw).parts[0])[0] in wanted]
    official_test = sum(1 for path in unlabelled if "test" in path.relative_to(raw).parts)
    stats["images_without_annotation"] = len(unlabelled)
    stats["images_without_annotation_in_test_folders"] = official_test
    for path in unlabelled:
        if "test" not in path.relative_to(raw).parts:
            issues.add("image_without_annotation", path.relative_to(raw), "not in a test folder and has no XML")
    return records, dict(stats)


def limit_per_source(records: list[Record], limit: int, block_size: int, seed: int) -> list[Record]:
    """Keep roughly ``limit`` images per source, as whole consecutive blocks so the subset still splits cleanly."""
    kept: list[Record] = []
    by_source: dict[str, dict[int, list[Record]]] = defaultdict(lambda: defaultdict(list))
    for position, record in enumerate(records):
        by_source[record.source][record.index // block_size if record.index is not None else -position - 1].append(record)
    for source in sorted(by_source):
        blocks = sorted(by_source[source])
        random.Random(f"{seed}:limit:{source}").shuffle(blocks)
        taken = 0
        for block in blocks:
            if taken >= limit:
                break
            kept.extend(by_source[source][block])
            taken += len(by_source[source][block])
    return kept


def place_image(source: Path, destination: Path, mode: str) -> str:
    if mode == "symlink":
        destination.symlink_to(source.resolve())
        return "symlink"
    if mode == "hardlink":
        try:
            os.link(source, destination)
            return "hardlink"
        except OSError:
            pass  # different filesystem or links unsupported
    shutil.copy2(source, destination)
    return "copy"


def prepare_output(output: Path, raw: Path, overwrite: bool) -> None:
    resolved, raw_resolved = output.resolve(), raw.resolve()
    if resolved == raw_resolved or raw_resolved.is_relative_to(resolved) or resolved.is_relative_to(raw_resolved):
        raise PreparationError("--output must be a separate directory, not inside or around --raw")
    existing = [name for name in GENERATED if (output / name).exists()]
    if existing and not overwrite:
        raise PreparationError(f"{output} already contains a prepared dataset ({', '.join(existing)}). Pass --overwrite to replace it.")
    for name in existing:
        target = output / name
        shutil.rmtree(target) if target.is_dir() else target.unlink()
    for split in SPLITS:
        (output / "images" / split).mkdir(parents=True, exist_ok=True)
        (output / "labels" / split).mkdir(parents=True, exist_ok=True)


def write_dataset(records: list[Record], assignment: dict[str, str], group_of: dict[str, str], output: Path, link_mode: str) -> Counter:
    placed = Counter()
    stems = Counter(record.image_path.stem for record in records)
    with (output / "manifest.csv").open("w", newline="") as handle:
        manifest = csv.writer(handle)
        manifest.writerow(["split", "source", "group", "image", "label", "boxes", "original_image"])
        for record in sorted(records, key=lambda item: item.key):
            split = assignment[record.key]
            stem = record.image_path.stem
            if stems[stem] > 1:  # same file name in two places: keep both apart
                stem = f"{stem}-{hashlib.sha1(record.key.encode()).hexdigest()[:8]}"
            image_out = output / "images" / split / f"{stem}{record.image_path.suffix.lower()}"
            label_out = output / "labels" / split / f"{stem}.txt"
            placed[place_image(record.image_path, image_out, link_mode)] += 1
            label_out.write_text("".join(box.as_line() + "\n" for box in record.boxes))
            manifest.writerow([split, record.source, group_of[record.key], image_out.relative_to(output), label_out.relative_to(output), len(record.boxes), record.image_path])
    data = {"path": str(output.resolve()), "train": "images/train", "val": "images/val", "test": "images/test", "names": dict(enumerate(CLASS_NAMES))}
    (output / "data.yaml").write_text("# Generated by model.training.prepare_rdd2022. Class order follows RDD2022: " + ", ".join(CLASS_CODES) + ".\n" + yaml.safe_dump(data, sort_keys=False))
    return placed


def summarise(records: list[Record], assignment: dict[str, str], group_of: dict[str, str]) -> tuple[dict, list[str]]:
    splits = {split: {"images": 0, "backgrounds": 0, "boxes": 0, "boxes_per_class": dict.fromkeys(CLASS_NAMES, 0), "images_per_source": Counter(), "groups": set()} for split in SPLITS}
    for record in records:
        entry = splits[assignment[record.key]]
        entry["images"] += 1
        entry["backgrounds"] += not record.boxes
        entry["boxes"] += len(record.boxes)
        entry["images_per_source"][record.source] += 1
        entry["groups"].add(group_of[record.key])
        for box in record.boxes:
            entry["boxes_per_class"][CLASS_NAMES[box.class_id]] += 1
    warnings = []
    shared = [name for name in set().union(*(entry["groups"] for entry in splits.values())) if sum(name in entry["groups"] for entry in splits.values()) > 1]
    if shared:
        warnings.append(f"{len(shared)} leakage group(s) ended up in more than one split; this is a bug, please report it")
    for split, entry in splits.items():
        if entry["images"] == 0:
            warnings.append(f"The {split} split is empty. Use more data, a smaller --block-size, or different fractions.")
        else:
            missing = [name for name, count in entry["boxes_per_class"].items() if count == 0]
            if missing:
                warnings.append(f"The {split} split has no examples of: {', '.join(missing)}. Metrics for those classes will be undefined on it.")
        entry["groups"] = len(entry["groups"])
        entry["images_per_source"] = dict(sorted(entry["images_per_source"].items()))
    return splits, warnings


def prepare(args: argparse.Namespace) -> dict:
    """Run the whole preparation and return the report (also written to preparation_report.json)."""
    raw, output = args.raw, args.output
    issues, unsupported = Issues(), Counter()
    records, stats = read_records(raw, args, issues, unsupported)
    if not records:
        raise PreparationError("No usable annotated images were found; see the issues above. Nothing was written.")
    if args.max_images_per_source:
        records = limit_per_source(records, args.max_images_per_source, args.block_size, args.seed)

    duplicate_images = 0
    if not args.skip_duplicate_check:
        by_hash: dict[str, int] = Counter()
        for record in records:
            record.content_hash = file_hash(record.image_path)
            by_hash[record.content_hash] += 1
        duplicate_images = sum(count - 1 for count in by_hash.values() if count > 1)

    items = [SplitItem(record.key, record.source, record.index, record.content_hash) for record in records]
    assignment, group_of = split_items(items, args.val_fraction, args.test_fraction, args.block_size, args.seed, frozenset(args.test_sources))
    missing_holdout = set(args.test_sources) - {record.source for record in records}
    if missing_holdout:
        raise PreparationError(f"--test-sources not present in the data: {sorted(missing_holdout)}")
    splits, warnings = summarise(records, assignment, group_of)

    placed = Counter()
    if not args.dry_run:
        prepare_output(output, raw, args.overwrite)
        placed = write_dataset(records, assignment, group_of, output, args.link_mode)

    report = {
        "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "dry_run": args.dry_run,
        "raw_dir": str(raw.resolve()),
        "output_dir": str(output.resolve()),
        "task": "detect",
        "classes": [{"id": item.class_id, "rdd_code": item.code, "name": item.name} for item in RDD_CLASSES],
        "settings": {"sources": args.sources, "val_fraction": args.val_fraction, "test_fraction": args.test_fraction, "test_sources": args.test_sources,
                     "block_size": args.block_size, "seed": args.seed, "backgrounds": args.backgrounds, "max_images_per_source": args.max_images_per_source,
                     "min_box_pixels": args.min_box_pixels, "link_mode": args.link_mode, "duplicate_check": not args.skip_duplicate_check},
        "input": stats,
        "output": {"images": len(records), "boxes": sum(len(record.boxes) for record in records), "image_files": dict(placed)},
        "splits": splits,
        "leakage_control": {
            "method": "Images are split in groups of consecutive image numbers per source; byte-identical images share a group; sources in test_sources are held out whole.",
            "limitation": "RDD2022 has no sequence metadata. Grouping removes most near-duplicate frames across splits but cannot guarantee that different groups never show the same road.",
            "groups": len(set(group_of.values())),
            "byte_identical_duplicate_images": duplicate_images if not args.skip_duplicate_check else None,
        },
        "unsupported_classes": dict(unsupported.most_common()),
        "issues": {"counts": dict(issues.counts), "examples": dict(issues.examples), "examples_limit_per_type": EXAMPLES_KEPT},
        "warnings": warnings,
    }
    if not args.dry_run:
        (output / "preparation_report.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


ISSUE_LABELS = {
    "missing_image": "Annotations with no image file (skipped)",
    "malformed_annotation": "Unreadable XML annotations (skipped)",
    "unreadable_image": "Damaged or unreadable images (skipped)",
    "invalid_box": "Invalid bounding boxes (dropped)",
    "clipped_box": "Boxes clipped to the image edge (kept)",
    "duplicate_box": "Repeated boxes (removed)",
    "size_mismatch": "XML size differs from the image (image size used)",
    "image_without_annotation": "Images outside test folders with no XML (ignored)",
}


def print_report(report: dict) -> None:
    line = lambda label, value: print(f"  {label:<52} {value}")
    print("\nRDD2022 -> YOLO detection" + ("  [DRY RUN: nothing written]" if report["dry_run"] else ""))
    print("Classes: " + ", ".join(f"{item['id']}={item['name']} ({item['rdd_code']})" for item in report["classes"]))
    print("\nInput")
    line("Annotation files read", report["input"].get("annotation_files", 0))
    line("Images with no supported damage", f"{report['input'].get('images_without_supported_damage', 0)} ({report['settings']['backgrounds']})")
    line("Unlabelled images in test folders (not used)", report["input"].get("images_without_annotation_in_test_folders", 0))
    print("\nSplits" + f"  ({report['leakage_control']['groups']} groups, block size {report['settings']['block_size']}, seed {report['settings']['seed']})")
    print(f"  {'split':<6} {'images':>7} {'empty':>6} {'boxes':>7}  " + "  ".join(f"{code:>6}" for code in CLASS_CODES) + "   sources")
    for split, entry in report["splits"].items():
        per_class = "  ".join(f"{entry['boxes_per_class'][name]:>6}" for name in CLASS_NAMES)
        print(f"  {split:<6} {entry['images']:>7} {entry['backgrounds']:>6} {entry['boxes']:>7}  {per_class}   {', '.join(f'{k}:{v}' for k, v in entry['images_per_source'].items())}")
    print("\nIssues")
    counts = report["issues"]["counts"]
    if not counts and not report["unsupported_classes"]:
        print("  none")
    for kind, label in ISSUE_LABELS.items():
        if counts.get(kind):
            line(label, counts[kind])
            for example in report["issues"]["examples"][kind][:3]:
                print(f"      {example['file']}" + (f": {example['detail']}" if example.get("detail") else ""))
    if report["unsupported_classes"]:
        line("Objects with unsupported labels (not converted)", sum(report["unsupported_classes"].values()))
        print("      " + ", ".join(f"{label}: {count}" for label, count in report["unsupported_classes"].items()))
    duplicates = report["leakage_control"]["byte_identical_duplicate_images"]
    if duplicates:
        line("Byte-identical duplicate images (kept in one split)", duplicates)
    for warning in report["warnings"]:
        print(f"  WARNING: {warning}")
    if not report["dry_run"]:
        print(f"\nDataset:  {report['output_dir']}/data.yaml")
        print(f"Report:   {report['output_dir']}/preparation_report.json  (full issue lists)")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        report = prepare(args)
    except (PreparationError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    print_report(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
