"""Evaluate YOLO11 detection weights on a split of the prepared dataset.

Reports precision, recall, mAP50 and mAP50-95, overall and per class, and
writes them to metrics.json. Run from the repository root:

    python -m model.training.evaluate --weights model/weights/roadguard-yolo11-rdd2022.pt --split test

See docs/MODEL_TRAINING.md.
"""
import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from .classes import CLASS_NAMES, RDD_CLASSES, names_match
from .common import DEFAULT_WEIGHTS, PipelineError, fail, load_dataset_config, repo_path, require_detection_model, resolve_device, sha256_of, split_label_counts


def collect_metrics(box_metrics, instances_per_class: dict[str, int]) -> dict:
    """Pull the four headline numbers, overall and per class, out of an Ultralytics detection result.

    A class with ground-truth boxes that the model never scored (no detections
    at all) is reported as zeros. A class with no ground-truth boxes in the
    split is reported as None: it cannot be measured there.
    """
    overall = {"precision": float(box_metrics.mp), "recall": float(box_metrics.mr), "mAP50": float(box_metrics.map50), "mAP50-95": float(box_metrics.map)}
    undetected = {"precision": 0.0, "recall": 0.0, "mAP50": 0.0, "mAP50-95": 0.0}
    per_class = {name: dict(undetected) if instances_per_class.get(name, 0) > 0 else None for name in CLASS_NAMES}
    for position, class_index in enumerate(box_metrics.ap_class_index):
        per_class[CLASS_NAMES[int(class_index)]] = {
            "precision": float(box_metrics.p[position]), "recall": float(box_metrics.r[position]),
            "mAP50": float(box_metrics.ap50[position]), "mAP50-95": float(box_metrics.ap[position]),
        }
    return {"overall": overall, "per_class": per_class}


def evaluate(weights: Path, data_yaml: Path, split: str, imgsz: int, batch: int, device: str, project: Path, name: str) -> dict:
    if not weights.is_file():
        raise PipelineError(f"Weights not found: {weights}\nTrain a model first (python -m model.training.train --help) or pass --weights.")
    data = load_dataset_config(data_yaml, (split,))
    counts = split_label_counts(data, split)
    os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")
    from ultralytics import YOLO, __version__ as ultralytics_version

    model = YOLO(str(weights))
    require_detection_model(model, str(weights))
    if not names_match(model.names):
        raise PipelineError(f"{weights} was trained with classes {model.names}; RoadGuard expects {CLASS_NAMES}. These weights are not a RoadGuard model.")
    resolved_device = resolve_device(device)
    results = model.val(data=str(data_yaml), split=split, imgsz=imgsz, batch=batch, device=resolved_device, project=str(project), name=name, plots=True)
    training_record = weights.with_suffix(".json")
    run_summary = weights.parent.parent / "training_summary.json"  # <run>/weights/best.pt -> <run>/training_summary.json
    described = next((json.loads(path.read_text()) for path in (training_record, run_summary) if path.is_file()), {})
    report = {
        "evaluated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "weights": str(weights),
        "weights_sha256": sha256_of(weights),
        "smoke_test_weights": bool(described.get("smoke_test", False)),
        "task": "detect",
        "classes": [{"id": item.class_id, "rdd_code": item.code, "name": item.name} for item in RDD_CLASSES],
        "dataset": str(data_yaml),
        "split": split,
        "split_size": counts,
        "imgsz": imgsz,
        "device": resolved_device,
        "ultralytics_version": ultralytics_version,
        "metrics": collect_metrics(results.box, counts["instances_per_class"]),
        "note": "Measured on this split of this prepared dataset only. Not a statement about accuracy on other roads, cameras or countries.",
    }
    output = Path(results.save_dir) / "metrics.json"
    output.write_text(json.dumps(report, indent=2) + "\n")
    report["metrics_file"] = str(output)
    return report


def print_report(report: dict) -> None:
    size = report["split_size"]
    print(f"\nEvaluation of {report['weights']}")
    print(f"Split: {report['split']}  ({size['images']} images, {size['instances']} boxes)  imgsz={report['imgsz']}  device={report['device']}")
    if report["smoke_test_weights"]:
        print("SMOKE-TEST WEIGHTS: the numbers below only show that evaluation runs. They are not model accuracy.")
    print(f"\n  {'class':<20} {'boxes':>6} {'precision':>10} {'recall':>8} {'mAP50':>8} {'mAP50-95':>9}")
    row = lambda label, boxes, values: print(f"  {label:<20} {boxes:>6} " + ("   (no ground-truth boxes in this split)" if values is None else f"{values['precision']:>10.3f} {values['recall']:>8.3f} {values['mAP50']:>8.3f} {values['mAP50-95']:>9.3f}"))
    row("all", size["instances"], report["metrics"]["overall"])
    for name in CLASS_NAMES:
        row(name, size["instances_per_class"][name], report["metrics"]["per_class"][name])
    print(f"\nSaved: {report['metrics_file']}")
    print(report["note"])


def default_label(weights: Path) -> str:
    """'smoke' for runs/rdd2022/smoke/weights/best.pt; the file name for exported weights."""
    return weights.parent.parent.name if weights.stem in ("best", "last") and weights.parent.name == "weights" else weights.stem


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--weights", type=Path, default=DEFAULT_WEIGHTS, help=f"weights to evaluate (default: {DEFAULT_WEIGHTS.relative_to(DEFAULT_WEIGHTS.parents[2])})")
    parser.add_argument("--data", default="datasets/rdd2022/processed/data.yaml")
    parser.add_argument("--split", choices=("train", "val", "test"), default="test")
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--batch", type=int, default=16)
    parser.add_argument("--device", default="auto")
    parser.add_argument("--project", default="runs/rdd2022/eval")
    parser.add_argument("--name", help="folder name for this evaluation (default: <run or weights name>-<split>)")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    weights = repo_path(args.weights)
    try:
        report = evaluate(weights, repo_path(args.data), args.split, args.imgsz, args.batch, args.device, repo_path(args.project), args.name or f"{default_label(weights)}-{args.split}")
    except PipelineError as error:
        return fail(error)
    print_report(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
