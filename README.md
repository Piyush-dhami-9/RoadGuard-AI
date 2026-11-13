# RoadGuard AI

RoadGuard AI is a road-inspection platform: upload a road-surface image, get flagged damage regions, an estimated severity and repair priority, a stored inspection record, and a PDF report.

> **Current status: DEMO mode only.** No trained model ships with this repository. Until trained weights are supplied, results come from a brightness-threshold placeholder detector and are **not AI predictions**. Every result is labelled with how it was produced, in the API, the UI, the annotated image and the PDF. See [docs/PROJECT_AUDIT.md](docs/PROJECT_AUDIT.md) and [docs/IMPLEMENTATION_REPORT.md](docs/IMPLEMENTATION_REPORT.md).

Severity and priority are estimated indicators from image-space (pixel) measurements. They are not physical dimensions and not a certified engineering assessment.

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
```

## Inference modes

| `INFERENCE_MODE` | Behaviour |
| --- | --- |
| `auto` (default) | Trained model if a weights file exists at `MODEL_WEIGHTS`; otherwise the labelled demo detector. With `APP_ENV=production`, missing weights make the model *unavailable* instead. |
| `demo` | Always the labelled demo detector. The only way to run demo output in production. |
| `trained` | Weights are required. If they are missing or fail to load, `/detect` returns 503. |

Supplied weights that fail to load are never replaced by demo output. `GET /health` reports the active mode and the reason.

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `DATABASE_URL` | local PostgreSQL | SQLAlchemy async URL |
| `CORS_ORIGINS` | `http://localhost:5173` | Comma-separated allowed origins |
| `APP_ENV` | `development` | `production` disables the automatic demo fallback |
| `INFERENCE_MODE` | `auto` | See above |
| `MODEL_WEIGHTS` | `model/weights/best.pt` | Path to trained weights |
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
- `model`: weights location and model notes
- `infra`, `scripts`, `DEPLOYMENT.md`: Azure Container Apps deployment
- `docs`: audit, implementation report, architecture
