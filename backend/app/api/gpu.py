import os
import json
import logging
import glob as _glob
from fastapi import APIRouter, UploadFile, File, HTTPException, Body, Request
from fastapi.responses import FileResponse
from sqlalchemy import select
from app.database import async_session
from app.models.job import Job
from app.config import settings

router = APIRouter(prefix="/api/v1/gpu")
logger = logging.getLogger(__name__)

GPU_SECRET = os.environ.get("GPU_SECRET", "gpu-worker-secret")


@router.get("/video/{job_id}")
async def serve_video(job_id: str):
    """Serve the original uploaded video for the workbench viewer."""
    job_dir = os.path.join(settings.upload_dir, job_id)
    candidates = _glob.glob(os.path.join(job_dir, "video.*"))
    if not candidates:
        raise HTTPException(status_code=404, detail="Video not found")
    return FileResponse(candidates[0], media_type="video/mp4")


def _check_auth(request: Request):
    auth = request.headers.get("Authorization", "")
    if auth != f"Bearer {GPU_SECRET}" and GPU_SECRET != "gpu-worker-secret":
        raise HTTPException(status_code=401, detail="Unauthorized")


@router.get("/pending")
async def get_pending_jobs():
    async with async_session() as session:
        result = await session.execute(
            select(Job).where(Job.status == "uploaded").order_by(Job.created_at).limit(3)
        )
        jobs = result.scalars().all()
        return [
            {"id": j.id, "settings": json.loads(j.settings) if j.settings else {}}
            for j in jobs
        ]


@router.get("/video/{job_id}")
async def download_video(job_id: str):
    job_dir = os.path.join(settings.upload_dir, job_id)
    candidates = _glob.glob(os.path.join(job_dir, "video.*"))
    if not candidates:
        raise HTTPException(status_code=404, detail="Video file not found")
    return FileResponse(candidates[0], media_type="video/mp4")


@router.post("/status/{job_id}")
async def update_status(job_id: str, data: dict = Body(...)):
    async with async_session() as session:
        result = await session.execute(select(Job).where(Job.id == job_id))
        job = result.scalar_one_or_none()
        if job:
            job.status = data.get("status", job.status)
            job.progress = data.get("progress", job.progress)
            detail = data.get("detail", "")
            if data.get("error_message"):
                job.error_message = data["error_message"]
            # Store detail as part of settings (JSON), since Job model has no detail column
            if detail:
                import json
                try:
                    s = json.loads(job.settings or "{}")
                except:
                    s = {}
                s["_detail"] = detail
                job.settings = json.dumps(s)
            await session.commit()
    return {"ok": True}


@router.post("/result/{job_id}")
async def upload_result_raw(job_id: str, request: Request):
    """Accept raw binary GLB upload (used by GPU worker for large files)."""
    content_type = request.headers.get("content-type", "")
    if "multipart" in content_type:
        # Multipart fallback
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

    import time as _time
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


@router.post("/result_mesh/{job_id}")
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


# ── Streaming WebSocket manager ──────────────────────────────────
_stream_connections: dict[str, list] = {}


@router.post("/stream/{job_id}")
async def receive_stream_batch(job_id: str, request: Request, batch: int = 0, count: int = 0):
    """Receive binary point cloud batch from GPU Worker, broadcast to WebSocket clients."""
    data = await request.body()

    # Broadcast binary data to all WebSocket clients for this job
    connections = _stream_connections.get(job_id, [])
    if connections:
        # Send header JSON first: {"type":"batch","batch":N,"count":N}
        import json as _json
        header = _json.dumps({"type": "batch", "batch": batch, "count": count}).encode()
        for ws in list(connections):
            try:
                await ws.send_bytes(header + b"\x00" + data)
            except Exception:
                pass

    # Also update job progress
    if batch >= 0 and count > 0:
        async with async_session() as session:
            result = await session.execute(select(Job).where(Job.id == job_id))
            job = result.scalar_one_or_none()
            if job and job.status in ("processing", "uploaded"):
                job.status = "processing"
                job.progress = min(0.85, 0.1 + batch * 0.05)  # 5% per batch
                await session.commit()

    return {"ok": True, "sent_to": len(connections)}
