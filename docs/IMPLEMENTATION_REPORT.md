# RoadGuard AI — Implementation Report

This report is updated at the end of each phase. Finding IDs (C1, M4, S2, ...) refer to [PROJECT_AUDIT.md](PROJECT_AUDIT.md).

## Phase 2 — Backend and frontend stabilization (2026-11-13)

### Outcome

The upload, history, detail, image, delete and report workflow now works end to end, rejects bad input with clear errors, and states honestly how each result was produced. **The system still has no trained model**: every result today is DEMO output, and is labelled as such.

### What changed

**Backend reliability**

| Change | Audit finding |
| --- | --- |
| Empty uploads return 400 instead of crashing | C4 |
| File type is determined from the file's content (JPEG, PNG, WebP); headers and names are ignored | — |
| Uploads over `MAX_UPLOAD_MB` (10 MB) return 413; oversized request bodies are refused before being buffered | C5, S2 (size part) |
| Image dimensions are read from the file header and capped at `MAX_IMAGE_MEGAPIXELS` before decoding | S12 |
| Corrupt and truncated images return 400 | — |
| Images are served by `GET /inspection/{id}/image/{original\|annotated}`; only files inside the upload directory can be returned | C1 |
| `/report/{id}` accepts GET as well as POST; PDFs are built in memory, keep the image's aspect ratio, and tolerate a missing image or no damage rows | C2 |
| Deleting an inspection deletes its images; a failed database commit removes the files just written | C7 |
| Decode, detection and PDF rendering run in worker threads | blocking event loop |
| `/health` checks the database (503 when unreachable) and reports the model status | — |
| Timestamps are returned as UTC with an offset | naive timestamps |
| `/inspections` takes `limit` and `offset` | no pagination |
| Unhandled errors are logged and returned as JSON 500 | S11 |
| Schema is managed by Alembic migrations applied at startup; pre-existing databases are upgraded in place | no migrations |

**Honest demo / trained distinction**

| Change | Audit finding |
| --- | --- |
| `INFERENCE_MODE` (`auto`, `demo`, `trained`) and `APP_ENV`; the mode is fixed at startup as `demo`, `trained` or `unavailable` | — |
| Weights that are present but fail to load make the model *unavailable* (503 on `/detect`); there is no fallback to demo | C8 |
| In production, missing weights make the model unavailable unless `INFERENCE_MODE=demo` is set deliberately | — |
| Detection (non-segmentation) weights are refused at startup rather than producing zero-area results | M5 (guard only) |
| `inference_mode`, `model_name`, `model_version` are stored on every inspection and returned by the API | M4, M11 |
| Demo annotated images carry a red "DEMO - PLACEHOLDER DETECTOR, NOT AN AI PREDICTION" band | M4 |
| PDF reports open with a DEMO / TRAINED MODEL / NOT RECORDED banner and end with the estimate disclaimer | M4 |
| The UI shows the live mode from `/health`, a DEMO banner, a source badge on every row and detail page; "Model ready · v1.0.0", "AI segmentation analysis", "Good morning, Jordan" and the fixed donut percentages are gone | M4, frontend fiction |

**Frontend**

- Split the single 29-line file into `api.ts`, `lib/`, `components/` and `pages/`.
- Annotated image and PDF download go through the API. The report is fetched and saved, so failures are shown instead of opening a blank tab.
- Server error messages are shown to the user. An unreachable API has its own message and a Retry button.
- Upload checks type and size before sending and reads the limit from the API.
- History: search (ID, damage type, severity, source, date), severity filter, sort by date or severity, CSV export of the visible rows.
- Delete from the detail page, with confirmation.
- Settings, Search, Notifications, the avatar and the "This year" button were removed. No control in the interface is non-functional.
- Mobile: `index.html` now has a viewport tag and the menu button opens the navigation.
- Measurements are labelled as pixels of the bounding box, with a disclaimer; a Critical severity style exists for the next phase.
- `npm run dev` proxies `/api` to the backend.
- Dependencies are pinned to exact versions; Vite was raised from 8.3.0 to 8.3.8 to clear a published advisory.

**Configuration**

- nginx `client_max_body_size 11m` (10 MB file plus multipart framing), matching the API.
- Compose files pass `INFERENCE_MODE`; the production file sets `APP_ENV=production` and defaults to `trained`. The no-op runtime `VITE_API_URL` was removed. The reports volume was removed because reports are no longer written to disk.
- Frontend image uses `npm ci`.

### Tests executed

All run on 2026-11-13 on the development Mac.

| Suite | Command | Result |
| --- | --- | --- |
| Backend | `python -m pytest` in `backend/` | **46 passed**, 0 failed |
| Frontend | `npm test` in `frontend/` | **34 passed**, 0 failed |
| Frontend type-check and build | `npm run build` | passed |
| Frontend dependency audit | `npm audit` | 0 vulnerabilities |

