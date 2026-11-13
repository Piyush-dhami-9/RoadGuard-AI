"""Demo and trained modes must be distinguishable everywhere and never swapped silently (C8, M4)."""
from pathlib import Path
import cv2
import numpy as np
import pytest
from app import main
from app.services import inference as inference_module
from app.services.inference import DEMO_MODEL_NAME, InferenceService, ModelUnavailableError
from tests.conftest import WORKDIR, road_image


class FakeYolo:
    task = "segment"

    def __call__(self, image, verbose=False):
        class Result:
            masks = None
            boxes = []
        return [Result()]


@pytest.fixture
def weights_file() -> Path:
    path = WORKDIR / "best.pt"
    path.write_bytes(b"not real weights - loader is faked in these tests")
    yield path
    path.unlink()


def test_health_reports_demo_mode_and_database(client):
    body = client.get("/health").json()
    assert body["status"] == "ok" and body["database"] == "ok"
    assert body["inference_mode"] == "demo"
    assert body["model"]["model_name"] == DEMO_MODEL_NAME
    assert "not a trained model" in body["model"]["detail"]
    assert body["max_upload_mb"] == 2


def test_health_is_503_when_the_database_is_down(client, monkeypatch):
    async def unreachable() -> bool:
        return False
    monkeypatch.setattr(main, "database_is_reachable", unreachable)
    response = client.get("/health")
    assert response.status_code == 503
    assert response.json()["status"] == "degraded" and response.json()["database"] == "unavailable"


def test_demo_results_are_labelled_in_response_database_and_image(client, uploaded):
    assert uploaded["inference_mode"] == "demo"
    assert uploaded["model_name"] == DEMO_MODEL_NAME and uploaded["model_version"] == "1"
    assert client.get("/inspections").json()[0]["inference_mode"] == "demo"
    plain = InferenceService("absent.pt", "demo")._demo(road_image())[1]
    served = cv2.imdecode(np.frombuffer(client.get(uploaded["annotated_image_url"]).content, np.uint8), cv2.IMREAD_COLOR)
    band = served[:20].astype(int)
    assert (band[..., 2] - band[..., 0]).mean() > 60, "annotated image should carry the red DEMO band"
    assert (plain[:20].astype(int)[..., 2] - plain[:20].astype(int)[..., 0]).mean() < 10


def test_auto_mode_without_weights_is_demo_only_in_development():
    assert InferenceService("absent.pt", "auto", "development").status.mode == "demo"
    production = InferenceService("absent.pt", "auto", "production")
    assert production.status.mode == "unavailable"
    with pytest.raises(ModelUnavailableError):
        production.detect(road_image())


def test_trained_mode_without_weights_is_unavailable():
    assert InferenceService("absent.pt", "trained", "development").status.mode == "unavailable"


def test_explicit_demo_mode_is_allowed_in_production():
    assert InferenceService("absent.pt", "demo", "production").status.mode == "demo"


@pytest.mark.parametrize("mode", ["auto", "trained"])
def test_weights_that_fail_to_load_never_fall_back_to_demo(weights_file, monkeypatch, mode):
    def broken_loader(path):
        raise ImportError("No module named 'ultralytics'")
    monkeypatch.setattr(inference_module, "load_yolo", broken_loader)
    service = InferenceService(str(weights_file), mode, "development")
    assert service.status.mode == "unavailable"
    assert "ultralytics" in service.status.detail
    with pytest.raises(ModelUnavailableError):
        service.detect(road_image())


def test_real_loader_failure_on_invalid_weights_is_reported(weights_file):
    # No monkeypatching: whether ultralytics is missing or the file is rejected, the result must be "unavailable".
    assert InferenceService(str(weights_file), "auto").status.mode == "unavailable"


def test_non_segmentation_weights_are_refused(weights_file, monkeypatch):
    fake = FakeYolo()
    fake.task = "detect"
    monkeypatch.setattr(inference_module, "load_yolo", lambda path: fake)
    status = InferenceService(str(weights_file), "trained").status
    assert status.mode == "unavailable" and "'detect'" in status.detail


def test_loaded_weights_report_trained_mode_with_name_and_fingerprint(weights_file, monkeypatch):
    monkeypatch.setattr(inference_module, "load_yolo", lambda path: FakeYolo())
    service = InferenceService(str(weights_file), "auto", "production")
    assert service.status.mode == "trained"
    assert service.status.model_name == "best.pt" and len(service.status.model_version) == 12
    detections, overlay = service.detect(road_image())
    assert detections == [] and np.array_equal(overlay, road_image()), "trained output must not carry the demo band"


def test_detect_returns_503_and_stores_nothing_when_model_unavailable(client, road_jpeg, monkeypatch):
    monkeypatch.setattr(main, "inference", InferenceService("absent.pt", "trained"))
    response = client.post("/detect", files={"file": ("r.jpg", road_jpeg, "image/jpeg")})
    assert response.status_code == 503
    assert "no weights file" in response.json()["detail"]
    health = client.get("/health")
    assert health.status_code == 200 and health.json()["status"] == "degraded" and health.json()["inference_mode"] == "unavailable"
    assert client.get("/inspections").json() == []
    assert list((WORKDIR / "uploads").glob("*")) == []


def test_trained_inspection_is_recorded_as_trained(client, road_jpeg, weights_file, monkeypatch):
    monkeypatch.setattr(inference_module, "load_yolo", lambda path: FakeYolo())
    monkeypatch.setattr(main, "inference", InferenceService(str(weights_file), "trained"))
    body = client.post("/detect", files={"file": ("r.jpg", road_jpeg, "image/jpeg")}).json()
    assert body["inference_mode"] == "trained" and body["model_name"] == "best.pt"
