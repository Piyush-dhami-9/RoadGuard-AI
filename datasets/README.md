# Datasets

Nothing in this folder except this file is tracked by Git.

```
datasets/rdd2022/
  raw/         extracted RDD2022 country folders, exactly as published (never modified)
    Czech/train/images/*.jpg
    Czech/train/annotations/xmls/*.xml
    Czech/test/images/*.jpg        (no annotations; not used)
  processed/   YOLO detection dataset written by model.training.prepare_rdd2022
  smoke/       small subset for the smoke test
```

How to obtain, prepare and use the data: [docs/MODEL_TRAINING.md](../docs/MODEL_TRAINING.md).

RDD2022 is published under CC BY 4.0: Arya et al., "RDD2022: A multi-national image dataset for automatic road damage detection", doi:10.6084/m9.figshare.21431547.