Backend tests cover: health, upload validation (empty, non-image, wrong headers, truncated, garbage, tiny, oversized, streamed oversized, decompression bomb), detection and persistence, history order and pagination, detail, image serving and path containment, deletion with file cleanup, cleanup after a failed commit, every inference-mode rule, 503 when the model is unavailable, PDF by GET and POST with content checks, and migrations (fresh, legacy upgrade with rows intact, idempotent, models match schema).

Frontend tests cover: mode indicator, absence of the old hardcoded claims and dead controls, unreachable API and retry, upload workflow, server-side and client-side rejection, history search/filter/sort, CSV export, report download and its failure, delete, image fallback, mobile navigation.

Manual integration checks, also on 2026-11-13:

| Check | Result |
| --- | --- |
| Backend + Vite dev server, full workflow through the `/api` proxy (health, detect, image, report by GET, empty and non-image uploads, list, delete) | passed |
| PostgreSQL 16 in a container: database created by the *original* code with one inspection, then started with the new backend | stamped `0001`, upgraded to `0002`, row and damage intact, `inference_mode = 'unknown'` |
| Backend restart against the migrated PostgreSQL database | no migrations re-run, healthy |
| PostgreSQL stopped while the backend runs | `/health` reports `degraded`, database `unavailable` |
| Frontend image build from `frontend/Dockerfile` | built (93.6 MB) |

### Not verified

- **nginx at runtime.** The 11 MB limit and the proxy config were not exercised in a running container: Docker on the development machine stopped starting containers partway through. The config change is one directive and the image builds, but the 1 MB bug (C3) is fixed on paper only until this is run.
- **`docker compose up` as a whole**, and the backend image build.
- **The trained-model path with real weights.** Mode handling is tested with a stand-in loader; no real YOLO model has been run.
- **The UI in a real browser.** Component tests run in jsdom; layout, dark mode and the mobile drawer were not looked at on a device.

### Azure

- Public access was restricted on 2026-11-13: both container apps have an ingress rule allowing one IP address. Verified: an external network receives 403 from both apps; the owner's address receives 200. Steps to change or remove the rule are in `DEPLOYMENT.md`.
- Nothing was deployed. The live site still runs the September image, including its bugs. It remains unauthenticated behind the IP rule.
- `infra/main.bicep` does not contain the rule; a redeploy may drop it.

### Remaining issues

| Area | Issue |
| --- | --- |
| Model | No weights, dataset, training or evaluation. The trained path still assumes segmentation and a hardcoded class order (M1, M2, M5, M6, M7). Phase 3. |
| Demo detector | Still assigns classes by list position and derives "confidence" from area (M3). It is labelled, not improved. |
| Severity | Still resolution-dependent, class-blind, three levels, undocumented priority formula (M8 to M10). Phase 4. |
| Authentication | None. Design agreed, not built; see below. Phase 7. |
| Rate limiting | None (S2, rate part). |
| Credentials | Default `roadguard:roadguard` fallbacks, published database port, admin database user, plaintext password file (S3 to S9). Phase 7 and 8. |
| Azure storage | Uploads are on ephemeral disk and not shared between replicas. |
| Compose | No backend or frontend healthchecks, hardcoded healthcheck user, no restart policy. Phase 8. |
| Database | Missing fields from the Phase 5 list: processing status, original filename, image dimensions. Timestamp column is still timezone-naive in storage (values are UTC). |
| Oversized upload through the Vite dev proxy | The backend refuses the body early and the dev proxy reports 502 rather than 413. The UI blocks such files before sending, so users do not meet this. |
| CI | Tests are not run automatically. |
| Port 8000 | Another process on the development Mac already listens on 8000. Run the backend on another port and set `VITE_DEV_API_TARGET` if that process is needed. |

### Authentication design for Phase 7

Agreed constraints: the backend is not reachable from the internet; the public entry point enforces authentication itself; no secret reaches the React bundle; a service key alone is not treated as sufficient.

1. **Backend ingress becomes internal.** Only nginx can reach it. The frontend is built with `/api` so the browser never talks to the backend directly.
2. **Operator login at the API, enforced on every request.** `POST /auth/login` checks a single operator's password (stored as an Argon2 hash in configuration), and sets a signed, `HttpOnly`, `Secure`, `SameSite=Strict` session cookie. Every other route except `/health` requires a valid session. Login attempts are rate limited.
3. **Service key between nginx and the backend** as a second layer: nginx adds a header from its environment; the backend rejects requests without it. This protects against anything else inside the environment, and is not what authenticates the user.
4. **Shaped for growth.** Routes depend on a `current_user` object with a `role`, and inspections gain a nullable `created_by`. Moving to several inspectors means adding a users table and role checks, not rewriting routes.

