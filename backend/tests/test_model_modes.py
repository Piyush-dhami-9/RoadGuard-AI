"""Mode selection: DEMO and YOLO must be distinguishable everywhere and never swapped silently."""
import json
import cv2
import numpy as np
import pytest
from app import main
from app.core.config import Settings
from app.services import yolo_detector
from app.services.damage_classes import CLASS_NAMES
from app.services.inference import DEMO_MODEL_NAME, InferenceService, ModelUnavailableError
from tests.conftest import WORKDIR, road_image

ABSENT = WORKDIR / "absent-weights.pt"


def service(weights, mode, env="development", **options) -> InferenceService:
    return InferenceService(weights, mode, env, options.pop("device", "cpu"), **options)


# ---- DEMO mode -----------------------------------------------------------

def test_health_reports_demo_mode_and_database(client):
    body = client.get("/health").json()
    assert body["status"] == "ok" and body["database"] == "ok"
    assert body["inference_mode"] == "demo"
    assert body["model"]["model_name"] == DEMO_MODEL_NAME
    assert "not a trained model" in body["model"]["detail"]
    assert body["model"]["loaded"] is False and body["model"]["task"] is None and body["model"]["classes"] == {}
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
    plain = service(ABSENT, "demo")._demo(road_image())[1]
    served = cv2.imdecode(np.frombuffer(client.get(uploaded["annotated_image_url"]).content, np.uint8), cv2.IMREAD_COLOR)
    band = served[:20].astype(int)
    assert (band[..., 2] - band[..., 0]).mean() > 60, "annotated image should carry the red DEMO band"
    assert (plain[:20].astype(int)[..., 2] - plain[:20].astype(int)[..., 0]).mean() < 10


def test_demo_mode_still_produces_a_complete_inspection(client, uploaded):
    assert uploaded["damage_count"] == 2
    for damage in uploaded["damages"]:
        assert damage["class_name"] in CLASS_NAMES.values() and damage["class_id"] in CLASS_NAMES
        assert damage["severity"] in {"Low", "Medium", "High", "Critical"} and 0 <= damage["severity_score"] <= 100
        assert damage["area"] > 0 and damage["length"] >= damage["width"] > 0


def test_demo_mode_ignores_weights_even_when_they_exist(weights_file, fake_yolo):
    model = fake_yolo([(10, 10, 100, 100, 0.9, 3)])
    demo = service(weights_file, "demo")
    assert demo.status.mode == "demo" and demo.detector is None and model.calls == []


def test_explicit_demo_mode_is_allowed_in_production():
    assert service(ABSENT, "demo", "production").status.mode == "demo"


def test_auto_mode_without_weights_is_demo_only_in_development():
    assert service(ABSENT, "auto", "development").status.mode == "demo"
    production = service(ABSENT, "auto", "production")
    assert production.status.mode == "unavailable"
    with pytest.raises(ModelUnavailableError):
        production.detect(road_image())


# ---- YOLO mode: successful loading ----------------------------------------

@pytest.mark.parametrize("mode", ["yolo", "trained", "auto"])
def test_detection_weights_load_once_and_report_trained_mode(weights_file, fake_yolo, monkeypatch, mode):
    loads = []
    model = fake_yolo()
    monkeypatch.setattr(yolo_detector, "load_ultralytics_model", lambda path: loads.append(path) or model)
    loaded = service(weights_file, mode, "production", confidence_threshold=0.4, image_size=512)
    status = loaded.status
    assert status.mode == "trained" and status.loaded is True and status.configured_mode == mode
    assert status.model_name == weights_file.name and len(status.model_version) == 12
    assert status.task == "detect" and status.device == "cpu" and status.confidence_threshold == 0.4
    assert status.classes == {0: "Longitudinal Crack", 1: "Transverse Crack", 2: "Alligator Crack", 3: "Pothole"}
    for _ in range(3):
        loaded.detect(road_image())
    assert loads == [weights_file], "the weights must be loaded exactly once, not per request"
    assert len(model.calls) == 4, "one test prediction at load, then one per request"
    assert model.calls[-1] == {"shape": (720, 1280, 3), "conf": 0.4, "imgsz": 512, "device": "cpu"}


