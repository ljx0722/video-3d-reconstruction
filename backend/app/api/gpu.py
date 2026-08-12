import glob as _glob
import json
import logging
import os
import secrets
import tempfile

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from sqlalchemy import select, update

from app.config import settings
from app.database import async_session
from app.models.job import Job

router = APIRouter(prefix="/api/v1/gpu")
logger = logging.getLogger(__name__)

_ARTIFACT_METADATA_KEY = "_artifact_metadata"
_MESH_STATS_KEY = "_mesh_stats"

GPU_SECRET = os.environ.get("GPU_SECRET", "").strip()


async def _verify_gpu(request: Request):
    """Require the shared GPU Worker bearer token."""
    if not GPU_SECRET or GPU_SECRET == "gpu-worker-secret":
        raise HTTPException(status_code=503, detail="GPU worker authentication is not configured")
    auth = request.headers.get("Authorization", "")
    prefix = "Bearer "
    if not auth.startswith(prefix) or not secrets.compare_digest(auth[len(prefix):], GPU_SECRET):
        raise HTTPException(status_code=401, detail="Unauthorized")


def _validate_glb(data: bytes, label: str) -> None:
    if len(data) < 20:
        raise HTTPException(status_code=400, detail=f"{label} GLB is empty")
    if data[:4] != b"glTF":
        raise HTTPException(status_code=400, detail=f"{label} is not a binary GLB")
    declared_length = int.from_bytes(data[8:12], "little")
    if declared_length != len(data):
        raise HTTPException(status_code=400, detail=f"{label} GLB length is invalid")


def _write_atomic(path: str, data: bytes) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, temp_path = tempfile.mkstemp(prefix=".upload-", suffix=".tmp", dir=os.path.dirname(path))
    try:
        with os.fdopen(fd, "wb") as temp_file:
            temp_file.write(data)
            temp_file.flush()
            os.fsync(temp_file.fileno())
        os.replace(temp_path, path)
    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)


def _merge_status_settings(settings_json: str | None, status: str, data: dict) -> str | None:
    try:
        job_settings = json.loads(settings_json or "{}")
    except (json.JSONDecodeError, TypeError):
        job_settings = {}
    if not isinstance(job_settings, dict):
        job_settings = {}

    changed = False
    detail = data.get("detail", "")
    if detail:
        job_settings["_detail"] = detail
        changed = True

    if status == "partial":
        if detail:
            job_settings["_mesh_error"] = (
                detail.removeprefix("Mesh 生成失败:").strip()
                if detail.startswith("Mesh 生成失败:")
                else detail
            )
            changed = True
    elif status == "failed" and detail.startswith("Mesh 生成失败:"):
        job_settings["_mesh_error"] = detail.removeprefix("Mesh 生成失败:").strip()
        changed = True
    elif status == "completed":
        if "_mesh_error" in job_settings:
            job_settings.pop("_mesh_error")
            changed = True

    for payload_key, settings_key in (
        ("artifact_metadata", _ARTIFACT_METADATA_KEY),
        ("mesh_stats", _MESH_STATS_KEY),
    ):
        if payload_key in data:
            if data[payload_key] is None:
                if settings_key in job_settings:
                    job_settings.pop(settings_key)
                    changed = True
            else:
                job_settings[settings_key] = data[payload_key]
                changed = True

    if status == "completed" and "mesh_stats" not in data:
        if _MESH_STATS_KEY in job_settings:
            job_settings.pop(_MESH_STATS_KEY)
            changed = True
    elif status == "partial" and "mesh_stats" not in data:
        if _MESH_STATS_KEY in job_settings:
            job_settings.pop(_MESH_STATS_KEY)
            changed = True

    if not changed:
        return settings_json
    return json.dumps(job_settings, ensure_ascii=False)


@router.get("/video/{job_id}", dependencies=[Depends(_verify_gpu)])
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
        for job in jobs:
            stmt = (
                update(Job)
                .where(Job.id == job.id, Job.status == "uploaded")
                .values(status="processing", progress=0.01)
            )
            claimed = await session.execute(stmt)
            if claimed.rowcount and claimed.rowcount > 0:
                await session.commit()
                output.append({
                    "id": job.id,
                    "settings": json.loads(job.settings) if job.settings else {},
                })
        return output


@router.post("/status/{job_id}", dependencies=[Depends(_verify_gpu)])
async def update_status(job_id: str, data: dict = Body(...)):
    async with async_session() as session:
        result = await session.execute(select(Job).where(Job.id == job_id))
        job = result.scalar_one_or_none()
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")

        job.status = data.get("status", job.status)
        job.progress = data.get("progress", job.progress)
        if data.get("error_message"):
            job.error_message = data["error_message"]
        elif job.status == "completed":
            job.error_message = None
        if data.get("num_frames") is not None:
            job.num_frames = data["num_frames"]
        if data.get("num_points") is not None:
            job.num_points = data["num_points"]
        if data.get("processing_time_secs") is not None:
            job.processing_time_secs = data["processing_time_secs"]

        job.settings = _merge_status_settings(job.settings, job.status, data)
        await session.commit()
    return {"ok": True}


@router.post("/result/{job_id}", dependencies=[Depends(_verify_gpu)])
async def upload_result_raw(job_id: str, request: Request):
    """Save the point-cloud GLB without completing the job before Mesh upload."""
    content_type = request.headers.get("content-type", "")
    if "multipart" in content_type:
        form = await request.form()
        uploaded = form.get("file")
        if not uploaded:
            raise HTTPException(status_code=400, detail="No file in multipart")
        glb_data = await uploaded.read()
    else:
        glb_data = await request.body()
    _validate_glb(glb_data, "Point cloud")

    async with async_session() as session:
        result = await session.execute(select(Job).where(Job.id == job_id))
        job = result.scalar_one_or_none()
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")

        glb_path = os.path.join(settings.upload_dir, job_id, "result.glb")
        _write_atomic(glb_path, glb_data)
        job.status = "processing"
        job.progress = max(job.progress or 0.0, 0.9)
        job.result_path = f"results/{job_id}/pointcloud.glb"
        await session.commit()

    logger.info("GPU result saved for job %s: %.1f MB", job_id, len(glb_data) / 1024 / 1024)
    return {"ok": True}


@router.post("/result_mesh/{job_id}", dependencies=[Depends(_verify_gpu)])
async def upload_result_mesh(job_id: str, request: Request):
    """Validate and atomically save the triangle-mesh GLB."""
    glb_data = await request.body()
    _validate_glb(glb_data, "Mesh")

    async with async_session() as session:
        result = await session.execute(select(Job).where(Job.id == job_id))
        job = result.scalar_one_or_none()
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")
        mesh_path = os.path.join(settings.upload_dir, job_id, "result_mesh.glb")
        _write_atomic(mesh_path, glb_data)
        job.progress = max(job.progress or 0.0, 0.95)
        await session.commit()

    logger.info("GPU mesh saved for job %s: %.1f MB", job_id, len(glb_data) / 1024 / 1024)
    return {"ok": True}
