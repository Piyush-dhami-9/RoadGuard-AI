from datetime import datetime, timezone
from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator
from .services.damage_classes import CLASS_IDS


ESTIMATE = "Estimated indicator from image-space measurements; not a physical measurement or a certified engineering assessment."


class DamageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    class_name: str
    confidence: float = Field(description="Detector confidence, 0 to 1")
    area: float = Field(description="Region area in image pixels (bounding-box area for model detections). Not a road-surface area.")
    length: float = Field(description="Long side of the bounding box in image pixels. Not a physical length.")
    width: float = Field(description="Short side of the bounding box in image pixels. Not a physical width.")
    severity: str = Field(description=f"Low, Medium, High or Critical. {ESTIMATE}")
    severity_score: float = Field(description=f"0 to 100. {ESTIMATE}")
    bbox: dict[str, float] = Field(description="Bounding box corners x1, y1, x2, y2 in image pixels")

    @computed_field
    @property
    def class_id(self) -> int | None:
        return CLASS_IDS.get(self.class_name)


class InspectionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, protected_namespaces=())
    id: int
    image_path: str
    annotated_image_path: str | None
    timestamp: datetime
    latitude: float | None
    longitude: float | None
    damage_count: int
    overall_severity: str = Field(description=f"Low, Medium, High or Critical. {ESTIMATE}")
    priority_score: float = Field(description=f"Repair-priority indicator, 0 to 100. {ESTIMATE}")
    inference_mode: str = Field(description="What produced this result: 'trained' (YOLO11 model), 'demo' (placeholder, not AI) or 'unknown' (recorded before tracking)")
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
    mode: str = Field(description="'trained' (YOLO11 model in use), 'demo' (placeholder, not AI) or 'unavailable'")
    model_name: str | None
    model_version: str | None
    detail: str
    configured_mode: str = Field("auto", description="The INFERENCE_MODE setting")
    loaded: bool = Field(False, description="True only when trained YOLO weights are loaded and passed a test prediction")
    task: str | None = None
    device: str | None = None
    confidence_threshold: float | None = None
    classes: dict[int, str] = {}


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
