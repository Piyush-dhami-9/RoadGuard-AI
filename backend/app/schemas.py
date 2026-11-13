from datetime import datetime
from pydantic import BaseModel, ConfigDict


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
    model_config = ConfigDict(from_attributes=True)
    id: int
    image_path: str
    annotated_image_path: str | None
    timestamp: datetime
    latitude: float | None
    longitude: float | None
    damage_count: int
    overall_severity: str
    priority_score: float
    damages: list[DamageResponse] = []
