import os
import aiofiles
from app.config import settings


async def save_upload(job_id: str, data: bytes, content_type: str = "video/mp4"):
    job_dir = os.path.join(settings.upload_dir, job_id)
    os.makedirs(job_dir, exist_ok=True)
    ext = ".mp4" if "video" in content_type else ""
    video_path = os.path.join(job_dir, f"video{ext}")
    async with aiofiles.open(video_path, "wb") as f:
        await f.write(data)
    return video_path


async def save_settings(job_id: str, settings_json: str):
    job_dir = os.path.join(settings.upload_dir, job_id)
    os.makedirs(job_dir, exist_ok=True)
    async with aiofiles.open(os.path.join(job_dir, "settings.json"), "w") as f:
        await f.write(settings_json)


async def save_glb(job_id: str, data: bytes):
    job_dir = os.path.join(settings.upload_dir, job_id)
    os.makedirs(job_dir, exist_ok=True)
    glb_path = os.path.join(job_dir, "result.glb")
    async with aiofiles.open(glb_path, "wb") as f:
        await f.write(data)
    return glb_path


async def get_glb(job_id: str) -> bytes | None:
    glb_path = os.path.join(settings.upload_dir, job_id, "result.glb")
    if not os.path.exists(glb_path):
        return None
    async with aiofiles.open(glb_path, "rb") as f:
        return await f.read()
