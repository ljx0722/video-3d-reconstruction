from __future__ import annotations
from datetime import datetime
from pydantic import BaseModel, Field


class JobSettings(BaseModel):
    fps: int = Field(default=10, ge=1, le=60)
    mode: str = Field(default="streaming", pattern=r"^(streaming|windowed)$")
    conf_threshold: float = Field(default=1.5, ge=0.0, le=100.0)


class JobCreate(BaseModel):
    settings: JobSettings = Field(default_factory=JobSettings)


class JobResponse(BaseModel):
    id: str
    status: str
    progress: float
    settings: JobSettings | None = None
    result_url: str | None = None
    error_message: str | None = None
    num_frames: int | None = None
    num_points: int | None = None
    processing_time_secs: float | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class JobListResponse(BaseModel):
    jobs: list[JobResponse]
    total: int
