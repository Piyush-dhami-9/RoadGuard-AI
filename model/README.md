# RoadGuard model

**No trained model exists yet.** Weights files are git-ignored and none ship with the repository.

| Path | Purpose |
| --- | --- |
| `training/` | Dataset fetch and preparation, training and evaluation scripts for YOLO11 **detection** on RDD2022 |
| `configs/` | Training configs: `rdd2022_yolo11n.yaml` (full run) and `smoke.yaml` (pipeline check) |
| `tests/` | Tests for class mapping, dataset conversion, splitting and script guard rails |
| `weights/roadguard-yolo11-rdd2022.pt` | Where a full training run saves its best model (with a `.json` describing the run) |
| `weights/pretrained/` | Downloaded starting checkpoints; not road-damage models |

How to use all of this: [docs/MODEL_TRAINING.md](../docs/MODEL_TRAINING.md).

## What the application runs today

Without usable weights the backend runs the DEMO detector (`opencv-threshold-demo`): it thresholds dark pixels and assigns damage classes by position in a list. It exists so the workflow can be exercised end to end. Its output is labelled DEMO everywhere and must not be used for decisions.

The backend's trained-model path still expects YOLO **segmentation** weights and refuses detection weights at startup with an explanatory message. Converting that path to detection, and reading class names from the model, is the remaining part of Phase 3. Until then, do not point `MODEL_WEIGHTS` at the detection weights: in `auto` mode the API would report the model as unavailable instead of running the demo.
