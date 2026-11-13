"""Helpers shared by the training and evaluation scripts."""
import hashlib
import sys
from pathlib import Path
import yaml
from .classes import CLASS_NAMES, names_match

REPO_ROOT = Path(__file__).resolve().parents[2]
PRETRAINED_DIR = REPO_ROOT / "model" / "weights" / "pretrained"
DEFAULT_WEIGHTS = REPO_ROOT / "model" / "weights" / "roadguard-yolo11-rdd2022.pt"
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png"}
NON_DETECTION_MARKERS = ("-seg", "-cls", "-pose", "-obb")


class PipelineError(Exception):
    """A precondition failed; the message says what to do."""


def repo_path(value: str | Path) -> Path:
    """Paths in configs and on the command line are relative to the repository root."""
    path = Path(value).expanduser()
    return path if path.is_absolute() else REPO_ROOT / path


def resolve_device(requested: str = "auto") -> str:
    """'auto' picks CUDA, then Apple MPS, then CPU, from what this machine actually has."""
    if requested != "auto":
        return requested
    import torch
    if torch.cuda.is_available():
        return "0"
    if getattr(torch.backends, "mps", None) is not None and torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_dataset_config(data_yaml: Path, required_splits: tuple[str, ...]) -> dict:
    """Read data.yaml and check it is a prepared RoadGuard detection dataset with images in the needed splits."""
    if not data_yaml.is_file():
        raise PipelineError(f"Dataset config not found: {data_yaml}\nPrepare the dataset first: python -m model.training.prepare_rdd2022 --help")
    data = yaml.safe_load(data_yaml.read_text()) or {}
    if not names_match(data.get("names") or {}):
        raise PipelineError(f"{data_yaml} does not define RoadGuard's four classes in order {CLASS_NAMES}; found {data.get('names')}. Re-run dataset preparation.")
    root = Path(data.get("path", data_yaml.parent))
    root = root if root.is_absolute() else data_yaml.parent / root
    for split in required_splits:
        if not data.get(split):
            raise PipelineError(f"{data_yaml} has no '{split}' split.")
        if not any(path.suffix.lower() in IMAGE_SUFFIXES for path in (root / data[split]).glob("*")):
            raise PipelineError(f"The '{split}' split has no images in {root / data[split]}. If the dataset was moved or prepared on another machine, re-run dataset preparation.")
    data["_root"] = root
    return data


def split_label_counts(data: dict, split: str) -> dict:
    """Images and boxes per class in a split, counted from its label files."""
    labels = data["_root"] / data[split].replace("images", "labels", 1)
    per_class = dict.fromkeys(CLASS_NAMES, 0)
    images = sum(1 for path in (data["_root"] / data[split]).glob("*") if path.suffix.lower() in IMAGE_SUFFIXES)
    for label_file in labels.glob("*.txt"):
        for line in label_file.read_text().splitlines():
            if line.strip():
                per_class[CLASS_NAMES[int(line.split()[0])]] += 1
    return {"images": images, "instances": sum(per_class.values()), "instances_per_class": per_class}


def require_detection_model(model, origin: str) -> None:
    task = getattr(model, "task", None)
    if task != "detect":
        raise PipelineError(f"{origin} is a '{task}' model. RoadGuard trains and evaluates YOLO11 object detection only; RDD2022 has bounding boxes, not masks.")


def fail(error: Exception) -> int:
    print(f"error: {error}", file=sys.stderr)
    return 1
