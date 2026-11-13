"""Detection workflow, persistence, image serving, deletion. Regressions for C1 and C7."""
from datetime import datetime
from pathlib import Path
from tests.conftest import WORKDIR

UPLOADS = WORKDIR / "uploads"


def test_detect_returns_and_persists_an_inspection(client, uploaded):
    assert uploaded["damage_count"] == len(uploaded["damages"]) == 2
    assert uploaded["overall_severity"] in {"Low", "Medium", "High", "Critical"}
    assert 0 <= uploaded["priority_score"] <= 100
    for damage in uploaded["damages"]:
        assert set(damage["bbox"]) == {"x1", "y1", "x2", "y2"}
        assert 0 <= damage["confidence"] <= 1
    stored = client.get(f"/inspection/{uploaded['id']}").json()
    assert stored == uploaded


def test_timestamp_is_timezone_aware_utc(uploaded):
    parsed = datetime.fromisoformat(uploaded["timestamp"])
    assert parsed.utcoffset() is not None and parsed.utcoffset().total_seconds() == 0


def test_history_is_newest_first_and_paginates(client, road_jpeg):
    ids = [client.post("/detect", files={"file": ("r.jpg", road_jpeg, "image/jpeg")}).json()["id"] for _ in range(3)]
    assert [item["id"] for item in client.get("/inspections").json()] == ids[::-1]
    assert [item["id"] for item in client.get("/inspections", params={"limit": 1, "offset": 1}).json()] == [ids[1]]
    assert client.get("/inspections", params={"limit": 0}).status_code == 422


def test_missing_and_malformed_ids(client):
    assert client.get("/inspection/999999").status_code == 404
    assert client.get("/inspection/abc").status_code == 422
    assert client.delete("/inspection/999999").status_code == 404
    assert client.get("/inspection/999999/image/annotated").status_code == 404


def test_annotated_and_original_images_are_served(client, uploaded):
    for key in ("annotated_image_url", "image_url"):
        response = client.get(uploaded[key])
        assert response.status_code == 200
        assert response.headers["content-type"] == "image/jpeg"
        assert response.content.startswith(b"\xff\xd8\xff")
    assert client.get(f"/inspection/{uploaded['id']}/image/secret").status_code == 422


def test_image_route_never_serves_files_outside_the_upload_directory(client, uploaded):
    import sqlite3
    from tests.conftest import DB_FILE
    outside = WORKDIR / "outside.jpg"
    outside.write_bytes(b"\xff\xd8\xff private")
    with sqlite3.connect(DB_FILE) as connection:
        connection.execute("UPDATE inspections SET annotated_image_path = ? WHERE id = ?", (f"../{outside.name}", uploaded["id"]))
        connection.execute("UPDATE inspections SET image_path = ? WHERE id = ?", (str(outside), uploaded["id"]))
    assert client.get(f"/inspection/{uploaded['id']}/image/annotated").status_code == 404
    assert client.get(f"/inspection/{uploaded['id']}/image/original").status_code == 404


def test_delete_removes_rows_and_files(client, uploaded):
    files = [UPLOADS / Path(uploaded[key]).name for key in ("image_path", "annotated_image_path")]
    assert all(path.is_file() for path in files)
    response = client.delete(f"/inspection/{uploaded['id']}")
    assert response.status_code == 200 and response.json() == {"deleted": uploaded["id"]}
    assert not any(path.exists() for path in files)
    assert client.get(f"/inspection/{uploaded['id']}").status_code == 404
    assert client.delete(f"/inspection/{uploaded['id']}").status_code == 404
    assert list(UPLOADS.glob("*")) == []


def test_image_without_dark_regions_yields_an_empty_inspection(client):
    import numpy as np
    from tests.conftest import encode
    response = client.post("/detect", files={"file": ("clean.jpg", encode(np.full((480, 640, 3), 150, np.uint8)), "image/jpeg")})
    body = response.json()
    assert response.status_code == 200 and body["damage_count"] == 0 and body["damages"] == []
    assert body["overall_severity"] == "Low" and body["priority_score"] == 0


def test_files_are_removed_when_the_database_write_fails(client, road_jpeg, monkeypatch):
    from sqlalchemy.ext.asyncio import AsyncSession

    async def failing_commit(self):
        raise RuntimeError("database went away")
    monkeypatch.setattr(AsyncSession, "commit", failing_commit)
    response = client.post("/detect", files={"file": ("r.jpg", road_jpeg, "image/jpeg")})
    assert response.status_code == 500
    assert response.json() == {"detail": "Internal server error"}
    assert list(UPLOADS.glob("*")) == []
