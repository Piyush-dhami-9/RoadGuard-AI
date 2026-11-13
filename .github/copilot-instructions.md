# RoadGuard AI workspace

- Backend: Python 3.12, FastAPI, async SQLAlchemy, PostgreSQL.
- Frontend: React, TypeScript, Vite, CSS tokens with a Tailwind-inspired component vocabulary.
- Keep inference, severity scoring, persistence, and report generation in separate services.
- Without model weights the app runs the DEMO detector in development only; demo output is always labelled and never substituted for a trained model that failed to load.
- Validate backend changes with `python -m pytest` (from `backend`) and frontend changes with `npm test` and `npm run build` (from `frontend`).
- Schema changes need an Alembic migration in `backend/app/migrations/versions`.
