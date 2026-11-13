# RoadGuard AI — Project Audit (Phase 1)

Audit date: 2026-11-13. No project file was modified during this audit; this document is the only file added.

## 1. Summary

RoadGuard AI is a small, coherent prototype: about 300 lines of backend Python, one 29-line React file, and working Azure infrastructure. The request/response plumbing and persistence work. Three things do not:

1. **There is no AI.** No weights, no dataset, no training code, and the Docker image does not install the YOLO runtime. Every result, locally and on the live Azure site, comes from a brightness threshold that labels dark regions with damage classes chosen by loop index. The UI presents this as "AI segmentation analysis" with "Model ready · v1.0.0".
2. **Three user-visible features are broken in the frontend**: the annotated image never displays, the PDF download returns 405, and uploads over 1 MB fail when served through Docker Compose.
3. **The live Azure deployment is public and unauthenticated.** Anyone with the URL can upload files of any size and delete any inspection.

Nothing here requires a rewrite. The structure is sound enough to fix in place.

## 2. How the audit was done

| Method | What it covered |
| --- | --- |
| Read every source, config, infra and doc file | All findings |
| Ran the unmodified backend in a throwaway venv outside the repo, against SQLite, with synthetic images | Findings marked **[verified]** |
| Read-only `GET` to the two documented Azure URLs | Deployment status |

Not verified, and why:

- **Docker Compose startup** — the Docker daemon was not running. Compose findings are from reading the files.
- **PostgreSQL behaviour** — the probe used SQLite. The summary in `.azure/summary.copilotmd` reports the endpoints working against Azure PostgreSQL; I did not re-test that.
- **Frontend build** — the local `frontend/node_modules` is damaged (no `.bin` directory; the TypeScript binary aborts on launch). Frontend findings are from reading `App.tsx` and the nginx config. A `frontend/dist` build exists from an earlier run.
- **The YOLO code path** — it cannot run without weights and `ultralytics`. Findings are from reading the code.

## 3. Existing architecture

```
Browser ── React SPA (one file, state-based page switching, no router)
   │  fetch  ${VITE_API_URL || '/api'}
   ▼
nginx (frontend container) ── /api/* → rewrite → BACKEND_ORIGIN      [Compose path]
   │                           (Azure: browser calls the backend directly, cross-origin)
   ▼
FastAPI (app/main.py: all routes and orchestration in one module)
   ├─ services/inference.py   YOLO branch (never active) | OpenCV demo branch
   ├─ services/severity.py    pixel-based score → Low/Medium/High, priority formula
   ├─ services/report.py      ReportLab PDF
   ├─ models.py / db.py       async SQLAlchemy, tables created by create_all at startup
   └─ local disk              uploads/, reports/generated/
   ▼
PostgreSQL 16 ── tables: inspections, damages
```

Deployment: `scripts/deploy-azure.sh` builds `linux/amd64` images locally, pushes to ACR, and applies `infra/main.bicep` (Container Apps, PostgreSQL Flexible Server, Log Analytics) in East Asia.

Size: backend 313 lines across 8 files; frontend 1 component file (15 KB on 29 lines) plus 1 stylesheet; no tests; no CI; **the directory is not a git repository**.

## 4. Completed features

These work as written **[verified]** unless noted:

- `GET /health` returns status and inference mode.
- `POST /detect` decodes an image, runs the demo detector, writes original and annotated JPEGs, persists an inspection with damage rows, returns it.
- `GET /inspections`, `GET /inspection/{id}` (404 for missing, 422 for non-integer id).
- `DELETE /inspection/{id}` removes the database rows (cascade to damages).
- `POST /report/{id}` returns a valid PDF.
- Non-image bytes are rejected with 400; a non-image content type with 415.
- Upload filenames are server-generated UUIDs, so there is no path traversal or collision risk from client filenames.
- CORS allows only the configured origin.
- Frontend: dashboard KPIs, history table, upload with drag-and-drop and preview, detail page, dark mode.
- Azure: both documented URLs respond 200; the backend reports `opencv-demo-fallback`. Images are built for `linux/amd64`; the nginx upstream is configurable at runtime.

## 5. Critical bugs

