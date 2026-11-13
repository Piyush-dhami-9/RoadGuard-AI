# RoadGuard AI

RoadGuard AI is a road-inspection platform: upload a road-surface image, get flagged damage regions, an estimated severity and repair priority, a stored inspection record, and a PDF report.

> **Current status: no trained model yet.** The backend can run YOLO11 detection weights, but none have been trained and none ship with this repository. Until they are supplied, results come from a brightness-threshold placeholder detector and are **not AI predictions**. Every result is labelled with how it was produced, in the API, the UI, the annotated image and the PDF. See [docs/PROJECT_AUDIT.md](docs/PROJECT_AUDIT.md) and [docs/IMPLEMENTATION_REPORT.md](docs/IMPLEMENTATION_REPORT.md).

Severity and priority are estimated indicators from bounding-box sizes relative to the image ([docs/SEVERITY.md](docs/SEVERITY.md)). They are not physical dimensions and not a certified engineering assessment.

## Run with Docker Compose

```bash
cp .env.example .env
docker compose up --build
```

Open `http://localhost:5173` for the dashboard and `http://localhost:8000/docs` for the API explorer.

## Run for development (no Docker for the app)

Backend, from `backend/` (Python 3.12, PostgreSQL reachable at `DATABASE_URL`):

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
uvicorn app.main:app --reload
```

Frontend, from `frontend/` (Node 22):

```bash
npm ci
npm run dev
```

The dev server forwards `/api` to `http://localhost:8000`. If the backend runs elsewhere, set `VITE_DEV_API_TARGET`, for example `VITE_DEV_API_TARGET=http://localhost:8765 npm run dev`.

## Tests

```bash
cd backend && python -m pytest        # API, uploads, model modes, reports, migrations (uses SQLite, no services needed)
cd frontend && npm test               # upload workflow, errors, history, report download
cd frontend && npm run build          # type-check and production build
python -m pytest model/tests           # dataset conversion, class mapping, training guard rails (needs model/requirements-train.txt)
```

## Inference modes

| `INFERENCE_MODE` | Behaviour |
| --- | --- |
| `demo` | Always the labelled demo detector, even if weights exist. The only way to run demo output in production. |
| `yolo` | The trained YOLO11 detection weights at `MODEL_WEIGHTS` are required. If they are missing or invalid, the model is *unavailable* and `/detect` returns 503 with the reason. (`trained` is accepted as an older name.) |
| `auto` (default) | `yolo` if the weights file exists; otherwise `demo` in development, *unavailable* in production. |

The service never switches from YOLO to demo on its own. `GET /health` reports the configured mode, whether a model is loaded, and why not if it is not.

### Enabling YOLO mode

No trained weights ship with the repository; produce them first (see [docs/MODEL_TRAINING.md](docs/MODEL_TRAINING.md)).

1. Put the weights at `model/weights/roadguard-yolo11-rdd2022.pt`, with the `.json` written next to them by training.
2. Install the model runtime in the backend environment: `pip install -r backend/requirements.txt` (this includes `ultralytics`).
3. Start the backend with `INFERENCE_MODE=yolo`. For example, from `backend/`:

   ```bash
   INFERENCE_MODE=yolo INFERENCE_DEVICE=cpu uvicorn app.main:app --port 8000
   ```

4. Check it, then send an image:

   ```bash
   curl -s http://localhost:8000/health
   # expect "inference_mode": "trained" and "model": {"loaded": true, "task": "detect", ...}
   curl -s -F "file=@road.jpg" http://localhost:8000/detect
   # each damage has class_id, class_name, confidence and bbox; "inference_mode" is "trained"
   ```

If `/health` shows `"inference_mode": "unavailable"`, `model.detail` says what is wrong: file missing, `ultralytics` not installed, not a detection model, wrong class table, or smoke-test weights.

To go back to the demo detector, restart with `INFERENCE_MODE=demo`. Existing inspections keep the mode they were produced with.

### YOLO mode with Docker Compose

The default backend image does not contain PyTorch or Ultralytics (843 MB). YOLO mode needs the image built with them (about 2.5 GB). In `.env`:

```env
INSTALL_MODEL_DEPS=true
INFERENCE_MODE=yolo
MODEL_WEIGHTS=model/weights/roadguard-yolo11-rdd2022.pt
```

then:

```bash
docker compose build backend
docker compose up -d
curl -s http://localhost:8000/health
```

- Compose mounts the host folder `model/weights/` read-only at the same relative path in the container, so `MODEL_WEIGHTS` is the same value on the host and in Docker. Keep it a relative path under `model/weights/`.
- Containers have no GPU here; inference runs on the CPU. Leave `INFERENCE_DEVICE` unset or `cpu` for Docker (`mps` only works outside Docker on a Mac).
- `INFERENCE_MODE=yolo` on an image built without `INSTALL_MODEL_DEPS=true` reports that `ultralytics` is not installed; it does not fall back to demo.
- `docker-compose.prod.yml` sets `APP_ENV=production` and defaults to `INFERENCE_MODE=yolo`.
- To return to the demo detector, set `INFERENCE_MODE=demo` and run `docker compose up -d backend`. No rebuild is needed.

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `DATABASE_URL` | local PostgreSQL | SQLAlchemy async URL |
| `CORS_ORIGINS` | `http://localhost:5173` | Comma-separated allowed origins |
| `APP_ENV` | `development` | `production` disables the automatic demo fallback |
| `INFERENCE_MODE` | `auto` | `demo`, `yolo` or `auto`; see above |
| `MODEL_WEIGHTS` | `model/weights/roadguard-yolo11-rdd2022.pt` | Trained YOLO11 detection weights. Relative paths are tried from the working directory, then the project root |
| `INFERENCE_DEVICE` | `auto` | `auto` (CUDA, then Apple MPS, then CPU), `cpu`, `mps`, `cuda:0` |
| `CONFIDENCE_THRESHOLD` | `0.25` | Detections below this confidence are discarded |
| `INFERENCE_IMAGE_SIZE` | `640` | Size images are scaled to for the model |
| `MAX_UPLOAD_MB` | `10` | Upload limit; keep `client_max_body_size` in `frontend/default.conf.template` in step |
| `MAX_IMAGE_MEGAPIXELS` | `50` | Largest image accepted, checked from the file header before decoding |
| `UPLOAD_DIR` | `uploads` | Where original and annotated images are stored |

## API

| Endpoint | Purpose |
| --- | --- |
| `GET /health` | Service, database and model status (503 if the database is unreachable) |
| `POST /detect` | Upload a JPEG, PNG or WebP image; stores and returns the inspection |
| `GET /inspections?limit=&offset=` | History, newest first |
| `GET /inspection/{id}` | One inspection with its damage items |
| `GET /inspection/{id}/image/{original\|annotated}` | Stored images |
| `DELETE /inspection/{id}` | Delete the record and its images |
| `GET /report/{id}` (also `POST`) | PDF report |

## Repository map

- `backend/app`: FastAPI routes (`main.py`), services (`services/`), models, migrations (`migrations/`)
- `backend/tests`: pytest suite
- `frontend/src`: React + TypeScript app (`pages/`, `components/`, `lib/`, `api.ts`)
- `model`: YOLO11 detection training pipeline (`training/`, `configs/`, `tests/`) and the weights location; see [docs/MODEL_TRAINING.md](docs/MODEL_TRAINING.md)
- `datasets`: where RDD2022 is placed and prepared (not tracked)
- `infra`, `scripts`, `DEPLOYMENT.md`: Azure Container Apps deployment
- `docs`: audit, implementation report, architecture
