# Architecture

```
Browser ── React SPA ── fetch /api/* ──▶ nginx (or the Vite dev proxy) ──▶ FastAPI ──▶ PostgreSQL
                                                                              └─▶ uploads/ (images on disk)
```

## Backend (`backend/app`)

| Module | Responsibility |
| --- | --- |
| `main.py` | Routes, error handlers, request-size limit. No image or model logic. |
| `services/images.py` | Upload validation (content sniffing, size, declared dimensions), decoding, file storage and safe path resolution |
| `services/inference.py` | Decides the inference mode at startup and dispatches to the YOLO model or the labelled demo detector |
| `services/yolo_detector.py` | Loads YOLO11 detection weights once, validates them, runs predictions, extracts boxes, classes and confidences |
| `services/damage_classes.py` | The four damage classes and their ids; must equal the class table inside the weights |
| `services/annotation.py` | Draws labelled boxes on the annotated image |
| `services/severity.py` | Estimated severity and priority from box sizes relative to the image ([SEVERITY.md](SEVERITY.md)) |
| `services/analysis.py` | The pipeline: decode, detect, score, store images, build the inspection record |
| `services/report.py` | PDF report, built in memory |
| `db.py`, `migrations/` | Engine, sessions, Alembic migrations applied at startup |

`POST /detect` reads at most the configured upload size, runs the CPU-bound pipeline in a worker thread, then commits the record. If the commit fails the stored images are removed. Deleting an inspection removes its images.

## Inference mode

Chosen once at startup from `INFERENCE_MODE` (`demo`, `yolo`, `auto`), `APP_ENV` and whether `MODEL_WEIGHTS` exists and passes validation. The model is loaded once and reused; predictions are serialised with a lock. The result is one of `demo`, `trained` (a YOLO11 model is in use) or `unavailable`, reported by `/health` and stored on every inspection together with the model name and version (for trained models, the first 12 hex digits of the weights file's SHA-256). There is no path from "weights supplied but unusable" to demo output.

## Frontend (`frontend/src`)

`api.ts` is the only module that calls the network. `lib/inspections.ts` holds pure logic (search, filter, sort, CSV, upload checks). Pages are `Dashboard`, `Upload`, `History` and `Detail`; `App.tsx` owns navigation and shared state. Images and reports are fetched through the API, never from static paths.

## Known gaps

See `docs/IMPLEMENTATION_REPORT.md` for what is not yet done: a trained model, authentication, persistent storage on Azure.
