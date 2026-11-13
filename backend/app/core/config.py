from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://roadguard:roadguard@localhost:5432/roadguard"
    cors_origins: str = "http://localhost:5173"
    model_weights: str = "model/weights/best.pt"
    upload_dir: Path = Path("uploads")
    report_dir: Path = Path("reports/generated")
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",")]


settings = Settings()
settings.upload_dir.mkdir(parents=True, exist_ok=True)
settings.report_dir.mkdir(parents=True, exist_ok=True)
