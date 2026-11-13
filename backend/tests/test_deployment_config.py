"""Guards on deployment configuration: one weights path everywhere, and no AI runtime in the default image."""
import re
from pathlib import Path
from app.core.config import Settings

REPO = Path(__file__).resolve().parents[2]
WEIGHTS = "model/weights/roadguard-yolo11-rdd2022.pt"
COMPOSE_FILES = ("docker-compose.yml", "docker-compose.prod.yml")


def read(name: str) -> str:
    return (REPO / name).read_text()


def test_application_default_is_the_training_pipeline_output(monkeypatch):
    monkeypatch.delenv("MODEL_WEIGHTS")  # the test environment overrides it; this checks the built-in default
    assert Settings(_env_file=None).model_weights == WEIGHTS
    training = read("model/training/common.py")
    assert 'DEFAULT_WEIGHTS = REPO_ROOT / "model" / "weights" / "roadguard-yolo11-rdd2022.pt"' in training
    assert f"export_to: {WEIGHTS}" in read("model/configs/rdd2022_yolo11n.yaml")


def test_no_configuration_file_names_a_different_weights_file():
    for name in (*COMPOSE_FILES, ".env.example", "infra/main.bicep", "backend/Dockerfile", "DEPLOYMENT.md"):
        assert "best.pt" not in read(name), f"{name} still refers to the old weights name"
    assert f"MODEL_WEIGHTS={WEIGHTS}" in read(".env.example")
    assert WEIGHTS in read("infra/main.bicep")


def test_compose_files_pass_the_weights_path_through_and_mount_the_weights_folder_read_only():
    for name in COMPOSE_FILES:
        compose = read(name)
        assert re.search(r"^      MODEL_WEIGHTS:\s*$", compose, re.M), f"{name} must not hardcode MODEL_WEIGHTS"
        assert "- ./model/weights:/app/model/weights:ro" in compose
        assert "INSTALL_MODEL_DEPS: ${INSTALL_MODEL_DEPS:-false}" in compose
        for setting in ("INFERENCE_DEVICE", "CONFIDENCE_THRESHOLD", "INFERENCE_IMAGE_SIZE"):
            assert re.search(rf"^      {setting}:\s*$", compose, re.M)
    assert "INFERENCE_MODE: ${INFERENCE_MODE:-yolo}" in read("docker-compose.prod.yml") and "APP_ENV: production" in read("docker-compose.prod.yml")
    assert "INFERENCE_MODE: ${INFERENCE_MODE:-auto}" in read("docker-compose.yml")


def test_default_image_does_not_install_the_ai_runtime():
    dockerfile = read("backend/Dockerfile")
    assert "ARG INSTALL_MODEL_DEPS=false" in dockerfile
    model_branch, default_branch = re.search(r'if \[ "\$INSTALL_MODEL_DEPS" = "true" \]; then(.*?)else(.*?)fi', dockerfile, re.S).groups()
    assert "torch==" in model_branch and "download.pytorch.org/whl/cpu" in model_branch and "-r requirements.txt" in model_branch
    assert "torch" not in default_branch and "grep -v '^ultralytics=='" in default_branch
    assert dockerfile.count("torch==") == 1, "PyTorch must only be installed inside the model-dependency branch"
    assert re.search(r"^ultralytics==", read("backend/requirements.txt"), re.M), "the Dockerfile filters on this exact line prefix"
