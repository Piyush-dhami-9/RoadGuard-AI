"""Config handling and guard rails of the training and evaluation scripts. No training runs here."""
import sys
import types
from pathlib import Path
import pytest
import yaml
from model.training import common, evaluate, train
from model.training.classes import CLASS_NAMES
from model.training.common import PipelineError, load_dataset_config, require_detection_model, resolve_device, split_label_counts
from model.training.prepare_rdd2022 import parse_args, prepare

CONFIGS = Path(__file__).resolve().parents[1] / "configs"


def write_config(tmp_path, **values) -> Path:
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump({"name": "t", **values}))
    return path


def fake_torch(monkeypatch, cuda: bool, mps: bool) -> None:
    module = types.SimpleNamespace(cuda=types.SimpleNamespace(is_available=lambda: cuda), backends=types.SimpleNamespace(mps=types.SimpleNamespace(is_available=lambda: mps)))
    monkeypatch.setitem(sys.modules, "torch", module)


@pytest.mark.parametrize("cuda, mps, expected", [(True, True, "0"), (False, True, "mps"), (False, False, "cpu")])
def test_auto_device_is_detected_not_assumed(monkeypatch, cuda, mps, expected):
    fake_torch(monkeypatch, cuda, mps)
    assert resolve_device("auto") == expected
    assert resolve_device("cpu") == "cpu"


def test_shipped_configs_are_valid_detection_configs():
    full = train.load_config(CONFIGS / "rdd2022_yolo11n.yaml")
    smoke = train.load_config(CONFIGS / "smoke.yaml")
    assert full.model == smoke.model == "yolo11n.pt" and not full.smoke_test
    assert full.export_to == "model/weights/roadguard-yolo11-rdd2022.pt"
    assert smoke.smoke_test and smoke.export_to is None
    assert smoke.epochs <= 3 and smoke.imgsz <= 320 and smoke.batch <= 4 and smoke.workers == 0


def test_command_line_overrides_apply(tmp_path):
    config = train.load_config(write_config(tmp_path, epochs=50), {"epochs": 3, "device": "cpu", "batch": None})
    assert (config.epochs, config.device, config.batch) == (3, "cpu", 16)


@pytest.mark.parametrize("model", ["yolo11n-seg.pt", "yolo11s-seg.pt", "yolo11n-cls.pt", "yolo11n-pose.pt", "yolo11n-obb.pt", "weights/custom-seg.pt"])
def test_non_detection_checkpoints_are_refused(tmp_path, model):
    with pytest.raises(PipelineError, match="not a detection checkpoint"):
        train.load_config(write_config(tmp_path, model=model))


def test_config_mistakes_are_refused(tmp_path):
    with pytest.raises(PipelineError, match="Unknown key"):
        train.load_config(write_config(tmp_path, epoch=5))
    with pytest.raises(PipelineError, match="must not set 'export_to'"):
        train.load_config(write_config(tmp_path, smoke_test=True, export_to="model/weights/x.pt"))
    with pytest.raises(PipelineError, match="top level"):
        train.load_config(write_config(tmp_path, extra={"epochs": 1}))
    with pytest.raises(PipelineError, match="not found"):
        train.load_config(tmp_path / "missing.yaml")


def test_named_checkpoints_download_into_the_ignored_weights_folder():
    assert train.pretrained_path("yolo11n.pt") == common.REPO_ROOT / "model/weights/pretrained/yolo11n.pt"
    assert train.pretrained_path("runs/rdd2022/x/weights/last.pt") == common.REPO_ROOT / "runs/rdd2022/x/weights/last.pt"


def test_model_task_guard():
    require_detection_model(types.SimpleNamespace(task="detect"), "ok.pt")
    with pytest.raises(PipelineError, match="'segment' model"):
        require_detection_model(types.SimpleNamespace(task="segment"), "seg.pt")


