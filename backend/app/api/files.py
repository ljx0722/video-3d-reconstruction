import os
import uuid

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.mesh_run import MeshRun
from app.services import storage_service

router = APIRouter(prefix="/files")


def _safe_path(job_id: str, filename: str) -> str:
    try:
        uuid.UUID(job_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid job ID") from None
    p = os.path.realpath(os.path.join(storage_service.settings.upload_dir, job_id, filename))
    base = os.path.realpath(storage_service.settings.upload_dir)
    if os.path.commonpath([base, p]) != base:
        raise HTTPException(status_code=400, detail="Invalid path")
    return p


@router.head("/{job_id}/result.glb", include_in_schema=False)
@router.get("/{job_id}/result.glb")
async def get_result_file(job_id: str):
    path = _safe_path(job_id, "result.glb")
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Result file not found")
    return FileResponse(path, media_type="model/gltf-binary",
                        headers={"Cache-Control": "public, max-age=3600"})


@router.head("/{job_id}/mesh-runs/{run_id}/result.glb", include_in_schema=False)
@router.get("/{job_id}/mesh-runs/{run_id}/result.glb")
async def get_mesh_run_file(
    job_id: str,
    run_id: str,
    db: AsyncSession = Depends(get_db),
):
    try:
        uuid.UUID(job_id)
        uuid.UUID(run_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid ID") from None
    result = await db.execute(
        select(MeshRun).where(
            MeshRun.id == run_id,
            MeshRun.job_id == job_id,
            MeshRun.status == "completed",
        )
    )
    run = result.scalar_one_or_none()
    if not run or not run.output_path:
        raise HTTPException(status_code=404, detail="Mesh run file not found")
    path = _safe_path(job_id, os.path.join("mesh_runs", run_id, "result.glb"))
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="Mesh run file not found")
    headers = {"Cache-Control": "public, max-age=31536000, immutable"}
    if run.output_sha256:
        headers["ETag"] = f'"{run.output_sha256}"'
    return FileResponse(path, media_type="model/gltf-binary", headers=headers)


@router.head("/{job_id}/result_mesh.glb", include_in_schema=False)
@router.get("/{job_id}/result_mesh.glb")
async def get_mesh_file(job_id: str):
    path = _safe_path(job_id, "result_mesh.glb")
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Mesh file not found")
    return FileResponse(path, media_type="model/gltf-binary",
                        headers={"Cache-Control": "public, max-age=3600"})
