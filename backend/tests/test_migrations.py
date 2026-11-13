"""Schema migrations must upgrade a pre-migration database without losing rows."""
import sqlite3
from sqlalchemy import create_engine
from app.db import run_migrations

LEGACY_SCHEMA = """
CREATE TABLE inspections (id INTEGER PRIMARY KEY, image_path VARCHAR(500) NOT NULL, annotated_image_path VARCHAR(500),
  timestamp DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, latitude FLOAT, longitude FLOAT, damage_count INTEGER NOT NULL,
  overall_severity VARCHAR(20) NOT NULL, priority_score FLOAT NOT NULL);
CREATE TABLE damages (id INTEGER PRIMARY KEY, inspection_id INTEGER NOT NULL REFERENCES inspections(id) ON DELETE CASCADE,
  class VARCHAR(40) NOT NULL, confidence FLOAT NOT NULL, area FLOAT NOT NULL, length FLOAT NOT NULL, width FLOAT NOT NULL,
  severity VARCHAR(20) NOT NULL, severity_score FLOAT NOT NULL, bbox JSON NOT NULL);
INSERT INTO inspections (id, image_path, damage_count, overall_severity, priority_score) VALUES (7, 'uploads/old.jpg', 1, 'High', 81.5);
INSERT INTO damages (inspection_id, class, confidence, area, length, width, severity, severity_score, bbox) VALUES (7, 'Pothole', 0.9, 10, 5, 2, 'High', 80, '{}');
"""


def migrate(path) -> None:
    engine = create_engine(f"sqlite:///{path}")
    with engine.begin() as connection:
        run_migrations(connection)
    engine.dispose()


def columns(path, table: str) -> set[str]:
    with sqlite3.connect(path) as connection:
        return {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}


def test_fresh_database_is_created_at_head(tmp_path):
    path = tmp_path / "fresh.db"
    migrate(path)
    assert {"inference_mode", "model_name", "model_version", "image_path"} <= columns(path, "inspections")
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == ("0002",)


def test_legacy_database_is_upgraded_in_place_with_rows_intact(tmp_path):
    path = tmp_path / "legacy.db"
    with sqlite3.connect(path) as connection:
        connection.executescript(LEGACY_SCHEMA)
    migrate(path)
    with sqlite3.connect(path) as connection:
        row = connection.execute("SELECT id, image_path, overall_severity, priority_score, inference_mode, model_name FROM inspections").fetchall()
        assert row == [(7, "uploads/old.jpg", "High", 81.5, "unknown", None)]
        assert connection.execute("SELECT COUNT(*) FROM damages").fetchone() == (1,)


def test_migrations_are_idempotent(tmp_path):
    path = tmp_path / "twice.db"
    migrate(path)
    migrate(path)
    assert "inference_mode" in columns(path, "inspections")


def test_models_match_the_migrated_schema(tmp_path):
    from app.db import Base
    path = tmp_path / "match.db"
    migrate(path)
    for table in Base.metadata.tables.values():
        assert {column.name for column in table.columns} == columns(path, table.name)