The frontend already routes every call through `api.ts`, so adding the login screen and 401 handling touches one module.

### Files

Created: `backend/alembic.ini`, `backend/requirements-dev.txt`, `backend/app/migrations/` (env, template, two revisions), `backend/app/services/analysis.py`, `backend/app/services/images.py`, `backend/tests/` (conftest and five test modules), `frontend/src/api.ts`, `frontend/src/lib/inspections.ts` and its test, `frontend/src/components/` (2), `frontend/src/pages/` (4), `frontend/src/App.test.tsx`, `frontend/src/test/` (2), `model/weights/.gitkeep`, `docs/IMPLEMENTATION_REPORT.md`.

Modified: `backend/app/main.py`, `db.py`, `models.py`, `schemas.py`, `core/config.py`, `services/inference.py`, `services/report.py`, `services/severity.py`, `backend/requirements.txt`, `backend/Dockerfile`, `frontend/src/App.tsx`, `styles.css`, `index.html`, `vite.config.ts`, `package.json`, `package-lock.json`, `Dockerfile`, `default.conf.template`, `docker-compose.yml`, `docker-compose.prod.yml`, `.env.example`, `.gitignore`, `README.md`, `DEPLOYMENT.md`, `docs/architecture.md`, `database/README.md`, `model/README.md`, `.github/copilot-instructions.md`.

Removed: `reports/.gitkeep` (reports are no longer written to disk).

### Next phase

See Phase 3 below.

## Phase 3, part 1 — Dataset preparation and training pipeline (2026-11-13, branch `phase-3-yolo11`)

### Outcome

A YOLO11 **detection** pipeline for RDD2022 exists: fetch, prepare, train, evaluate. It has been run end to end as a smoke test on real data. **No model has been trained and there are no accuracy figures.** The application is unchanged and still runs the DEMO detector.

### What was added

| Path | Purpose |
| --- | --- |
| `model/training/classes.py` | The four classes in RDD2022 order (D00, D10, D20, D40) with the names the app displays |
| `model/training/voc.py` | Pascal VOC parsing, box validation, conversion to YOLO format |
| `model/training/splits.py` | Group-based train/val/test split to limit leakage |
| `model/training/prepare_rdd2022.py` | Dataset preparation with a full issue report |
| `model/training/fetch_rdd2022.py` | Downloads chosen countries from the figshare archive without fetching all 13 GB |
| `model/training/train.py`, `evaluate.py`, `common.py` | Training, evaluation (precision, recall, mAP50, mAP50-95), device detection, guards |
| `model/configs/` | Full-run and smoke-test configs |
| `model/tests/` | 93 tests |
| `docs/MODEL_TRAINING.md`, `datasets/README.md` | Documentation |

`.gitignore` now keeps datasets, runs, label caches and weights out of Git (only `datasets/README.md` is tracked). No backend, frontend, database or Docker file was changed. A matching `.dockerignore` update, which keeps `datasets/` and `runs/` out of image build contexts, is pending as a separate change.

### Tests executed

| Suite | Command | Result |
| --- | --- | --- |
| Model pipeline | `python -m pytest model/tests` | **93 passed** |
| Backend (unchanged code) | `python -m pytest` in `backend/` | **46 passed** |
| Frontend (unchanged code) | `npm test` in `frontend/` | **34 passed** |

Runs on real data (development M1, 8 GB, Ultralytics 8.3.55, PyTorch 2.15.0):

| Step | Result |
| --- | --- |
| Fetch Czech (257 MB) | 2,829 annotation files and 3,538 images, matching the official file list |
| Prepare Czech | 2,829 images, 1,745 boxes (D00 988, D10 399, D20 161, D40 197), 1,757 images with no supported damage, 709 unlabelled test images ignored, no issues reported, 7 seconds |
| Smoke subset | 200 images with damage, split 163 / 18 / 19 |
| Smoke training | completed on `mps` in 69 seconds, `best.pt` written, not exported |
| Smoke evaluation | completed; all metrics 0.000, as expected after 2 epochs on 163 images |

The smoke-test numbers are not model results and are recorded here only as evidence that the pipeline executes.

### Not done or not verified

- **No full training run.** It needs a GPU machine.
- **Only the Czech subset has been through preparation.** The other six country sets are untested against the script.
- **CUDA has not been exercised**; only Apple MPS.
- **The backend cannot load detection weights yet.** Its trained path still assumes segmentation and refuses detection weights. This is the next step.
- The leakage control is a heuristic; see `docs/MODEL_TRAINING.md`.

### Next

Convert the backend inference path to YOLO11 detection (boxes, class names read from the model, confidence threshold, device detection), keeping the DEMO detector until that path is tested with real weights. Then severity (Phase 4).
