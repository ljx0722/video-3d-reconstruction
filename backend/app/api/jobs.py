import json
import uuid
import logging
import os
from fastapi import APIRouter, UploadFile, File, Form, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.models.job import Job
from app.schemas.job import JobSettings
from app.services import storage_service
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

    contents = await file.read()
    file_size_mb = len(contents) / (1024 * 1024)

    from app.config import settings as app_settings
    if file_size_mb > app_settings.max_video_size_mb:
        raise HTTPException(status_code=413, detail=f"文件超过{app_settings.max_video_size_mb}MB限制")

    job_id = str(uuid.uuid4())

    await storage_service.save_upload(job_id, contents, content_type)
    await storage_service.save_settings(job_id, job_settings.model_dump_json())

    job = Job(
        id=job_id,
        session_id="anonymous",
        status="uploaded",
        video_path=job_id,
        settings=job_settings.model_dump_json(),
    )

    # Store file metadata in settings so frontend can show file name/size
    try:
        s = json.loads(job.settings)
        s["file_name"] = file.filename
        s["file_size_bytes"] = len(contents)
        job.settings = json.dumps(s)
    except Exception:
        pass

    db.add(job)
    await db.commit()

    # GPU Worker polls for pending jobs, no local processing needed
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


@router.get("/jobs/{job_id}/video")
async def get_job_video(job_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Job).where(Job.id == job_id))
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Job not found")
    job_dir = os.path.join(storage_service.settings.upload_dir, job_id)
    candidates = sorted(
        os.path.join(job_dir, name)
        for name in os.listdir(job_dir)
        if name.startswith("video.")
    ) if os.path.isdir(job_dir) else []
    if not candidates:
        raise HTTPException(status_code=404, detail="Video not found")
    from fastapi.responses import FileResponse
    return FileResponse(candidates[0], media_type="video/mp4")


@router.delete("/jobs/{job_id}")
async def delete_job(job_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Job).where(Job.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    import shutil
    job_dir = os.path.join(storage_service.settings.upload_dir, job_id)
    if os.path.exists(job_dir):
        shutil.rmtree(job_dir)

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
    job_dir = os.path.join(storage_service.settings.upload_dir, job.id)
    point_cloud_available = os.path.isfile(os.path.join(job_dir, "result.glb"))
    mesh_available = os.path.isfile(os.path.join(job_dir, "result_mesh.glb"))
    mesh_error = settings.get("_mesh_error") if settings else None
    return {
        "id": job.id,
        "status": job.status,
        "progress": job.progress,
        "settings": settings,
        "result_url": f"/files/{job.id}/result.glb",
        "point_cloud_available": point_cloud_available,
        "mesh_available": mesh_available,
        "mesh_error": mesh_error,
        "error_message": job.error_message,
        "num_frames": job.num_frames,
        "num_points": job.num_points,
        "processing_time_secs": job.processing_time_secs,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "updated_at": job.updated_at.isoformat() if job.updated_at else None,
        "detail": settings.get("_detail", "") if settings else "",
        "file_name": settings.get("file_name", "") if settings else "",
        "file_size_bytes": settings.get("file_size_bytes", 0) if settings else 0,
    }
