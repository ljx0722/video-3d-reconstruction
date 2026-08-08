from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from app.services import storage_service
import os

router = APIRouter(prefix="/files")


@router.get("/{job_id}/result.glb")
async def get_result_file(job_id: str):
    glb_path = os.path.join(storage_service.settings.upload_dir, job_id, "result.glb")
    if not os.path.exists(glb_path):
        raise HTTPException(status_code=404, detail="Result file not found")
    return FileResponse(glb_path, media_type="model/gltf-binary",
                        headers={"Cache-Control": "public, max-age=86400"})
