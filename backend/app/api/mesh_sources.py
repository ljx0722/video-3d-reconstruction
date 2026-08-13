from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.api.gpu import _verify_gpu
from app.config import settings
from app.database import async_session
from app.models.job import Job
from app.services.mesh_source_service import (
    load_mesh_source_manifest,
    mesh_source_root,
    mesh_source_staging_root,
)

router = APIRouter(
    prefix="/api/v1/gpu/mesh-sources", dependencies=[Depends(_verify_gpu)]
)
CHUNK_NAME_RE = re.compile(r"^chunk-[0-9]{4}\.npz$")
MAX_STREAM_BLOCK = 1024 * 1024


class MeshSourceBegin(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str = Field(pattern=r"^mesh-source-v1$")
    frame_count: int = Field(ge=1, le=1000)
    chunk_count: int = Field(ge=1, le=1000)
    image_height: int = Field(ge=1, le=4096)
    image_width: int = Field(ge=1, le=4096)
    coordinate_system: str = Field(max_length=64)
    color_space: str = Field(max_length=32)
    alignment: str = Field(max_length=128)
    source_model: str = Field(max_length=128)
    source_fps: float | None = Field(default=None, gt=0, le=1000)
    source_frame_count: int | None = Field(default=None, ge=1, le=10_000_000)
    source_height: int | None = Field(default=None, ge=1, le=16384)
    source_width: int | None = Field(default=None, ge=1, le=16384)


class MeshSourceChunkMeta(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(ge=1)


class MeshSourceComplete(BaseModel):
    model_config = ConfigDict(extra="forbid")

    manifest: dict


def _source_root(job_id: str) -> Path:
    return mesh_source_root(job_id)


def _staging_root(job_id: str) -> Path:
    return mesh_source_staging_root(job_id)


async def _require_job(job_id: str) -> Job:
    async with async_session() as session:
        result = await session.execute(select(Job).where(Job.id == job_id))
        job = result.scalar_one_or_none()
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")
        return job


@router.post("/{job_id}/begin", response_model=dict)
async def begin_mesh_source(job_id: str, data: MeshSourceBegin):
    await _require_job(job_id)
    staging = _staging_root(job_id)
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True, exist_ok=True)
    metadata = data.model_dump()
    metadata["chunks"] = []
    (staging / "metadata.json").write_text(
        json.dumps(metadata, sort_keys=True, separators=(",", ":")), encoding="utf-8"
    )
    return {"ok": True}


@router.put("/{job_id}/chunks/{chunk_name}", response_model=dict)
async def upload_mesh_source_chunk(
    job_id: str,
    chunk_name: str,
    request: Request,
    sha256: str,
    size_bytes: int,
):
    await _require_job(job_id)
    if not CHUNK_NAME_RE.fullmatch(chunk_name):
        raise HTTPException(status_code=400, detail="Invalid mesh source chunk name")
    maximum = settings.max_mesh_source_chunk_mb * 1024 * 1024
    if size_bytes <= 0 or size_bytes > maximum:
        raise HTTPException(status_code=413, detail="Mesh source chunk exceeds size limit")
    if not re.fullmatch(r"[0-9a-f]{64}", sha256):
        raise HTTPException(status_code=400, detail="Invalid chunk checksum")
    staging = _staging_root(job_id)
    metadata_path = staging / "metadata.json"
    if not metadata_path.is_file():
        raise HTTPException(status_code=409, detail="Mesh source upload was not initialized")

    digest = hashlib.sha256()
    received = 0
    fd, temp_path = tempfile.mkstemp(prefix=f".{chunk_name}-", suffix=".tmp", dir=staging)
    try:
        with os.fdopen(fd, "wb") as target:
            async for block in request.stream():
                if not block:
                    continue
                received += len(block)
                if received > maximum or received > size_bytes:
                    raise HTTPException(status_code=413, detail="Mesh source chunk exceeds declared size")
                digest.update(block)
                target.write(block)
            target.flush()
            os.fsync(target.fileno())
        if received != size_bytes:
            raise HTTPException(status_code=400, detail="Mesh source chunk size mismatch")
        if digest.hexdigest() != sha256:
            raise HTTPException(status_code=400, detail="Mesh source chunk checksum mismatch")
        destination = staging / chunk_name
        if destination.exists():
            if destination.stat().st_size == received:
                existing_hash = hashlib.sha256(destination.read_bytes()).hexdigest()
                if existing_hash == sha256:
                    os.unlink(temp_path)
                    return {"ok": True, "idempotent": True}
            raise HTTPException(status_code=409, detail="Mesh source chunk already exists")
        os.replace(temp_path, destination)
    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)
    return {"ok": True, "sha256": sha256, "size_bytes": received}


