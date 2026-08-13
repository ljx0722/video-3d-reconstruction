from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.job import Job
from app.models.mesh_run import MeshRun
from app.schemas.mesh_run import MeshRunCreate, MeshRunConfig
from app.services.mesh_source_service import mesh_source_root, require_mesh_source_manifest

MESH_BUILDER_VERSION = "mesh-builder-v3"
TERMINAL_MESH_STATUSES = {"completed", "failed", "cancelled"}
MAX_PENDING_MESH_RUNS = 3
MAX_MESH_RUNS_PER_JOB = 12


def canonical_config(config: MeshRunConfig) -> str:
    return json.dumps(config.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))


def sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def hash_lease_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def source_absolute_path(run: MeshRun) -> str:
    path = os.path.realpath(os.path.join(settings.upload_dir, run.source_path))
    base = os.path.realpath(settings.upload_dir)
    if os.path.commonpath([base, path]) != base:
        raise ValueError("Mesh source path escapes upload directory")
    return path


def output_absolute_path(run: MeshRun) -> str:
    relative = run.output_path or os.path.join(run.job_id, "mesh_runs", run.id, "result.glb")
    path = os.path.realpath(os.path.join(settings.upload_dir, relative))
    base = os.path.realpath(settings.upload_dir)
    if os.path.commonpath([base, path]) != base:
        raise ValueError("Mesh output path escapes upload directory")
    return path


def mesh_run_to_response(run: MeshRun) -> dict:
    try:
        config = json.loads(run.config_json)
    except (json.JSONDecodeError, TypeError):
        config = {}
    try:
        stats = json.loads(run.stats_json) if run.stats_json else None
    except (json.JSONDecodeError, TypeError):
        stats = None
    output_url = None
    if run.status == "completed" and run.output_path:
        output_url = f"/files/{run.job_id}/mesh-runs/{run.id}/result.glb"
    return {
        "id": run.id,
        "job_id": run.job_id,
        "preset": run.preset,
        "algorithm": run.algorithm,
        "status": run.status,
        "progress": run.progress,
        "config": config,
        "cache_key": run.cache_key,
        "source_kind": run.source_kind,
        "source_color_space": run.source_color_space,
        "detail": run.detail or "",
        "stats": stats,
        "error_message": run.error_message,
        "output_url": output_url,
        "output_sha256": run.output_sha256,
        "output_size_bytes": run.output_size_bytes,
        "is_active": run.active_slot == run.job_id,
        "cancel_requested": run.cancel_requested_at is not None,
        "attempts": run.attempts,
        "created_at": run.created_at.isoformat() if run.created_at else None,
        "updated_at": run.updated_at.isoformat() if run.updated_at else None,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
    }


async def create_mesh_run(
    session: AsyncSession,
    job: Job,
    request: MeshRunCreate,
    source_color_space: str | None = None,
) -> tuple[MeshRun, bool]:
    config = request.effective_config()
    config_json = canonical_config(config)
    config_hash = hashlib.sha256(config_json.encode("utf-8")).hexdigest()

    try:
        job_settings = json.loads(job.settings or "{}")
    except (json.JSONDecodeError, TypeError):
        job_settings = {}
    metadata = job_settings.get("_artifact_metadata") if isinstance(job_settings, dict) else None
    metadata_color_space = metadata.get("color_space") if isinstance(metadata, dict) else None
    color_space = source_color_space or metadata_color_space
    if color_space not in {"linear-srgb", "srgb"}:
        color_space = "srgb"

    if config.algorithm == "tsdf":
        manifest = require_mesh_source_manifest(job.id)
        source_kind = "mesh-source-v1"
        source_relative_path = os.path.relpath(mesh_source_root(job.id), settings.upload_dir)
        source_hash = manifest["manifest_sha256"]
        color_space = manifest.get("color_space", color_space)
        if config.use_sam2:
            source_fps = manifest.get("source_fps")
            source_frame_count = manifest.get("source_frame_count")
            if not isinstance(source_fps, (int, float)) or source_fps <= 0:
                raise FileNotFoundError("mesh-source-v1 lacks source video FPS required by SAM2")
            if not isinstance(source_frame_count, int) or source_frame_count < 1:
                raise FileNotFoundError("mesh-source-v1 lacks source frame count required by SAM2")
            for prompt in config.sam2_prompts:
                if prompt.frame_index >= source_frame_count:
                    raise ValueError(
                        f"SAM2 prompt frame {prompt.frame_index} exceeds source video frame count"
                    )
                if prompt.kind == "point":
                    coordinates = (prompt.x, prompt.y)
                else:
                    coordinates = (prompt.x0, prompt.y0, prompt.x1, prompt.y1)
                source_width = manifest.get("source_width")
                source_height = manifest.get("source_height")
                if not isinstance(source_width, int) or not isinstance(source_height, int):
                    raise FileNotFoundError("mesh-source-v1 lacks source video dimensions required by SAM2")
                xs = coordinates[0::2]
                ys = coordinates[1::2]
                if any(value >= source_width for value in xs) or any(value >= source_height for value in ys):
                    raise ValueError("SAM2 prompt coordinates exceed source video dimensions")
    else:
        source_kind = "legacy-point-glb"
        source_relative_path = os.path.join(job.id, "result.glb")
        source_path = os.path.join(settings.upload_dir, source_relative_path)
        if not os.path.isfile(source_path):
            raise FileNotFoundError("Point cloud artifact not found")
        source_hash = sha256_file(source_path)

    cache_material = "\0".join(
        (job.id, source_hash, color_space, MESH_BUILDER_VERSION, config_json)
    )
    cache_key = hashlib.sha256(cache_material.encode("utf-8")).hexdigest()

    result = await session.execute(
        select(MeshRun).where(MeshRun.cache_slot == cache_key)
    )
    existing = result.scalar_one_or_none()
    if existing:
        return existing, True

    pending_count = await session.scalar(
        select(func.count())
        .select_from(MeshRun)
        .where(MeshRun.job_id == job.id, MeshRun.status.in_(["queued", "processing"]))
    )
    if pending_count >= MAX_PENDING_MESH_RUNS:
        raise ValueError("每个作业最多同时排队 3 个表面重建任务，请等待完成或先取消")

    total_count = await session.scalar(
        select(func.count()).select_from(MeshRun).where(MeshRun.job_id == job.id)
    )
    if total_count >= MAX_MESH_RUNS_PER_JOB:
        raise ValueError("每个作业最多保留 12 个表面版本，请先删除旧版本")

    run = MeshRun(
        job_id=job.id,
        preset=request.preset,
        algorithm=config.algorithm,
        config_json=config_json,
        config_hash=config_hash,
        cache_key=cache_key,
        cache_slot=cache_key,
        source_kind=source_kind,
        source_path=source_relative_path,
        source_sha256=source_hash,
        source_color_space=color_space,
        status="queued",
        progress=0,
        detail="等待 GPU Worker 生成表面",
    )
    session.add(run)
    await session.flush()
    return run, False


def mark_terminal(run: MeshRun, status: str, error_message: str | None = None) -> None:
    now = datetime.utcnow()
    run.status = status
    run.finished_at = now
    run.lease_expires_at = None
    run.lease_token_hash = None
    run.worker_id = None
    if status != "completed":
        run.cache_slot = None
    if error_message is not None:
        run.error_message = error_message
