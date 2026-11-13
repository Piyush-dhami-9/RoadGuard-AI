from pathlib import Path
from typing import Literal
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: Literal["development", "production"] = "development"
    database_url: str = "postgresql+asyncpg://roadguard:roadguard@localhost:5432/roadguard"
    cors_origins: str = "http://localhost:5173"
    model_weights: str = "model/weights/roadguard-yolo11-rdd2022.pt"
    # demo: always the labelled placeholder detector.
    # yolo: the trained YOLO11 detection weights are required; never replaced by demo output.
    #       ("trained" is accepted as an older name for yolo.)
    # auto: yolo when the weights file exists, otherwise demo in development and unavailable in production.
    inference_mode: Literal["auto", "demo", "yolo", "trained"] = "auto"
    inference_device: str = "auto"  # auto | cpu | mps | cuda:0 ...
    confidence_threshold: float = Field(0.25, ge=0.0, le=1.0)
    inference_image_size: int = Field(640, ge=32, le=4096)
    upload_dir: Path = Path("uploads")
    max_upload_mb: int = 10
    max_image_megapixels: int = 50
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def weights_path(self) -> Path:
        """MODEL_WEIGHTS as a path. A relative value is looked up from the working directory, then the project root."""
        given = Path(self.model_weights).expanduser()
        if given.is_absolute():
            return given
        here = Path(__file__).resolve()
        for base in (Path.cwd(), here.parents[2], here.parents[3]):
            if (base / given).is_file():
                return base / given
        return given

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024


settings = Settings()
settings.upload_dir.mkdir(parents=True, exist_ok=True)
