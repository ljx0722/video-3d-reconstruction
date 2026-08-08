import uuid
from datetime import datetime
from sqlalchemy import String, Float, Integer, Text, DateTime
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID, JSONB


class Base(DeclarativeBase):
    pass


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    session_id: Mapped[str] = mapped_column(String(64), index=True, default="anonymous")
    status: Mapped[str] = mapped_column(String(20), default="uploaded", index=True)
    video_path: Mapped[str | None] = mapped_column(String(512))
    settings: Mapped[str | None] = mapped_column(Text)  # JSON string
    result_path: Mapped[str | None] = mapped_column(String(512))
    error_message: Mapped[str | None] = mapped_column(Text)
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    num_frames: Mapped[int | None] = mapped_column(Integer)
    num_points: Mapped[int | None] = mapped_column(Integer)
    processing_time_secs: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
