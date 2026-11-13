# RoadGuard AI

RoadGuard AI is a full-stack road inspection platform. Upload a road image, detect surface damage, measure severity, prioritize repairs, and export a professional report.

## Run it

```bash
cp .env.example .env
docker compose up --build
```

Open `http://localhost:5173` for the dashboard and `http://localhost:8000/docs` for the API explorer. Without `model/weights/best.pt`, the backend uses a deterministic OpenCV demo detector so the complete workflow remains runnable. Add trained YOLO11 segmentation weights at that path to enable production inference.

## Repository map

- `backend/app`: FastAPI API, SQLAlchemy models, inference, severity, reporting
- `frontend/src`: React + TypeScript dashboard
- `model`: model weights and training notes
- `database`: schema notes and migrations guidance
- `docs`: architecture and API notes
- `reports/generated`: generated PDFs

## API

- `POST /detect`: multipart image upload and persisted analysis
- `GET /inspections`: inspection history
- `GET /inspection/{id}`: detailed inspection with damage items
- `DELETE /inspection/{id}`: remove an inspection
- `POST /report/{id}`: generate and download a PDF report
- `GET /health`: service status

For local frontend development, run the backend with `uvicorn app.main:app --reload` from `backend`, then run `npm install && npm run dev` from `frontend`.
