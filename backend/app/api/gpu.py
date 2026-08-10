import os
import json
import logging
import glob as _glob
from fastapi import APIRouter, Depends, HTTPException, Body, Request
from fastapi.responses import FileResponse
from sqlalchemy import select, update
from app.database import async_session
from app.models.job import Job
from app.config import settings

router = APIRouter(prefix="/api/v1/gpu")
logger = logging.getLogger(__name__)

GPU_SECRET = os.environ.get("GPU_SECRET", "gpu-worker-secret")


async def _verify_gpu(request: Request):
    """Require GPU Worker authentication in production."""
    if GPU_SECRET == "gpu-worker-secret":
        return  # development mode, skip auth
    auth = request.headers.get("Authorization", "")
    if auth != f"Bearer {GPU_SECRET}":
        raise HTTPException(status_code=401, detail="Unauthorized")


@router.get("/video/{job_id}")
async def serve_video(job_id: str):
    """Serve the original uploaded video for the workbench viewer."""
    job_dir = os.path.join(settings.upload_dir, job_id)
    candidates = _glob.glob(os.path.join(job_dir, "video.*"))
    if not candidates:
        raise HTTPException(status_code=404, detail="Video not found")
    return FileResponse(candidates[0], media_type="video/mp4")


@router.get("/pending", dependencies=[Depends(_verify_gpu)])
async def get_pending_jobs():
    """Atomically claim up to 3 uploaded jobs for processing."""
    async with async_session() as session:
        result = await session.execute(
            select(Job).where(Job.status == "uploaded").order_by(Job.created_at).limit(3)
        )
        jobs = result.scalars().all()
        output = []
        for j in jobs:
            # Atomically claim: UPDATE status WHERE id=X AND status='uploaded'
            stmt = (
                update(Job).where(Job.id == j.id, Job.status == "uploaded")
                .values(status="processing", progress=0.01)
            )
            claimed = await session.execute(stmt)
            if claimed.rowcount and claimed.rowcount > 0:
                await session.commit()
                output.append({
                    "id": j.id,
                    "settings": json.loads(j.settings) if j.settings else {},
                })
        return output


@router.post("/status/{job_id}")
async def update_status(job_id: str, data: dict = Body(...)):
    async with async_session() as session:
        result = await session.execute(select(Job).where(Job.id == job_id))
        job = result.scalar_one_or_none()
        if job:
            job.status = data.get("status", job.status)
            job.progress = data.get("progress", job.progress)
            if data.get("error_message"):
                job.error_message = data["error_message"]
            if data.get("num_frames"):
                job.num_frames = data["num_frames"]
            if data.get("num_points"):
                job.num_points = data["num_points"]
            if data.get("processing_time_secs"):
                job.processing_time_secs = data["processing_time_secs"]
            detail = data.get("detail", "")
            if detail:
                try:
                    s = json.loads(job.settings or "{}")
                except Exception:
                    s = {}
                s["_detail"] = detail
                job.settings = json.dumps(s)
            await session.commit()
    return {"ok": True}


@router.post("/result/{job_id}", dependencies=[Depends(_verify_gpu)])
async def upload_result_raw(job_id: str, request: Request):
    """Accept raw binary GLB upload (used by GPU worker for large files)."""
    content_type = request.headers.get("content-type", "")
    if "multipart" in content_type:
        form = await request.form()
        uploaded = form.get("file")
        if uploaded:
            glb_data = await uploaded.read()
        else:
            raise HTTPException(status_code=400, detail="No file in multipart")
    else:
        glb_data = await request.body()

    job_dir = os.path.join(settings.upload_dir, job_id)
    os.makedirs(job_dir, exist_ok=True)
    glb_path = os.path.join(job_dir, "result.glb")
    with open(glb_path, "wb") as f:
        f.write(glb_data)

    async with async_session() as session:
        result = await session.execute(select(Job).where(Job.id == job_id))
        job = result.scalar_one_or_none()
        if job:
            job.status = "completed"
            job.progress = 1.0
            job.result_path = f"results/{job_id}/pointcloud.glb"
            await session.commit()

    logger.info(f"GPU result saved for job {job_id}: {len(glb_data)/1024/1024:.1f} MB")
    return {"ok": True}


@router.post("/result_mesh/{job_id}", dependencies=[Depends(_verify_gpu)])
async def upload_result_mesh(job_id: str, request: Request):
    """Accept raw binary GLB mesh upload from GPU worker."""
    glb_data = await request.body()
    job_dir = os.path.join(settings.upload_dir, job_id)
    os.makedirs(job_dir, exist_ok=True)
    mesh_path = os.path.join(job_dir, "result_mesh.glb")
    with open(mesh_path, "wb") as f:
        f.write(glb_data)
    logger.info(f"GPU mesh saved for job {job_id}: {len(glb_data)/1024/1024:.1f} MB")
    return {"ok": True}
