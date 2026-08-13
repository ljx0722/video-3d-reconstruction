from __future__ import annotations

import json
from pathlib import Path

from app.config import settings


def mesh_source_root(job_id: str) -> Path:
    return Path(settings.upload_dir) / job_id / "mesh_source_v1"


def mesh_source_staging_root(job_id: str) -> Path:
    return Path(settings.upload_dir) / job_id / ".mesh_source_v1.upload"


def load_mesh_source_manifest(job_id: str) -> dict | None:
    path = mesh_source_root(job_id) / "manifest.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if data.get("version") == "mesh-source-v1" else None


def require_mesh_source_manifest(job_id: str) -> dict:
    manifest = load_mesh_source_manifest(job_id)
    if not manifest or not manifest.get("manifest_sha256"):
        raise FileNotFoundError("mesh-source-v1 sidecar is required for balanced TSDF")
    return manifest
