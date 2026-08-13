from __future__ import annotations

import os
import shutil
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models.job import Job
from app.models.mesh_run import MeshRun
from app.schemas.mesh_run import ActiveMeshRequest, MeshRunCreate
from app.services.mesh_run_service import (
    TERMINAL_MESH_STATUSES,
    create_mesh_run,
    mesh_run_to_response,
)

router = APIRouter(prefix="/api/v1")


async def _get_job(db: AsyncSession, job_id: str) -> Job:
    result = await db.execute(select(Job).where(Job.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


async def _get_run(db: AsyncSession, job_id: str, run_id: str) -> MeshRun:
    result = await db.execute(
        select(MeshRun).where(MeshRun.id == run_id, MeshRun.job_id == job_id)
    )
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="Mesh run not found")
    return run


@router.post("/jobs/{job_id}/mesh-runs", response_model=dict)
async def create_job_mesh_run(
    job_id: str,
    request: MeshRunCreate,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    job = await _get_job(db, job_id)
    try:
        run, cache_hit = await create_mesh_run(db, job, request)
        await db.commit()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except IntegrityError:
        await db.rollback()
        config = request.effective_config()
        run, cache_hit = await create_mesh_run(db, job, request)
        await db.commit()
    await db.refresh(run)
    response.status_code = 200 if cache_hit else 201
    result = mesh_run_to_response(run)
    result["cache_hit"] = cache_hit
    return result


@router.get("/jobs/{job_id}/mesh-runs", response_model=list)
async def list_job_mesh_runs(job_id: str, db: AsyncSession = Depends(get_db)):
    await _get_job(db, job_id)
    result = await db.execute(
        select(MeshRun)
        .where(MeshRun.job_id == job_id)
        .order_by(MeshRun.created_at.desc())
    )
    return [mesh_run_to_response(run) for run in result.scalars().all()]


@router.get("/jobs/{job_id}/mesh-runs/{run_id}", response_model=dict)
async def get_job_mesh_run(job_id: str, run_id: str, db: AsyncSession = Depends(get_db)):
    return mesh_run_to_response(await _get_run(db, job_id, run_id))


@router.post("/jobs/{job_id}/mesh-runs/{run_id}/cancel", response_model=dict)
async def cancel_job_mesh_run(job_id: str, run_id: str, db: AsyncSession = Depends(get_db)):
    run = await _get_run(db, job_id, run_id)
    if run.status in TERMINAL_MESH_STATUSES:
        return mesh_run_to_response(run)
    run.cancel_requested_at = datetime.utcnow()
    run.detail = "正在取消表面重建"
    if run.status == "queued":
        run.status = "cancelled"
        run.finished_at = datetime.utcnow()
        run.cache_slot = None
        run.detail = "已取消"
    await db.commit()
    await db.refresh(run)
    return mesh_run_to_response(run)


@router.delete("/jobs/{job_id}/mesh-runs/{run_id}", status_code=204)
async def delete_job_mesh_run(job_id: str, run_id: str, db: AsyncSession = Depends(get_db)):
    run = await _get_run(db, job_id, run_id)
    if run.status not in TERMINAL_MESH_STATUSES:
        raise HTTPException(status_code=409, detail="Only terminal mesh runs can be deleted")
    output_dir = os.path.join(settings.upload_dir, job_id, "mesh_runs", run_id)
    await db.delete(run)
    await db.commit()
    shutil.rmtree(output_dir, ignore_errors=True)
    return Response(status_code=204)


@router.patch("/jobs/{job_id}/active-mesh", response_model=dict)
async def select_active_mesh(
    job_id: str,
    request: ActiveMeshRequest,
    db: AsyncSession = Depends(get_db),
):
    await _get_job(db, job_id)
    result = await db.execute(
        select(MeshRun).where(MeshRun.job_id == job_id, MeshRun.active_slot == job_id)
    )
    for current in result.scalars().all():
        current.active_slot = None

    selected = None
    if request.run_id is not None:
        selected = await _get_run(db, job_id, request.run_id)
        if selected.status != "completed" or not selected.output_path:
            raise HTTPException(status_code=409, detail="Only completed mesh runs can be selected")
        selected.active_slot = job_id
    await db.commit()
    return {
        "active_mesh_run_id": selected.id if selected else None,
        "mesh_url": (
            f"/files/{job_id}/mesh-runs/{selected.id}/result.glb" if selected else None
        ),
    }
