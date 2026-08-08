import json
import uuid
import logging
from fastapi import APIRouter, UploadFile, File, Form, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.models.job import Job
from app.schemas.job import JobCreate, JobResponse, JobSettings
from app.services import storage_service, task_broker
from sqlalchemy import select, desc

router = APIRouter(prefix="/api/v1")
logger = logging.getLogger(__name__)


@router.post("/jobs/upload", response_model=dict)
async def upload_job(
    file: UploadFile = File(...),
    settings: str = Form(default='{"fps":10,"mode":"streaming","conf_threshold":1.5}'),
    db: AsyncSession = Depends(get_db),
):
    try:
        job_settings = JobSettings.model_validate(json.loads(settings))
    except (json.JSONDecodeError, ValueError) as e:
        raise HTTPException(status_code=400, detail=f"Invalid settings: {e}")

    content_type = file.content_type or ""
    if not content_type.startswith("video/"):
        raise HTTPException(status_code=400, detail="File must be a video")

    job_id = str(uuid.uuid4())
    video_key = f"videos/{job_id}/raw.mp4"
    contents = await file.read()
    file_size_mb = len(contents) / (1024 * 1024)

    from app.config import settings as app_settings
    if file_size_mb > app_settings.max_video_size_mb:
        raise HTTPException(status_code=413, detail=f"File exceeds {app_settings.max_video_size_mb}MB limit")

    await storage_service.upload_bytes(contents, video_key, content_type)

    job = Job(
        id=job_id,
        session_id="anonymous",
        status="uploaded",
        video_path=video_key,
        settings=job_settings.model_dump_json(),
    )
    db.add(job)
    await db.commit()

    task_broker.enqueue_gpu_job(job_id)

    return {"id": job_id, "status": "uploaded"}


@router.get("/jobs", response_model=list)
async def list_jobs(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Job).order_by(desc(Job.created_at)).limit(50))
    jobs = result.scalars().all()
    return [_job_to_response(j) for j in jobs]


@router.get("/jobs/{job_id}", response_model=dict)
async def get_job(job_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Job).where(Job.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return _job_to_response(job)


@router.delete("/jobs/{job_id}")
async def delete_job(job_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Job).where(Job.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    await db.delete(job)
    await db.commit()
    return {"ok": True}


def _job_to_response(job: Job) -> dict:
    settings = None
    if job.settings:
        try:
            settings = json.loads(job.settings)
        except json.JSONDecodeError:
            pass
    return {
        "id": job.id,
        "status": job.status,
        "progress": job.progress,
        "settings": settings,
        "result_url": f"/files/{job.id}/result.glb" if job.result_path else None,
        "error_message": job.error_message,
        "num_frames": job.num_frames,
        "num_points": job.num_points,
        "processing_time_secs": job.processing_time_secs,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "updated_at": job.updated_at.isoformat() if job.updated_at else None,
    }
