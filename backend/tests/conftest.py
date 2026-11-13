import os
import sqlite3
import tempfile
from pathlib import Path

# Settings are read at import time, so the test environment is fixed first.
WORKDIR = Path(tempfile.mkdtemp(prefix="roadguard-tests-"))
DB_FILE = WORKDIR / "test.db"
os.environ.update(
    DATABASE_URL=f"sqlite+aiosqlite:///{DB_FILE}",
    UPLOAD_DIR=str(WORKDIR / "uploads"),
    MODEL_WEIGHTS=str(WORKDIR / "absent-weights.pt"),
    INFERENCE_MODE="auto",
    INFERENCE_DEVICE="cpu",
    APP_ENV="development",
    MAX_UPLOAD_MB="2",
    MAX_IMAGE_MEGAPIXELS="8",
)

import cv2  # noqa: E402
import numpy as np  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from app import main  # noqa: E402
from app.services.inference import InferenceService  # noqa: E402


@pytest.fixture(scope="session")
def client():
    with TestClient(main.app, raise_server_exceptions=False) as test_client:
        yield test_client


@pytest.fixture(autouse=True)
def clean_state(client):
    yield
    with sqlite3.connect(DB_FILE) as connection:
        connection.execute("DELETE FROM damages")
        connection.execute("DELETE FROM inspections")
    for path in (WORKDIR / "uploads").glob("*"):
        path.unlink()


@pytest.fixture
def demo_inference(monkeypatch):
    service = InferenceService(str(WORKDIR / "absent-weights.pt"), "demo")
    monkeypatch.setattr(main, "inference", service)
    return service


def encode(image: np.ndarray, extension: str = ".jpg") -> bytes:
    return cv2.imencode(extension, image)[1].tobytes()


def road_image() -> np.ndarray:
    """Grey surface with two dark regions the demo detector will pick up."""
    image = np.full((720, 1280, 3), 150, np.uint8)
    cv2.ellipse(image, (400, 400), (160, 90), 0, 0, 360, (30, 30, 30), -1)
    cv2.rectangle(image, (900, 100), (1100, 300), (20, 20, 20), -1)
    return image


@pytest.fixture
def road_jpeg() -> bytes:
    return encode(road_image())


@pytest.fixture
def uploaded(client, road_jpeg) -> dict:
    response = client.post("/detect", files={"file": ("road.jpg", road_jpeg, "image/jpeg")})
    assert response.status_code == 200, response.text
    return response.json()


class FakeYolo:
    """Stands in for an Ultralytics model: same attributes and predict() signature, scripted output."""
    task = "detect"

    def __init__(self, boxes: list[tuple] = (), names: dict | None = None, task: str = "detect"):
        from app.services.damage_classes import CLASS_NAMES
        self.boxes = list(boxes)  # (x1, y1, x2, y2, confidence, class_id)
        self.names = dict(CLASS_NAMES) if names is None else names
        self.task = task
        self.calls: list[dict] = []

    def predict(self, source, conf, imgsz, device, verbose):
        from types import SimpleNamespace
        self.calls.append({"shape": source.shape, "conf": conf, "imgsz": imgsz, "device": device})
        rows = np.array(self.boxes, dtype=float).reshape(-1, 6)
        return [SimpleNamespace(boxes=SimpleNamespace(xyxy=rows[:, :4], conf=rows[:, 4], cls=rows[:, 5]))]


@pytest.fixture
def weights_file():
    path = WORKDIR / "roadguard-test-weights.pt"
    path.write_bytes(b"placeholder bytes - the loader is replaced in these tests")
    yield path
    path.unlink(missing_ok=True)
    path.with_suffix(".json").unlink(missing_ok=True)


@pytest.fixture
def fake_yolo(monkeypatch):
    """Make the loader return a scripted model. Returns a function: fake_yolo(boxes=[...], **attributes) -> FakeYolo."""
    from app.services import yolo_detector

    def install(boxes: list[tuple] = (), **attributes) -> FakeYolo:
        model = FakeYolo(boxes, **attributes)
        monkeypatch.setattr(yolo_detector, "load_ultralytics_model", lambda path: model)
        return model
    return install
