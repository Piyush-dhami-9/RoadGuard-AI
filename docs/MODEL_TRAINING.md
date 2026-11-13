# Training the road-damage detector

RoadGuard's model is a **YOLO11 object-detection** model trained on RDD2022. RDD2022 annotations are bounding boxes, so segmentation is not used anywhere in this pipeline.

> **Status:** the pipeline exists and has been run end to end as a smoke test. **No model has been trained.** There are no accuracy figures to report. The application still runs its labelled DEMO detector, and cannot load detection weights until the backend inference step of Phase 3 is done.

All commands run from the repository root.

## Classes

| YOLO id | RDD2022 code | Name shown in the app |
| --- | --- | --- |
| 0 | D00 | Longitudinal Crack |
| 1 | D10 | Transverse Crack |
| 2 | D20 | Alligator Crack |
| 3 | D40 | Pothole |

Defined once in `model/training/classes.py`. The names are written into `data.yaml` and from there into the trained weights. Any other label found in the annotations is counted in the report and not converted.

## 1. Environment

```bash
python3.12 -m venv .venv-train
source .venv-train/bin/activate
pip install -r model/requirements-train.txt
```

This installs PyTorch and takes about 1.2 GB. Keep it separate from the backend's environment.

## 2. Get the dataset

RDD2022 is one 13.3 GB archive on figshare containing a zip per country. The older per-country links on the dataset's GitHub page no longer work (HTTP 403, checked 2026-11-13).

| Country | Download | Annotated images |
| --- | --- | --- |
| China_Drone | 160 MB | 2,401 |
| China_MotorBike | 192 MB | 1,977 |
| Czech | 257 MB | 2,829 |
| India | 527 MB | 7,706 |
| Japan | 1,073 MB | 10,506 |
| United_States | 444 MB | 4,805 |
| Norway | 10,611 MB | 8,161 |

To fetch chosen countries without downloading the whole archive:

```bash
python -m model.training.fetch_rdd2022 --list
python -m model.training.fetch_rdd2022 --sources Czech
```

Each country needs roughly twice its download size free while extracting. Everything except Norway fits on a small laptop disk.

To place data by hand instead, download the archive from <https://figshare.com/articles/dataset/21431547>, and extract the country zips so that the layout is:

```
datasets/rdd2022/raw/<Country>/train/images/<Country>_000123.jpg
datasets/rdd2022/raw/<Country>/train/annotations/xmls/<Country>_000123.xml
datasets/rdd2022/raw/<Country>/test/images/...        (unlabelled, ignored)
```

An extra wrapping folder such as `raw/RDD2022/<Country>/...` is fine.

Licence: CC BY 4.0. Cite Arya et al., "RDD2022: A multi-national image dataset for automatic road damage detection" (doi:10.6084/m9.figshare.21431547) in anything published from it.

## 3. Prepare the dataset

```bash
python -m model.training.prepare_rdd2022 --raw datasets/rdd2022/raw --output datasets/rdd2022/processed
```

This reads every XML under `--raw`, validates it, and writes:

```
datasets/rdd2022/processed/
  images/{train,val,test}/     hard links to the raw images (no extra disk used)
  labels/{train,val,test}/     one YOLO .txt per image: class x_center y_center width height (normalised)
  data.yaml                    dataset definition for Ultralytics
  manifest.csv                 split, source and leakage group of every image
  preparation_report.json      counts, class balance and every issue found
```

The raw folder is never modified. Add `--dry-run` to see the report without writing anything, and `--overwrite` to replace an existing prepared dataset.

### What is validated and reported

| Situation | What happens |
| --- | --- |
| Annotation with no image file | skipped, listed |
| XML that cannot be parsed | skipped, listed |
| Image that cannot be opened | skipped, listed |
| Box with missing, non-numeric or non-finite coordinates | dropped, listed with the reason |
| Box with zero or negative size, or entirely outside the image | dropped, listed |
| Box partly outside the image | clipped to the image, counted |
| Box smaller than `--min-box-pixels` (default 1) after clipping | dropped, listed |
| Repeated identical box | removed, counted |
| Label other than D00, D10, D20, D40 | not converted, counted per label |
| XML `<size>` differs from the real image | the real image size is used, listed |
| Image with no supported damage | kept with an empty label file as a negative example; `--backgrounds drop` removes them |
| Images in `test/` folders | counted, not used (RDD2022 publishes no labels for them) |

Coordinates are normalised by the size read from the image file, not the size written in the XML.

### How the split avoids leakage

RDD2022 has no sequence or drive identifiers. Its images are numbered per country in capture order, so adjacent numbers are often adjacent frames of the same stretch of road. A random per-image split would put near-identical frames in both training and test and inflate every metric. The script therefore splits in groups:

- **Blocks of consecutive numbers.** Images `N` to `N+49` of a country (`--block-size 50`) always land in the same split.
- **Byte-identical images** are detected by hash and kept together, even across countries.
- **Each country is split separately**, so all three splits see every country, in the requested proportions (default 80 / 10 / 10).
- **`--test-sources Norway`** holds one or more whole countries out as the test set; the rest are divided between train and validation. This is the strictest option and also measures how the model transfers to an unseen country.
- The split is deterministic for a given `--seed`.

Limits of this: it is a heuristic. Frames either side of a block boundary can still be similar, and two blocks may show the same road on different passes. Nothing in the published data allows that to be ruled out. `manifest.csv` records the group of every image so the split can be audited.