def test_auto_device_is_detected_from_the_machine(weights_file, fake_yolo, monkeypatch):
    import sys
    import types
    fake_yolo()
    torch = types.SimpleNamespace(cuda=types.SimpleNamespace(is_available=lambda: False), backends=types.SimpleNamespace(mps=types.SimpleNamespace(is_available=lambda: False)))
    monkeypatch.setitem(sys.modules, "torch", torch)
    assert service(weights_file, "yolo", device="auto").status.device == "cpu"
    torch.backends.mps.is_available = lambda: True
    assert service(weights_file, "yolo", device="auto").status.device == "mps"
    torch.cuda.is_available = lambda: True
    assert service(weights_file, "yolo", device="auto").status.device == "cuda:0"
    assert service(weights_file, "yolo", device="cpu").status.device == "cpu", "an explicit device is never overridden"


# ---- YOLO mode: missing and invalid weights -------------------------------

@pytest.mark.parametrize("mode", ["yolo", "trained"])
@pytest.mark.parametrize("env", ["development", "production"])
def test_yolo_mode_with_missing_weights_is_unavailable_never_demo(mode, env):
    missing = service(ABSENT, mode, env)
    assert missing.status.mode == "unavailable" and missing.status.loaded is False and missing.detector is None
    assert "No weights file exists" in missing.status.detail and str(ABSENT) in missing.status.detail
    with pytest.raises(ModelUnavailableError, match="No weights file exists"):
        missing.detect(road_image())


@pytest.mark.parametrize("mode", ["yolo", "auto"])
def test_weights_that_fail_to_load_never_fall_back_to_demo(weights_file, monkeypatch, mode):
    def broken_loader(path):
        raise RuntimeError("invalid load key, 'p'.")
    monkeypatch.setattr(yolo_detector, "load_ultralytics_model", broken_loader)
    broken = service(weights_file, mode)
    assert broken.status.mode == "unavailable"
    assert "not a loadable Ultralytics model" in broken.status.detail and "invalid load key" in broken.status.detail
    with pytest.raises(ModelUnavailableError):
        broken.detect(road_image())


def test_missing_ultralytics_package_is_explained(weights_file, monkeypatch):
    def no_package(path):
        raise ModuleNotFoundError("No module named 'ultralytics'")
    monkeypatch.setattr(yolo_detector, "load_ultralytics_model", no_package)
    detail = service(weights_file, "yolo").status.detail
    assert "'ultralytics' package is not installed" in detail and "INSTALL_MODEL_DEPS=true" in detail


def test_real_loader_rejects_a_file_that_is_not_a_model(weights_file):
    # No stand-in here: whether ultralytics is absent or rejects the file, the outcome must be "unavailable".
    assert service(weights_file, "yolo").status.mode == "unavailable"


@pytest.mark.parametrize("task", ["segment", "classify", "pose", "obb"])
def test_non_detection_weights_are_refused(weights_file, fake_yolo, task):
    fake_yolo(task=task)
    status = service(weights_file, "yolo").status
    assert status.mode == "unavailable" and f"'{task}' model" in status.detail and "object-detection" in status.detail


@pytest.mark.parametrize("names", [
    {index: f"coco{index}" for index in range(80)},                                               # generic pretrained checkpoint
    {0: "Pothole", 1: "Longitudinal Crack", 2: "Transverse Crack", 3: "Alligator Crack"},         # right names, wrong order
    {0: "D00", 1: "D10", 2: "D20", 3: "D40"},
    {0: "Longitudinal Crack", 1: "Transverse Crack", 2: "Alligator Crack"},
])
def test_weights_with_another_class_table_are_refused(weights_file, fake_yolo, names):
    fake_yolo(names=names)
    status = service(weights_file, "yolo").status
    assert status.mode == "unavailable" and "was not trained on RoadGuard's classes" in status.detail


