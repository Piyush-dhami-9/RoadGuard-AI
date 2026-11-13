# RoadGuard model

**No trained model exists yet.** `model/weights/` is empty and weights files are git-ignored.

Without weights the backend runs the DEMO detector (`opencv-threshold-demo`): it thresholds dark pixels and assigns damage classes by position in a list. It exists so the workflow can be exercised end to end. Its output is labelled DEMO everywhere and must not be used for decisions.

## Supplying weights

Place weights at `model/weights/best.pt` (or set `MODEL_WEIGHTS`) and install `ultralytics` (Docker: build with `--build-arg INSTALL_MODEL_DEPS=true`). If the file is present but cannot be loaded, the API reports the model as unavailable and `/detect` returns 503; it does not fall back to demo output.

## Current limitation

The trained-model code path still expects YOLO **segmentation** weights with the class order Pothole, Longitudinal Crack, Transverse Crack, Alligator Crack. Detection weights are refused at startup with an explanatory message. The planned dataset, RDD2022, has bounding boxes only, so the next phase converts this path to YOLO11 detection and reads class names from the model. No training pipeline, dataset or evaluation metrics exist in this repository yet.
