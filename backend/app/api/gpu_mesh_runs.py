from __future__ import annotations

import hashlib
import json
import os
import secrets
from datetime import datetime, timedelta

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Request, Response
from fastapi.responses import FileResponse
from sqlalchemy import or_, select, update

from app.api.gpu import _validate_glb, _verify_gpu, _write_atomic
from app.config import settings
from app.database import async_session
from app.models.mesh_run import MeshRun
from app.schemas.mesh_run import MeshRunClaimRequest, MeshRunStatusUpdate
from app.services.mesh_source_service import load_mesh_source_manifest, mesh_source_root
from app.services.mesh_run_service import (
    hash_lease_token,
    mark_terminal,
    mesh_run_to_response,
    output_absolute_path,
    sha256_file,
    source_absolute_path,
)

router = APIRouter(prefix="/api/v1/gpu/mesh-runs", dependencies=[Depends(_verify_gpu)])
LEASE_SECONDS = 180


def _lease_deadline(now: datetime) -> datetime:
    return now + timedelta(seconds=LEASE_SECONDS)


def _assert_current_lease(run: MeshRun, leased: MeshRun, token: str | None) -> None:
    now = datetime.utcnow()
    if (
        not token
        or run.status != "processing"
        or not run.lease_token_hash
        or not secrets.compare_digest(run.lease_token_hash, hash_lease_token(token))
        or run.lease_token_hash != leased.lease_token_hash
        or not run.lease_expires_at
        or run.lease_expires_at <= now
    ):
        raise HTTPException(status_code=409, detail="Mesh run lease is no longer valid")


async def _leased_run(run_id: str, token: str | None) -> MeshRun:
    if not token:
        raise HTTPException(status_code=401, detail="Mesh lease token is required")
    now = datetime.utcnow()
    async with async_session() as session:
        result = await session.execute(select(MeshRun).where(MeshRun.id == run_id))
        run = result.scalar_one_or_none()
        if not run:
            raise HTTPException(status_code=404, detail="Mesh run not found")
        expected_hash = run.lease_token_hash or ""
        if (
            run.status != "processing"
            or not expected_hash
            or not secrets.compare_digest(expected_hash, hash_lease_token(token))
            or not run.lease_expires_at
            or run.lease_expires_at <= now
        ):
            raise HTTPException(status_code=409, detail="Mesh run lease is no longer valid")
        session.expunge(run)
        return run


@router.post("/claim", response_model=dict | None)
async def claim_mesh_run(request: MeshRunClaimRequest, response: Response):
    now = datetime.utcnow()
    async with async_session() as session:
        expired_cancelled = await session.execute(
            select(MeshRun).where(
                MeshRun.status == "processing",
                MeshRun.cancel_requested_at.is_not(None),
                MeshRun.lease_expires_at <= now,
            )
        )
        for run in expired_cancelled.scalars().all():
            mark_terminal(run, "cancelled")
            run.detail = "已取消"
        await session.commit()

        candidates = await session.execute(
            select(MeshRun.id)
            .where(
                MeshRun.cancel_requested_at.is_(None),
                or_(
                    MeshRun.status == "queued",
                    (MeshRun.status == "processing") & (MeshRun.lease_expires_at <= now),
                ),
            )
            .order_by(MeshRun.created_at)
            .limit(8)
        )
        for run_id in candidates.scalars().all():
            token = secrets.token_urlsafe(32)
            condition = or_(
                MeshRun.status == "queued",
                (MeshRun.status == "processing") & (MeshRun.lease_expires_at <= now),
            )
            claimed = await session.execute(
                update(MeshRun)
                .where(
                    MeshRun.id == run_id,
                    MeshRun.cancel_requested_at.is_(None),
                    condition,
                )
                .values(
                    status="processing",
                    progress=0.01,
                    detail="GPU Worker 已认领，准备生成表面",
                    worker_id=request.worker_id,
                    lease_token_hash=hash_lease_token(token),
                    lease_expires_at=_lease_deadline(now),
                    heartbeat_at=now,
                    attempts=MeshRun.attempts + 1,
                    started_at=now,
                    error_message=None,
                )
            )
            if not claimed.rowcount:
                await session.rollback()
                continue
            await session.commit()
            result = await session.execute(select(MeshRun).where(MeshRun.id == run_id))
            run = result.scalar_one()
            return {
                "id": run.id,
                "job_id": run.job_id,
                "config": json.loads(run.config_json),
                "source_kind": run.source_kind,
                "source_url": f"/api/v1/gpu/mesh-runs/{run.id}/source",
                "source_sha256": run.source_sha256,
                "source_color_space": run.source_color_space,
                "lease_token": token,
                "lease_expires_at": run.lease_expires_at.isoformat(),
                "attempt": run.attempts,
            }
    response.status_code = 204
    return None


@router.post("/{run_id}/heartbeat", response_model=dict)
async def heartbeat_mesh_run(
    run_id: str,
    x_mesh_lease_token: str | None = Header(default=None),
):
    run = await _leased_run(run_id, x_mesh_lease_token)
    now = datetime.utcnow()
    async with async_session() as session:
        renewed = await session.execute(
            update(MeshRun)
            .where(
                MeshRun.id == run.id,
                MeshRun.status == "processing",
                MeshRun.lease_token_hash == run.lease_token_hash,
                MeshRun.lease_expires_at > now,
            )
            .values(heartbeat_at=now, lease_expires_at=_lease_deadline(now))
        )
        if not renewed.rowcount:
            await session.rollback()
            raise HTTPException(status_code=409, detail="Mesh run lease is no longer valid")
        await session.commit()
        result = await session.execute(select(MeshRun).where(MeshRun.id == run.id))
        current = result.scalar_one()
        return {
            "ok": True,
            "cancel_requested": current.cancel_requested_at is not None,
            "lease_expires_at": current.lease_expires_at.isoformat(),
        }


