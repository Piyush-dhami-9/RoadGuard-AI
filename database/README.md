# Database

PostgreSQL schema is managed with Alembic. Migrations live in `backend/app/migrations/versions` and are applied automatically when the backend starts.

- A database created before migrations existed (by the old `create_all` bootstrap) is detected, stamped as revision `0001`, and upgraded in place. Existing rows are kept.
- Rows that predate revision `0002` have `inference_mode = 'unknown'`, because nothing recorded how they were produced.
- On PostgreSQL an advisory lock serialises migrations when several replicas start together.

## Tables

`inspections`: id, image_path, annotated_image_path, timestamp (UTC, stored without time zone), latitude, longitude, damage_count, overall_severity, priority_score, inference_mode, model_name, model_version.

`damages`: id, inspection_id (indexed, cascade delete), class, confidence, area, length, width, severity, severity_score, bbox (JSON). Area, length and width are image pixels.

## Adding a migration

From `backend/`, with `DATABASE_URL` pointing at a development database that is at the latest revision:

```bash
alembic revision --autogenerate -m "describe the change"
```

Review the generated file, then restart the backend or run `alembic upgrade head`. Never edit a migration that has already been applied anywhere.