Because `test/` in RDD2022 is unlabelled, the test split here is carved out of the labelled data. Results are not comparable with CRDDC leaderboard numbers.

### Useful options

```bash
--sources Japan India            # use only some countries
--test-sources Norway            # hold a country out as the test set
--val-fraction 0.1 --test-fraction 0.1
--block-size 50 --seed 42
--backgrounds drop               # leave out images with no supported damage
--max-images-per-source 200      # small subset (whole blocks), for smoke tests
--link-mode hardlink|symlink|copy
--skip-duplicate-check           # faster; skips hashing every image
```

`data.yaml` contains an absolute path. If the dataset folder is moved or copied to another machine, run the preparation again there.

## 4. Smoke test (Apple M1, 8 GB)

The smoke test proves that data loading, training, checkpointing and evaluation run on your machine. It does not produce a usable model.

```bash
python -m model.training.fetch_rdd2022 --sources Czech

python -m model.training.prepare_rdd2022 --output datasets/rdd2022/smoke \
    --max-images-per-source 200 --block-size 20 --backgrounds drop

python -m model.training.train --config model/configs/smoke.yaml

python -m model.training.evaluate --weights runs/rdd2022/smoke/weights/best.pt \
    --data datasets/rdd2022/smoke/data.yaml --split test --imgsz 320 --batch 4
```

`model/configs/smoke.yaml` uses YOLO11n, 2 epochs, 320 px images, batch 4 and no loader workers. On the development M1 the training step took about 70 seconds on the Apple GPU (`device=mps`, detected automatically; pass `--device cpu` to force the CPU).

**Expect metrics at or near zero.** Two epochs on about 160 images does not teach a detector anything. A smoke run is marked `smoke_test: true` in its `training_summary.json`, its weights are never copied to `model/weights/`, and the evaluation output says so.

Do not run full training on an 8 GB laptop: use a machine with a GPU.

## 5. Full training

```bash
python -m model.training.train --config model/configs/rdd2022_yolo11n.yaml
```

Defaults: YOLO11n, 100 epochs, 640 px, batch 16, early stopping after 20 epochs without improvement. Override per run with `--epochs`, `--batch`, `--device`, `--data`, `--name`. Other Ultralytics arguments go under `extra:` in the config. To try a larger model, copy the config and set `model: yolo11s.pt`; only detection checkpoints are accepted (`-seg`, `-cls`, `-pose` and `-obb` are refused).

The device is detected: CUDA if present, otherwise Apple MPS, otherwise CPU.

On a hosted GPU notebook: clone the repository, install `model/requirements-train.txt`, fetch and prepare the dataset there, run the command above, then download `model/weights/roadguard-yolo11-rdd2022.pt` and its `.json`.

### Where the model is saved

| Path | Contents |
| --- | --- |
| `runs/rdd2022/<name>/` | Ultralytics run folder: `weights/best.pt`, `weights/last.pt`, curves, `training_summary.json` |
| **`model/weights/roadguard-yolo11-rdd2022.pt`** | Copy of `best.pt` from a full run. This is the model file for the application. |
| `model/weights/roadguard-yolo11-rdd2022.json` | How that file was produced: config, classes, device, Ultralytics version, SHA-256, validation metrics from training |
| `model/weights/pretrained/` | Downloaded starting checkpoints such as `yolo11n.pt` (COCO weights, not a road-damage model) |

`runs/`, `datasets/` and everything in `model/weights/` are ignored by Git. Keep the `.pt` and `.json` together when you move them.

## 6. Evaluate

```bash
python -m model.training.evaluate --weights model/weights/roadguard-yolo11-rdd2022.pt --split test
```

Prints and saves precision, recall, mAP50 and mAP50-95, overall and per class, to `runs/rdd2022/eval/<name>-<split>/metrics.json`, with the weights' SHA-256, the split size and the Ultralytics version. `--split val` or `--split train` evaluate the other splits; `--data` selects another prepared dataset.

The script refuses weights that are not a detection model or whose class table is not exactly RoadGuard's four classes in order.

Reading the output:

- A class with boxes in the split but no detections scores 0.
- A class with no boxes in the split is shown as not measurable, not as 0.
- Numbers describe one weights file on one split of one prepared dataset. Quote them with the split, the countries included and the preparation settings. They are not physical-accuracy or field-performance claims.

## 7. Tests

```bash
python -m pytest model/tests
```

93 tests cover class mapping, VOC parsing, box validation and conversion, leakage-aware splitting, the preparation script end to end on generated RDD2022-style folders, and the guard rails of the training and evaluation scripts. They do not train a model and need no dataset.

## Known limitations

- No trained model and no metrics yet.
- Preparation has been run on the real Czech subset only (2,829 annotated images, no issues reported). The other countries have not been processed; expect the report to surface labels and defects not seen so far.
- RDD2022 images are mostly forward-facing vehicle or motorbike views, plus drone images from China. Accuracy on other viewpoints must be measured separately.
- Class imbalance is not corrected. In the Czech subset 62% of images have no supported damage and potholes are rare.
- XML is parsed with Python's standard library; only use annotation files from a source you trust.
- The backend does not yet load these weights. Its trained-model path still expects segmentation and refuses detection weights at startup rather than misusing them.