def test_smoke_test_weights_are_refused(weights_file, fake_yolo):
    fake_yolo()
    weights_file.with_suffix(".json").write_text(json.dumps({"smoke_test": True}))
    status = service(weights_file, "yolo").status
    assert status.mode == "unavailable" and "smoke-test run" in status.detail and "not a trained model" in status.detail
    weights_file.with_suffix(".json").write_text(json.dumps({"smoke_test": False}))
    assert service(weights_file, "yolo").status.mode == "trained"


def test_model_that_cannot_predict_is_unavailable(weights_file, fake_yolo):
    model = fake_yolo()

    def failing_predict(**kwargs):
        raise RuntimeError("device 'cuda:0' is not available")
    model.predict = failing_predict
    status = service(weights_file, "yolo", device="cuda:0").status
    assert status.mode == "unavailable" and "failed a test prediction on device 'cuda:0'" in status.detail


# ---- YOLO mode through the API ---------------------------------------------

def test_api_reports_unavailable_and_stores_nothing_when_yolo_weights_are_missing(client, road_jpeg, monkeypatch):
    monkeypatch.setattr(main, "inference", service(ABSENT, "yolo"))
    response = client.post("/detect", files={"file": ("r.jpg", road_jpeg, "image/jpeg")})
    assert response.status_code == 503
    assert "No weights file exists" in response.json()["detail"]
    health = client.get("/health")
    body = health.json()
    assert health.status_code == 200 and body["status"] == "degraded" and body["inference_mode"] == "unavailable"
    assert body["model"]["configured_mode"] == "yolo" and body["model"]["loaded"] is False and body["model"]["model_name"] is None
    assert client.get("/inspections").json() == []
    assert list((WORKDIR / "uploads").glob("*")) == []


def test_api_health_describes_a_loaded_yolo_model(client, weights_file, fake_yolo, monkeypatch):
    fake_yolo()
    monkeypatch.setattr(main, "inference", service(weights_file, "yolo", confidence_threshold=0.3))
    body = client.get("/health").json()
    assert body["status"] == "ok" and body["inference_mode"] == "trained"
    assert body["model"] == {
        "mode": "trained", "model_name": weights_file.name, "model_version": body["model"]["model_version"], "detail": body["model"]["detail"],
        "configured_mode": "yolo", "loaded": True, "task": "detect", "device": "cpu", "confidence_threshold": 0.3,
        "classes": {"0": "Longitudinal Crack", "1": "Transverse Crack", "2": "Alligator Crack", "3": "Pothole"},
    }
    assert "YOLO11 detection model loaded" in body["model"]["detail"]


def test_yolo_inspection_is_stored_and_returned_through_the_existing_contract(client, road_jpeg, weights_file, fake_yolo, monkeypatch):
    fake_yolo([(100, 200, 500, 420, 0.91, 3), (600, 50, 660, 700, 0.55, 0), (5, 5, 50, 50, 0.10, 1)])
    monkeypatch.setattr(main, "inference", service(weights_file, "yolo", confidence_threshold=0.25))
    response = client.post("/detect", files={"file": ("r.jpg", road_jpeg, "image/jpeg")})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["inference_mode"] == "trained" and body["model_name"] == weights_file.name
    assert body["damage_count"] == 2, "the 0.10-confidence box is below the threshold"
    pothole, crack = body["damages"]
    assert (pothole["class_id"], pothole["class_name"], pothole["confidence"]) == (3, "Pothole", 0.91)
    assert pothole["bbox"] == {"x1": 100.0, "y1": 200.0, "x2": 500.0, "y2": 420.0}
    assert (pothole["area"], pothole["length"], pothole["width"]) == (88000.0, 400.0, 220.0)
    assert (crack["class_id"], crack["class_name"]) == (0, "Longitudinal Crack")
    assert set(body) >= {"id", "timestamp", "damage_count", "overall_severity", "priority_score", "inference_mode", "model_name", "model_version", "image_url", "annotated_image_url", "damages"}
    assert client.get(f"/inspection/{body['id']}").json() == body
    assert client.get("/inspections").json()[0]["id"] == body["id"]
    annotated = cv2.imdecode(np.frombuffer(client.get(body["annotated_image_url"]).content, np.uint8), cv2.IMREAD_COLOR)
    assert annotated.shape == (720, 1280, 3)
    band = annotated[:20].astype(int)
    assert (band[..., 2] - band[..., 0]).mean() < 10, "model output must not carry the DEMO band"
    report = client.get(f"/report/{body['id']}")
    assert report.status_code == 200 and report.content.startswith(b"%PDF-")
    assert client.delete(f"/inspection/{body['id']}").status_code == 200


