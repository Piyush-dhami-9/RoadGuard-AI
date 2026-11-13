# RoadGuard AI workspace

- Backend: Python 3.12, FastAPI, async SQLAlchemy, PostgreSQL.
- Frontend: React, TypeScript, Vite, CSS tokens with a Tailwind-inspired component vocabulary.
- Keep inference, severity scoring, persistence, and report generation in separate services.
- The app must remain runnable without model weights by using the documented demo inference fallback.
- Validate backend changes with `python -m compileall app` and frontend changes with `npm run build`.
