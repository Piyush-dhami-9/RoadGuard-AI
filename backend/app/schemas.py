from datetime import datetime, timezone
from pydantic import BaseModel, ConfigDict, computed_field, field_validator


class DamageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    class_name: str
    confidence: float
    area: float
    length: float
    width: float
    severity: str
    severity_score: float
    bbox: dict[str, float]


class InspectionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, protected_namespaces=())
    id: int
    image_path: str
    annotated_image_path: str | None
    timestamp: datetime
    latitude: float | None
    longitude: float | None
    damage_count: int
    overall_severity: str
    priority_score: float
    inference_mode: str
    model_name: str | None
    model_version: str | None
    damages: list[DamageResponse] = []

    @field_validator("timestamp")
    @classmethod
    def stored_timestamps_are_utc(cls, value: datetime) -> datetime:
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)

    @computed_field
    @property
    def image_url(self) -> str:
        return f"/inspection/{self.id}/image/original"

    @computed_field
    @property
    def annotated_image_url(self) -> str | None:
        return f"/inspection/{self.id}/image/annotated" if self.annotated_image_path else None


class ModelStatusResponse(BaseModel):
    model_config = ConfigDict(protected_namespaces=())
    mode: str
    model_name: str | None
    model_version: str | None
    detail: str


class HealthResponse(BaseModel):
    status: str
    database: str
    inference_mode: str
    model: ModelStatusResponse
    max_upload_mb: int


class DeleteResponse(BaseModel):
    deleted: int


class ErrorResponse(BaseModel):
    detail: str