| ID | Bug | Evidence |
| --- | --- | --- |
| C1 | **Annotated image never displays.** The backend has no route or static mount for `uploads/`. The frontend requests `/<annotated_image_path>`, which nginx answers with `index.html`. | `GET /uploads/annotated-….jpg` → 404 **[verified]**. `App.tsx:28`, `main.py` has no `StaticFiles`. |
| C2 | **PDF download is broken in the UI.** The button calls `window.open(...)`, a GET; the route only accepts POST. | `GET /report/1` → 405 **[verified]**. `App.tsx:28`, `main.py:83`. |
| C3 | **Uploads over 1 MB fail under Docker Compose.** nginx's default `client_max_body_size` is 1 MB and the config does not raise it, while the UI advertises 10 MB. Most phone photos exceed 1 MB. The UI reports "Check that the backend is running". Azure is not affected because the browser bypasses nginx there. | `frontend/default.conf.template` (by reading). |
| C4 | **Empty upload crashes the endpoint.** `cv2.imdecode` raises on an empty buffer and nothing catches it. | Empty file → 500 **[verified]**. `main.py:40`. |
| C5 | **No upload size or dimension limit.** The whole body is read into memory, then decoded. | A 108 MB, 6000×6000 PNG was accepted and processed **[verified]**. `main.py:39`. |
| C6 | **Documented local dev flow does not work.** `vite.config.ts` has no proxy, and the API base defaults to `/api`, so `npm run dev` sends API calls to the Vite server. Running `uvicorn` from `backend/` also looks for weights in `backend/model/…` and writes reports to `backend/reports/…`, not the repo-level directories. | `vite.config.ts`, `App.tsx:6`, `core/config.py:8-10`. |
| C7 | **Deleting an inspection leaves its files.** Original image, annotated image and PDF stay on disk. | **[verified]**. `main.py:73-81`. |
| C8 | **YOLO failures are silent.** If weights exist but `ultralytics` is missing or loading fails, a bare `except` swallows the error and the service serves demo output with no log line. With the default Docker build (`INSTALL_MODEL_DEPS=false`) this is exactly what would happen after adding `best.pt`. | `inference.py:24-29`, `backend/Dockerfile:8`, `deploy-azure.sh:70`. |

## 6. Other bugs and incomplete features

### Backend

- **Blocking work on the event loop.** Image decode, inference, file writes and PDF rendering run inside `async` handlers; one slow request stalls all others.
- **Files are written before the database commit**, with no cleanup if the commit fails. `cv2.imwrite` return values are not checked.
- **Stored paths are relative to the process working directory** (`uploads/x.jpg`), so records break if the service starts elsewhere.
- **Timestamps are timezone-naive.** The API returns `2026-11-13T11:35:00` with no offset; the browser interprets it as local time, so displayed times are wrong by the UTC offset.
- **`/inspections` has no pagination** and eager-loads every damage row for every inspection.
- **`report.py:14`**: `Path("").exists()` is true, so a null annotated path would crash PDF generation. The image is forced to 480×300, distorting any other aspect ratio. Reports are written to a fixed filename per inspection, so concurrent requests race. Report files are never cleaned up.
- **Severity thresholds are duplicated** in `main.py:52` and `severity.py:16-20`.
- **`/health` does not check the database.**
- **Logging** is one `basicConfig` call; no request, error or model-load logging.
- `latitude`/`longitude` columns exist but nothing ever writes them.
- `main.py:43` uses `__import__('uuid')` inline.

### Frontend

- **Hardcoded fiction presented as live state:** "System operational / Model ready · v1.0.0", "Good morning, Jordan", avatar "JL", "AI segmentation analysis". The severity donut uses fixed 18% / 29% / 53% segments regardless of data.
- **Dead controls:** Settings, Search, notifications, mobile menu, Export CSV, history search box, both history filter buttons, "This year", "View history".
- **No navigation on phones.** Below 650 px the sidebar is hidden and the menu button does nothing.
- **`index.html` is a single line** with no doctype, `<title>`, `lang`, or viewport meta tag. Without the viewport tag, mobile browsers render the desktop layout and the media queries do not take effect.
- **Never calls** `GET /health`, `GET /inspection/{id}` or `DELETE`. There is no delete UI. The detail page uses the list payload.
- **Errors are generic.** Server messages (415, 400) are discarded; every failure says the backend may be down.
- Measurements are labelled "Surface area", "Length", "Avg width" as if physical; they are bounding-box pixels.
- No "Critical" styling exists (`pill.low/medium/high` only).
- Everything lives in one file with very long lines; unused imports (`useMemo`, `Trash2`). Object URLs are not revoked.
- `package.json` pins every dependency to `"latest"` and lists build tools under `dependencies`. The lockfile currently resolves to React 19.3, Vite 8.3 and TypeScript 7.0. The Dockerfile uses `npm install`, not `npm ci`.

## 7. AI/ML limitations

