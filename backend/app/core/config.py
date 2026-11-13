from pathlib import Path
from typing import Literal
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: Literal["development", "production"] = "development"
    database_url: str = "postgresql+asyncpg://roadguard:roadguard@localhost:5432/roadguard"
    cors_origins: str = "http://localhost:5173"
    model_weights: str = "model/weights/best.pt"
    # auto: demo when no weights file exists (development only), trained when one does.
    # demo: always the labelled placeholder detector. trained: weights are required.
    inference_mode: Literal["auto", "demo", "trained"] = "auto"
    upload_dir: Path = Path("uploads")
    max_upload_mb: int = 10
    max_image_megapixels: int = 50
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024


settings = Settings()
settings.upload_dir.mkdir(parents=True, exist_ok=True)