def test_dataset_checks_before_training(populated, tmp_path):
    with pytest.raises(PipelineError, match="Prepare the dataset first"):
        load_dataset_config(tmp_path / "none" / "data.yaml", ("train", "val"))
    output = tmp_path / "out"
    prepare(parse_args(["--raw", str(populated.root), "--output", str(output)]))
    data = load_dataset_config(output / "data.yaml", ("train", "val", "test"))
    counts = split_label_counts(data, "train")
    assert counts["images"] == len(list(output.glob("images/train/*.jpg"))) == counts["instances"]
    assert set(counts["instances_per_class"]) == set(CLASS_NAMES) and all(counts["instances_per_class"].values())

    wrong = yaml.safe_load((output / "data.yaml").read_text())
    wrong["names"] = {0: "Pothole", 1: "Longitudinal Crack", 2: "Transverse Crack", 3: "Alligator Crack"}
    (output / "wrong.yaml").write_text(yaml.safe_dump(wrong))
    with pytest.raises(PipelineError, match="four classes in order"):
        load_dataset_config(output / "wrong.yaml", ("train",))
    for image in output.glob("images/val/*"):
        image.unlink()
    with pytest.raises(PipelineError, match="'val' split has no images"):
        load_dataset_config(output / "data.yaml", ("train", "val"))


def test_train_stops_before_loading_anything_when_the_dataset_is_missing(tmp_path, capsys):
    config = write_config(tmp_path, data=str(tmp_path / "absent" / "data.yaml"))
    assert train.main(["--config", str(config)]) == 1
    assert "Prepare the dataset first" in capsys.readouterr().err


def test_evaluate_stops_when_weights_are_missing(tmp_path, capsys):
    assert evaluate.main(["--weights", str(tmp_path / "none.pt")]) == 1
    assert "Weights not found" in capsys.readouterr().err


def test_metrics_are_read_per_class_and_unmeasurable_classes_are_not_invented():
    box = types.SimpleNamespace(mp=0.5, mr=0.25, map50=0.4, map=0.2, ap_class_index=[0, 3], p=[0.6, 0.4], r=[0.3, 0.2], ap50=[0.5, 0.3], ap=[0.25, 0.15])
    counts = {"Longitudinal Crack": 12, "Transverse Crack": 0, "Alligator Crack": 5, "Pothole": 3}
    metrics = evaluate.collect_metrics(box, counts)
    assert metrics["overall"] == {"precision": 0.5, "recall": 0.25, "mAP50": 0.4, "mAP50-95": 0.2}
    assert metrics["per_class"]["Longitudinal Crack"] == {"precision": 0.6, "recall": 0.3, "mAP50": 0.5, "mAP50-95": 0.25}
    assert metrics["per_class"]["Pothole"]["mAP50-95"] == 0.15
    assert metrics["per_class"]["Transverse Crack"] is None, "no ground truth in the split: cannot be measured"
    assert metrics["per_class"]["Alligator Crack"] == {"precision": 0.0, "recall": 0.0, "mAP50": 0.0, "mAP50-95": 0.0}, "ground truth exists but nothing was detected"


def test_model_with_no_detections_scores_zero_not_missing():
    box = types.SimpleNamespace(mp=0.0, mr=0.0, map50=0.0, map=0.0, ap_class_index=[], p=[], r=[], ap50=[], ap=[])
    metrics = evaluate.collect_metrics(box, dict.fromkeys(CLASS_NAMES, 4))
    assert all(values == {"precision": 0.0, "recall": 0.0, "mAP50": 0.0, "mAP50-95": 0.0} for values in metrics["per_class"].values())


def test_evaluation_folder_is_named_after_the_run_or_the_weights():
    assert evaluate.default_label(Path("runs/rdd2022/smoke/weights/best.pt")) == "smoke"
    assert evaluate.default_label(Path("model/weights/roadguard-yolo11-rdd2022.pt")) == "roadguard-yolo11-rdd2022"