| ID | Finding |
| --- | --- |
| M1 | **No trained weights.** `model/weights/` does not exist. |
| M2 | **No dataset, training script, data config or evaluation code.** `model/` contains one three-line README. |
| M3 | **The demo detector does not detect road damage.** It thresholds pixels darker than 88/255, keeps up to four blobs, assigns class by position in the sorted list (`CLASSES[index % 4]`), and derives "confidence" from blob area. In testing **[verified]**: a 200×200 dark square was labelled "Longitudinal Crack"; an undamaged image with a shadow across half of it was labelled "Pothole, 96% confidence, High severity, priority 93.2". |
| M4 | **Demo output is not labelled.** Nothing in the API response, database, PDF or UI marks a result as demo. Only `/health` reveals the mode, and the frontend never calls it. |
| M5 | **The YOLO branch assumes segmentation.** It reads `result.masks`; with a detection model, masks are `None`, every area becomes 0, and severity collapses. RDD2022 provides bounding boxes only, so a model trained on it is incompatible with this code. |
| M6 | **Class order is hardcoded and does not match RDD2022.** The code uses `[Pothole, Longitudinal, Transverse, Alligator]`; RDD2022's order is D00 Longitudinal, D10 Transverse, D20 Alligator, D40 Pothole. Indexing a hardcoded list instead of reading `model.names` would mislabel every class. |
| M7 | **No device selection, confidence threshold, or image-size setting.** |
| M8 | **Severity is resolution-dependent.** Width saturates at 25 px and length at 500 px regardless of image size. The same crack scored 55.2 (Medium) at 12 MP and 10.8 (Low) when the image was scaled to 640 px **[verified]**. "Width" is the short side of the bounding box, not crack width. |
| M9 | **Severity ignores damage class**, has no Critical level, and takes the single worst item as the overall result, ignoring count and coverage. |
| M10 | **Priority formula is undocumented**: `0.72·score + 20·confidence + 2·min(count, 4)`. High confidence raises priority even for minor damage. |
| M11 | **No model name, version or mode is stored** with an inspection, so past results cannot be traced to what produced them. |

### RDD2022 as a training source

RDD2022 fits the four target classes and is the standard public dataset for this task. Points to settle before using it:

- **Task type:** bounding boxes, so the model must be YOLO11 *detection*. The inference pipeline should be changed to detection rather than waiting for masks that will not exist.
- **Format:** annotations are Pascal VOC XML and need converting to YOLO text labels. Some country subsets include extra classes that must be filtered out.
- **Size versus this machine:** the full dataset is on the order of 10 GB or more (to be confirmed at download). This Mac currently has **7.8 GB free disk** and 8 GB RAM. Full training locally is not practical. Realistic options are a free GPU notebook (Colab or Kaggle) for the real run, with a small subset and `yolo11n` locally only as a smoke test of the pipeline.
- **Licence:** must be read and recorded before training and before publishing weights.
- **Domain:** images are mostly vehicle-mounted forward views. Accuracy on top-down or handheld photos will differ and must be measured, not assumed.

## 8. Database findings

- Schema is created by `Base.metadata.create_all` at startup. **There are no migrations** (no Alembic). `create_all` never alters existing tables, so any new column would silently not appear in the live Azure database.
- Against the Phase 5 requirements, these fields are missing: model name, model version, inference mode, processing status, error message, original filename, image dimensions, per-inspection coverage, recommended action.
- `timestamp` is naive `DateTime`.
- No index on `damages.inspection_id`.
- The damage class column is named `class`, a reserved word in Python and awkward in SQL.
- No uniqueness or check constraints on severity values.
- The live Azure database was reported empty after deployment testing (`.azure/summary.copilotmd`); I did not query it.

## 9. Security concerns

| ID | Concern |
| --- | --- |
| S1 | **No authentication on a public API.** The Azure backend has external ingress. Anyone can create, read and delete inspections. |
| S2 | **No upload limits or rate limiting** (see C5). An attacker can exhaust memory or disk with a few requests. |
| S3 | **Default credentials `roadguard:roadguard`** are hardcoded as fallbacks in `config.py`, both Compose files, and `.env.example`. The production Compose file falls back to them silently. |
| S4 | **PostgreSQL port 5432 is published to the host** in both Compose files, including production. |
| S5 | **The database password is stored in plaintext** at `.azure/postgres-admin-password` and passed as a command-line argument by the deploy script. It is gitignored, but there is no git repository yet, so that protection is not active. I did not read the file's contents. |
| S6 | **The application connects as the PostgreSQL admin user.** |
| S7 | **Azure PostgreSQL firewall allows all Azure services** (`0.0.0.0` rule), i.e. any Azure tenant. |
| S8 | **ACR admin credentials** are used for image pulls instead of a managed identity. |
| S9 | The password is interpolated into the connection URL without URL-encoding (`main.bicep:20`); a password containing `@`, `/` or `:` would break the connection. |
| S10 | Backend container runs as root. `/docs` and `/openapi.json` are exposed in production. |
| S11 | Unhandled exceptions return framework 500s; there is no global handler or structured error format. |
| S12 | Decompression-bomb exposure: image dimensions are not checked before or after decode. |
| S13 | No security headers in nginx. Fonts load from Google at runtime. |

