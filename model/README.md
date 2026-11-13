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

## Using trained weights in the application

The backend loads YOLO11 **detection** weights with `INFERENCE_MODE=yolo` (or `auto` when the file exists). Place the file at `model/weights/roadguard-yolo11-rdd2022.pt`, keep the `.json` from training beside it, and see the README section "Enabling YOLO mode".

At startup the backend checks the weights and refuses them, with a reason in `/health`, when:

- the file is missing or is not a loadable Ultralytics model;
- it is not a detection model (segmentation, classification, pose and OBB are refused);
- its class table is not exactly `0 Longitudinal Crack, 1 Transverse Crack, 2 Alligator Crack, 3 Pothole`, which also rules out generic pretrained checkpoints such as `weights/pretrained/yolo11n.pt`;
- its training record marks it as a smoke test;
- it cannot complete a test prediction on the selected device.

In none of these cases does the application fall back to the demo detector.