@router.get("/{run_id}/source")
async def download_mesh_source(
    run_id: str,
    x_mesh_lease_token: str | None = Header(default=None),
):
    run = await _leased_run(run_id, x_mesh_lease_token)
    if run.source_kind == "mesh-source-v1":
        manifest = load_mesh_source_manifest(run.job_id)
        if not manifest or manifest.get("manifest_sha256") != run.source_sha256:
            raise HTTPException(status_code=409, detail="Mesh source manifest changed")
        return manifest
    path = source_absolute_path(run)
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="Mesh source not found")
    if sha256_file(path) != run.source_sha256:
        raise HTTPException(status_code=409, detail="Mesh source checksum changed")
    return FileResponse(path, media_type="model/gltf-binary")


@router.get("/{run_id}/source/chunks/{chunk_name}")
async def download_mesh_source_chunk(
    run_id: str,
    chunk_name: str,
    x_mesh_lease_token: str | None = Header(default=None),
):
    run = await _leased_run(run_id, x_mesh_lease_token)
    if run.source_kind != "mesh-source-v1":
        raise HTTPException(status_code=409, detail="Mesh run does not use sidecar source")
    manifest = load_mesh_source_manifest(run.job_id)
    entry = next(
        (item for item in manifest.get("chunks", []) if item.get("name") == chunk_name),
        None,
    ) if manifest else None
    if not entry:
        raise HTTPException(status_code=404, detail="Mesh source chunk not found")
    path = mesh_source_root(run.job_id) / chunk_name
    if not path.is_file() or path.stat().st_size != entry.get("size_bytes"):
        raise HTTPException(status_code=409, detail="Mesh source chunk changed")
    if sha256_file(str(path)) != entry.get("sha256"):
        raise HTTPException(status_code=409, detail="Mesh source chunk checksum changed")
    return FileResponse(path, media_type="application/octet-stream")


@router.get("/{run_id}/cancel", response_model=dict)
async def check_mesh_cancel(
    run_id: str,
    x_mesh_lease_token: str | None = Header(default=None),
):
    run = await _leased_run(run_id, x_mesh_lease_token)
    return {"cancel_requested": run.cancel_requested_at is not None}


@router.post("/{run_id}/status", response_model=dict)
async def update_mesh_run_status(
    run_id: str,
    data: MeshRunStatusUpdate,
    x_mesh_lease_token: str | None = Header(default=None),
):
    leased = await _leased_run(run_id, x_mesh_lease_token)
    async with async_session() as session:
        result = await session.execute(select(MeshRun).where(MeshRun.id == leased.id))
        run = result.scalar_one()
        _assert_current_lease(run, leased, x_mesh_lease_token)
        if data.status == "processing" and run.cancel_requested_at is not None:
            raise HTTPException(status_code=409, detail="Mesh run cancellation was requested")
        if data.progress is not None:
            run.progress = data.progress
        if data.detail is not None:
            run.detail = data.detail
        if data.stats is not None:
            run.stats_json = json.dumps(data.stats, ensure_ascii=False)
        if data.status in {"failed", "cancelled"}:
            mark_terminal(run, data.status, data.error_message)
            run.detail = data.detail or ("已取消" if data.status == "cancelled" else "表面重建失败")
        await session.commit()
        await session.refresh(run)
        return mesh_run_to_response(run)


@router.post("/{run_id}/result", response_model=dict)
async def upload_mesh_run_result(
    run_id: str,
    request: Request,
    x_mesh_lease_token: str | None = Header(default=None),
):
    leased = await _leased_run(run_id, x_mesh_lease_token)
    data = await request.body()
    _validate_glb(data, "Mesh")
    digest = hashlib.sha256(data).hexdigest()

    async with async_session() as session:
        result = await session.execute(select(MeshRun).where(MeshRun.id == leased.id))
        run = result.scalar_one()
        _assert_current_lease(run, leased, x_mesh_lease_token)
        if run.cancel_requested_at is not None:
            raise HTTPException(status_code=409, detail="Mesh run cancellation was requested")
        path = output_absolute_path(run)
        if os.path.exists(path):
            if sha256_file(path) != digest:
                raise HTTPException(status_code=409, detail="Immutable mesh output already exists")
        else:
            _write_atomic(path, data)

        previous = await session.execute(
            select(MeshRun).where(
                MeshRun.job_id == run.job_id,
                MeshRun.active_slot == run.job_id,
                MeshRun.id != run.id,
            )
        )
        for old_active in previous.scalars().all():
            old_active.active_slot = None

        run.output_path = os.path.relpath(path, settings.upload_dir)
        run.output_sha256 = digest
        run.output_size_bytes = len(data)
        run.status = "completed"
        run.progress = 1.0
        run.detail = "表面重建完成"
        run.error_message = None
        run.finished_at = datetime.utcnow()
        run.active_slot = run.job_id
        run.lease_expires_at = None
        run.lease_token_hash = None
        run.worker_id = None
        await session.commit()
        await session.refresh(run)
        return mesh_run_to_response(run)