@router.post("/{job_id}/complete", response_model=dict)
async def complete_mesh_source(job_id: str, data: MeshSourceComplete):
    await _require_job(job_id)
    staging = _staging_root(job_id)
    metadata_path = staging / "metadata.json"
    if not metadata_path.is_file():
        raise HTTPException(status_code=409, detail="Mesh source upload was not initialized")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    manifest = data.manifest
    if manifest.get("version") != "mesh-source-v1":
        raise HTTPException(status_code=400, detail="Unsupported mesh source version")
    for key in (
        "frame_count", "chunk_count", "image_height", "image_width",
        "coordinate_system", "color_space", "alignment", "source_model",
        "source_fps", "source_frame_count", "source_height", "source_width",
    ):
        if manifest.get(key) != metadata.get(key):
            raise HTTPException(status_code=400, detail=f"Manifest field mismatch: {key}")
    chunks = manifest.get("chunks")
    if not isinstance(chunks, list) or len(chunks) != metadata["chunk_count"]:
        raise HTTPException(status_code=400, detail="Manifest chunk count mismatch")

    total_size = 0
    seen_names: set[str] = set()
    for entry in chunks:
        if not isinstance(entry, dict):
            raise HTTPException(status_code=400, detail="Invalid manifest chunk")
        name = entry.get("name")
        checksum = entry.get("sha256")
        size = entry.get("size_bytes")
        if not isinstance(name, str) or not CHUNK_NAME_RE.fullmatch(name) or name in seen_names:
            raise HTTPException(status_code=400, detail="Invalid manifest chunk name")
        if not isinstance(checksum, str) or not re.fullmatch(r"[0-9a-f]{64}", checksum):
            raise HTTPException(status_code=400, detail="Invalid manifest chunk checksum")
        if not isinstance(size, int) or size <= 0:
            raise HTTPException(status_code=400, detail="Invalid manifest chunk size")
        path = staging / name
        if not path.is_file() or path.stat().st_size != size:
            raise HTTPException(status_code=409, detail=f"Missing mesh source chunk: {name}")
        if hashlib.sha256(path.read_bytes()).hexdigest() != checksum:
            raise HTTPException(status_code=409, detail=f"Mesh source chunk changed: {name}")
        total_size += size
        seen_names.add(name)
    if total_size > settings.max_mesh_source_size_mb * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Mesh source exceeds total size limit")

    manifest_bytes = json.dumps(
        manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    manifest_digest = hashlib.sha256(manifest_bytes).hexdigest()
    manifest["manifest_sha256"] = manifest_digest
    final_bytes = json.dumps(
        manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    with open(staging / "manifest.json", "wb") as target:
        target.write(final_bytes)
        target.flush()
        os.fsync(target.fileno())
    metadata_path.unlink(missing_ok=True)

    destination = _source_root(job_id)
    if destination.exists():
        current = load_mesh_source_manifest(job_id)
        if current and current.get("manifest_sha256") == manifest_digest:
            shutil.rmtree(staging, ignore_errors=True)
            return {"ok": True, "manifest_sha256": manifest_digest, "idempotent": True}
        raise HTTPException(status_code=409, detail="Immutable mesh source already exists")
    os.replace(staging, destination)
    return {
        "ok": True,
        "manifest_sha256": manifest_digest,
        "total_size_bytes": total_size,
    }
