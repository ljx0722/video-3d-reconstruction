from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from app.services import storage_service
import os
import uuid

router = APIRouter(prefix="/files")


def _safe_path(job_id: str, filename: str) -> str:
    try:
        uuid.UUID(job_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid job ID") from None
    p = os.path.realpath(os.path.join(storage_service.settings.upload_dir, job_id, filename))
    base = os.path.realpath(storage_service.settings.upload_dir)
    if not p.startswith(base):
        raise HTTPException(status_code=400, detail="Invalid path")
    return p


@router.get("/{job_id}/result.glb")
async def get_result_file(job_id: str):
    path = _safe_path(job_id, "result.glb")
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Result file not found")
    return FileResponse(path, media_type="model/gltf-binary",
                        headers={"Cache-Control": "public, max-age=3600"})


@router.get("/{job_id}/result_mesh.glb")
async def get_mesh_file(job_id: str):
    path = _safe_path(job_id, "result_mesh.glb")
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Mesh file not found")
    return FileResponse(path, media_type="model/gltf-binary",
                        headers={"Cache-Control": "public, max-age=3600"})
