from datetime import datetime
from typing import Any
from sqlalchemy import DateTime, Float, ForeignKey, Integer, JSON, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .db import Base


class Inspection(Base):
    __tablename__ = "inspections"
    id: Mapped[int] = mapped_column(primary_key=True)
    image_path: Mapped[str] = mapped_column(String(500))
    annotated_image_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    damage_count: Mapped[int] = mapped_column(Integer, default=0)
    overall_severity: Mapped[str] = mapped_column(String(20), default="Low")
    priority_score: Mapped[float] = mapped_column(Float, default=0)
    damages: Mapped[list["Damage"]] = relationship(back_populates="inspection", cascade="all, delete-orphan")


class Damage(Base):
    __tablename__ = "damages"
    id: Mapped[int] = mapped_column(primary_key=True)
    inspection_id: Mapped[int] = mapped_column(ForeignKey("inspections.id", ondelete="CASCADE"))
    class_name: Mapped[str] = mapped_column("class", String(40))
    confidence: Mapped[float] = mapped_column(Float)
    area: Mapped[float] = mapped_column(Float)
    length: Mapped[float] = mapped_column(Float)
    width: Mapped[float] = mapped_column(Float)
    severity: Mapped[str] = mapped_column(String(20))
    severity_score: Mapped[float] = mapped_column(Float)
    bbox: Mapped[dict[str, Any]] = mapped_column(JSON)
    inspection: Mapped[Inspection] = relationship(back_populates="damages")
