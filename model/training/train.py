"""Train a YOLO11 object-detection model on the prepared RDD2022 dataset.

Run from the repository root:

    python -m model.training.train --config model/configs/rdd2022_yolo11n.yaml
    python -m model.training.train --config model/configs/smoke.yaml        # pipeline check only

See docs/MODEL_TRAINING.md.
"""
import argparse
import json
import os
import shutil
import sys
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime, timezone
from pathlib import Path
import yaml
from .classes import CLASS_NAMES, RDD_CLASSES
from .common import NON_DETECTION_MARKERS, PRETRAINED_DIR, PipelineError, fail, load_dataset_config, repo_path, require_detection_model, resolve_device, sha256_of

METRIC_KEYS = {"precision": "metrics/precision(B)", "recall": "metrics/recall(B)", "mAP50": "metrics/mAP50(B)", "mAP50-95": "metrics/mAP50-95(B)"}


@dataclass
class TrainConfig:
    name: str
    model: str = "yolo11n.pt"                 # pretrained YOLO11 detection checkpoint to start from
    data: str = "datasets/rdd2022/processed/data.yaml"
    epochs: int = 100
    imgsz: int = 640
    batch: int = 16
    workers: int = 4
    device: str = "auto"
    patience: int = 20
    seed: int = 0
    project: str = "runs/rdd2022"
    export_to: str | None = None              # where best.pt is copied for the application; omit to keep it in the run folder only
    smoke_test: bool = False                  # marks the run as a pipeline check whose weights must not be used
    extra: dict = field(default_factory=dict)  # further Ultralytics train() arguments


def load_config(path: Path, overrides: dict | None = None) -> TrainConfig:
    if not path.is_file():
        raise PipelineError(f"Training config not found: {path}")
    values = yaml.safe_load(path.read_text()) or {}
    known = {item.name for item in fields(TrainConfig)}
    unknown = sorted(set(values) - known)
    if unknown:
        raise PipelineError(f"Unknown key(s) in {path}: {unknown}. Allowed: {sorted(known)}. Put other Ultralytics arguments under 'extra'.")
    values.update({key: value for key, value in (overrides or {}).items() if value is not None})
    if "name" not in values:
        raise PipelineError(f"{path} must set 'name'.")
    config = TrainConfig(**values)
    if any(marker in Path(config.model).name for marker in NON_DETECTION_MARKERS):
        raise PipelineError(f"'{config.model}' is not a detection checkpoint. Use a YOLO11 detection model such as yolo11n.pt or yolo11s.pt.")
    if config.smoke_test and config.export_to:
        raise PipelineError("A smoke-test config must not set 'export_to': smoke-test weights are not a trained model.")
    reserved = {"data", "epochs", "imgsz", "batch", "workers", "device", "patience", "seed", "project", "name", "task"} & set(config.extra)
    if reserved:
        raise PipelineError(f"Set {sorted(reserved)} at the top level of the config, not under 'extra'.")
    return config


def pretrained_path(model: str) -> Path:
    """Named checkpoints are downloaded once into model/weights/pretrained/; explicit paths are used as given."""
    candidate = Path(model)
    return repo_path(candidate) if candidate.parent != Path(".") else PRETRAINED_DIR / candidate.name


def train(config: TrainConfig) -> dict:
    data_yaml = repo_path(config.data)
    load_dataset_config(data_yaml, ("train", "val"))
    os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")  # lets operators missing on Apple GPUs run on the CPU
    from ultralytics import YOLO, __version__ as ultralytics_version

    device = resolve_device(config.device)
    start = pretrained_path(config.model)
    start.parent.mkdir(parents=True, exist_ok=True)
    model = YOLO(str(start))
    require_detection_model(model, config.model)
    print(f"Training '{config.name}': {config.model} on {data_yaml} | device={device} epochs={config.epochs} imgsz={config.imgsz} batch={config.batch}")
    results = model.train(data=str(data_yaml), task="detect", epochs=config.epochs, imgsz=config.imgsz, batch=config.batch, workers=config.workers,
                          device=device, patience=config.patience, seed=config.seed, project=str(repo_path(config.project)), name=config.name, **config.extra)

    run_dir = Path(model.trainer.save_dir)
    best = Path(model.trainer.best)
    if not best.is_file():
        raise PipelineError(f"Training finished without producing {best}.")
    trained = YOLO(str(best))
    require_detection_model(trained, str(best))
    if [trained.names[key] for key in sorted(trained.names)] != CLASS_NAMES:
        raise PipelineError(f"The trained weights carry classes {trained.names}, expected {CLASS_NAMES}.")
    reported = getattr(results, "results_dict", {}) or {}
    summary = {
        "name": config.name,
        "smoke_test": config.smoke_test,
        "task": "detect",
        "classes": [{"id": item.class_id, "rdd_code": item.code, "name": item.name} for item in RDD_CLASSES],
        "base_model": config.model,
        "config": asdict(config),
        "device": device,
        "ultralytics_version": ultralytics_version,
        "finished_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "run_dir": str(run_dir),
        "best_weights": str(best),
        "best_weights_sha256": sha256_of(best),
        "validation_metrics_from_training": {label: float(reported[key]) for label, key in METRIC_KEYS.items() if key in reported},
        "note": "Validation-split figures reported by the trainer for best.pt. Report test-split results from model.training.evaluate."
                + (" SMOKE TEST: these weights only prove the pipeline runs and must not be used for inspections." if config.smoke_test else ""),
    }
    (run_dir / "training_summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    if config.export_to:
        target = repo_path(config.export_to)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(best, target)
        target.with_suffix(".json").write_text(json.dumps({**summary, "exported_weights": str(target)}, indent=2) + "\n")
        summary["exported_weights"] = str(target)
    return summary


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", type=Path, required=True, help="training config, e.g. model/configs/rdd2022_yolo11n.yaml")
    parser.add_argument("--data", help="override the dataset data.yaml")
    parser.add_argument("--device", help="override the device: auto, cpu, mps, 0, ...")
    parser.add_argument("--epochs", type=int)
    parser.add_argument("--batch", type=int)
    parser.add_argument("--name", help="override the run name")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        config = load_config(repo_path(args.config), {key: getattr(args, key) for key in ("data", "device", "epochs", "batch", "name")})
        summary = train(config)
    except PipelineError as error:
        return fail(error)
    print(f"\nRun folder:    {summary['run_dir']}")
    print(f"Best weights:  {summary['best_weights']}")
    if summary.get("exported_weights"):
        print(f"Exported to:   {summary['exported_weights']}  (+ .json describing the run)")
    if summary["smoke_test"]:
        print("SMOKE TEST: the pipeline ran. These weights are not a trained model and were not exported.")
    print("Next: python -m model.training.evaluate --weights " + (summary.get("exported_weights") or summary["best_weights"]) + " --split test")
    return 0


if __name__ == "__main__":
    sys.exit(main())