## 10. Deployment limitations

### Docker Compose

- Healthcheck hardcodes `-U roadguard -d roadguard`; changing `POSTGRES_USER` breaks it.
- The development Compose file hardcodes `DATABASE_URL`, ignoring `.env`.
- No healthcheck on backend or frontend; frontend `depends_on` backend without a readiness condition.
- No restart policies.
- `VITE_API_URL` is set as a *runtime* variable on the frontend in `docker-compose.prod.yml`. It is a build-time value, so this line has no effect.
- The backend image always installs PyTorch but, by default, not `ultralytics`. The default image therefore carries the weight of torch with none of the capability.
- Root `.dockerignore` excludes `model/weights`, so weights can only arrive by volume mount. That is reasonable, but undocumented for Azure, where no volume exists.

### Azure

- **Uploads and PDFs are on ephemeral container disk** and are lost on restart or scale-out. With `maxReplicas: 3`, a file written by one replica is invisible to the others.
- **No path exists to deploy model weights** (no volume, not in image).
- No liveness or readiness probes.
- Backend has 1 CPU / 2 GiB. YOLO11n on CPU should fit; this needs measuring once a model exists.
- `DEPLOYMENT.md` mixes the real East Asia deployment with generic `eastus` examples and lists `VITE_API_URL` as a production runtime variable.
- The deploy script prompts for nothing before changing live resources; it should not be run without a deliberate decision.

### Project hygiene

- Not a git repository: no history, no way to review or revert changes.
- No tests of any kind, no linter or formatter configuration, no CI.
- `frontend/dist`, `tsconfig.tsbuildinfo`, `__pycache__` and a 24-package partial `node_modules` are present in the tree.

## 11. Recommended implementation order

1. **Safety net.** `git init` and a first commit of the current state, so every later change is reviewable and reversible.
2. **Backend stabilization (Phase 2a).** Fix C1, C2, C4, C5, C7. Split routes from orchestration. Move blocking work off the event loop. Add logging, a global error handler, and a database check in `/health`. Add backend tests alongside each fix.
3. **Honest model status (Phase 3a).** Add an explicit inference mode setting (`demo` / `trained`), fail loudly in production when weights are missing, record mode and model version on every inspection, and label demo results in the API, UI and PDF. This comes before training because it is what stops the product misrepresenting itself today.
4. **Database (Phase 5).** Introduce Alembic with a baseline migration matching the current schema, then a second migration adding the new columns. Existing rows are preserved.
5. **Detection pipeline (Phase 3b).** Convert the YOLO branch to detection, read class names from the model, add device detection and thresholds, and split into loader / inference / classifier modules. Test with a stock `yolo11n.pt` to prove the pipeline runs — clearly marked as not a road-damage model.
6. **Severity and priority (Phase 4).** Resolution-independent, class-aware scoring with four levels and a documented formula.
7. **Frontend (Phase 2b).** Fix integrations, add model-status indicator, delete, real error messages, working mobile navigation; remove or implement dead controls; split the single file into components. Add frontend tests.
8. **Training pipeline.** Dataset conversion script, training and evaluation scripts, and a documented run on a hosted GPU. Weights and metrics appear only after a real run.
9. **Security and deployment (Phases 7–8).** Upload limits, rate limiting, API-key auth, credentials without defaults in production, Compose healthchecks, closed database port, non-root image, persistent storage for Azure, updated docs.
10. **`docs/IMPLEMENTATION_REPORT.md`** and README, written from what was actually done and measured.

## 12. Decisions needed from the project owner

| # | Decision | Recommendation |
| --- | --- | --- |
| 1 | Initialise git before changes begin? | Yes. |
| 2 | Where will the real training run happen? | Hosted GPU notebook; local machine for smoke tests only. |
| 3 | Authentication model for the deployed API | A single API key held by the nginx proxy, with the backend's ingress made internal, as the minimum. User accounts only if multiple inspectors are planned. |
| 4 | The live Azure site is open to the internet in demo mode today | Either restrict it now or accept the exposure knowingly until Phase 7. No deployment will be made without approval. |
| 5 | Dead UI controls (search, filters, CSV export, settings, notifications) | Implement search, severity filter, sort and CSV export, which are cheap and useful; remove settings and notifications until there is something behind them. |