def test_yolo_image_with_no_detections_is_a_valid_empty_inspection(client, road_jpeg, weights_file, fake_yolo, monkeypatch):
    fake_yolo([])
    monkeypatch.setattr(main, "inference", service(weights_file, "yolo"))
    body = client.post("/detect", files={"file": ("r.jpg", road_jpeg, "image/jpeg")}).json()
    assert body["inference_mode"] == "trained" and body["damage_count"] == 0 and body["damages"] == []
    assert body["overall_severity"] == "Low" and body["priority_score"] == 0
    assert client.get(body["annotated_image_url"]).status_code == 200
    assert client.get(f"/report/{body['id']}").status_code == 200


def test_prediction_failure_during_a_request_is_a_500_and_stores_nothing(client, road_jpeg, weights_file, fake_yolo, monkeypatch):
    model = fake_yolo()
    loaded = service(weights_file, "yolo")

    def failing_predict(**kwargs):
        raise RuntimeError("out of memory")
    model.predict = failing_predict
    monkeypatch.setattr(main, "inference", loaded)
    response = client.post("/detect", files={"file": ("r.jpg", road_jpeg, "image/jpeg")})
    assert response.status_code == 500 and response.json() == {"detail": "Internal server error"}
    assert client.get("/inspections").json() == [] and list((WORKDIR / "uploads").glob("*")) == []


# ---- configuration -----------------------------------------------------------

def test_settings_accept_the_documented_modes_and_reject_others(monkeypatch):
    for mode in ("demo", "yolo", "trained", "auto"):
        monkeypatch.setenv("INFERENCE_MODE", mode)
        assert Settings().inference_mode == mode
    monkeypatch.setenv("INFERENCE_MODE", "segmentation")
    with pytest.raises(ValueError):
        Settings()


def test_settings_validate_threshold_and_resolve_relative_weights(monkeypatch, tmp_path):
    monkeypatch.setenv("CONFIDENCE_THRESHOLD", "1.5")
    with pytest.raises(ValueError):
        Settings()
    monkeypatch.setenv("CONFIDENCE_THRESHOLD", "0.6")
    monkeypatch.setenv("INFERENCE_DEVICE", "mps")
    assert (Settings().confidence_threshold, Settings().inference_device) == (0.6, "mps")
    (tmp_path / "weights").mkdir()
    (tmp_path / "weights" / "w.pt").write_bytes(b"x")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("MODEL_WEIGHTS", "weights/w.pt")
    assert Settings().weights_path == tmp_path / "weights" / "w.pt"
    monkeypatch.setenv("MODEL_WEIGHTS", "weights/none.pt")
    assert str(Settings().weights_path) == "weights/none.pt"
    monkeypatch.delenv("MODEL_WEIGHTS")
    assert Settings(_env_file=None).model_weights == "model/weights/roadguard-yolo11-rdd2022.pt"
