from __future__ import annotations

import hashlib
import io
import json
import math
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable, Mapping

import numpy as np

MESH_SOURCE_VERSION = "mesh-source-v1"
CHUNK_FRAMES = 8


class MeshSourceError(ValueError):
    pass


@dataclass
class MeshSourcePackage:
    begin: dict[str, Any]
    manifest: dict[str, Any]
    chunks: list[tuple[str, bytes]]


def _normalize_depth(value: Any, name: str) -> np.ndarray:
    array = np.asarray(value)
    if array.ndim == 4 and array.shape[-1] == 1:
        array = array[..., 0]
    if array.ndim != 3:
        raise MeshSourceError(f"{name} must have shape [N,H,W], got {array.shape}")
    return array


def _normalize_intrinsics(value: Any, frame_count: int) -> np.ndarray:
    array = np.asarray(value)
    if array.ndim == 2:
        array = np.broadcast_to(array, (frame_count, *array.shape))
    if array.shape != (frame_count, 3, 3):
        raise MeshSourceError(f"intrinsic must have shape [N,3,3], got {array.shape}")
    return array


def _normalize_c2w(value: Any, frame_count: int) -> np.ndarray:
    array = np.asarray(value)
    if array.shape == (frame_count, 3, 4):
        result = np.zeros((frame_count, 4, 4), dtype=np.float32)
        result[:, :3, :4] = array
        result[:, 3, 3] = 1
        array = result
    if array.shape != (frame_count, 4, 4):
        raise MeshSourceError(f"c2w must have shape [N,3,4] or [N,4,4], got {array.shape}")
    if not np.isfinite(array).all():
        raise MeshSourceError("c2w contains NaN/Inf")
    return array


def _estimate_scene_diagonal(
    depth: np.ndarray,
    intrinsic: np.ndarray,
    c2w: np.ndarray,
) -> float:
    samples: list[np.ndarray] = []
    frame_step = max(1, len(depth) // 32)
    for frame_index in range(0, len(depth), frame_step):
        values = np.asarray(depth[frame_index], dtype=np.float64)
        valid = np.isfinite(values) & (values > 0)
        ys, xs = np.nonzero(valid)
        if not len(xs):
            continue
        pixel_step = max(1, len(xs) // 2000)
        xs = xs[::pixel_step]
        ys = ys[::pixel_step]
        z = values[ys, xs]
        k = intrinsic[frame_index]
        camera = np.column_stack([
            (xs - k[0, 2]) * z / k[0, 0],
            (ys - k[1, 2]) * z / k[1, 1],
            z,
            np.ones_like(z),
        ])
        world = camera @ c2w[frame_index].T
        samples.append(world[:, :3])
    if not samples:
        raise MeshSourceError("cannot estimate scene scale from depth")
    points = np.concatenate(samples, axis=0)
    lower, upper = np.percentile(points, [1, 99], axis=0)
    diagonal = float(np.linalg.norm(upper - lower))
    if not np.isfinite(diagonal) or diagonal <= 0:
        raise MeshSourceError("estimated scene scale is invalid")
    return diagonal


def build_mesh_source_package(
    predictions: dict[str, Any],
    frame_indices: np.ndarray,
    alignment_matrix: np.ndarray,
    source_model: str = "lingbot-map",
    chunk_frames: int = CHUNK_FRAMES,
    source_video: Mapping[str, int | float] | None = None,
) -> MeshSourcePackage:
    depth = _normalize_depth(predictions.get("depth"), "depth")
    confidence_value = predictions.get("depth_conf")
    if confidence_value is None:
        confidence_value = predictions.get("world_points_conf")
    if confidence_value is None:
        confidence = np.ones_like(depth, dtype=np.float32)
    else:
        confidence = _normalize_depth(confidence_value, "confidence")
    if confidence.shape != depth.shape:
        raise MeshSourceError(
            f"confidence shape {confidence.shape} does not match depth {depth.shape}"
        )
    frame_count, height, width = depth.shape
    intrinsic = _normalize_intrinsics(predictions.get("intrinsic"), frame_count)
    c2w = _normalize_c2w(predictions.get("extrinsic"), frame_count)
    frame_values = np.asarray(frame_indices, dtype=np.int32).reshape(-1)
    if len(frame_values) != frame_count:
        raise MeshSourceError("frame_indices count does not match depth frames")
    alignment = np.asarray(alignment_matrix, dtype=np.float32)
    if alignment.shape != (4, 4) or not np.isfinite(alignment).all():
        raise MeshSourceError("alignment_matrix must be finite 4x4")
    if chunk_frames < 1 or chunk_frames > 32:
        raise MeshSourceError("chunk_frames must be in [1,32]")

    chunks: list[tuple[str, bytes]] = []
    entries: list[dict[str, Any]] = []
    for chunk_index, start in enumerate(range(0, frame_count, chunk_frames)):
        stop = min(start + chunk_frames, frame_count)
        buffer = io.BytesIO()
        np.savez_compressed(
            buffer,
            depth=np.nan_to_num(depth[start:stop], nan=0, posinf=0, neginf=0).astype(np.float16),
            confidence=np.nan_to_num(confidence[start:stop], nan=0, posinf=0, neginf=0).astype(np.float16),
            intrinsic=intrinsic[start:stop].astype(np.float32),
            c2w=c2w[start:stop].astype(np.float32),
            frame_indices=frame_values[start:stop],
        )
        data = buffer.getvalue()
        name = f"chunk-{chunk_index:04d}.npz"
        digest = hashlib.sha256(data).hexdigest()
        chunks.append((name, data))
        entries.append({
            "name": name,
            "sha256": digest,
            "size_bytes": len(data),
            "frame_start": int(start),
            "frame_stop": int(stop),
        })

    begin = {
        "version": MESH_SOURCE_VERSION,
        "frame_count": frame_count,
        "chunk_count": len(chunks),
        "image_height": height,
        "image_width": width,
        "coordinate_system": "lingbot-c2w-opencv",
        "color_space": "srgb",
        "alignment": "first-camera-opengl-y180",
        "source_model": source_model,
    }
    if source_video is not None:
        required_source_keys = ("source_fps", "source_frame_count", "source_height", "source_width")
        if not all(key in source_video for key in required_source_keys):
            raise MeshSourceError("source_video metadata is incomplete")
        begin.update({key: source_video[key] for key in required_source_keys})
    manifest = {
        **begin,
        "chunk_frames": chunk_frames,
        "depth_dtype": "float16",
        "confidence_dtype": "float16",
        "intrinsic_dtype": "float32",
        "c2w_dtype": "float32",
        "frame_index_dtype": "int32",
        "depth_unit": "meter",
        "pose_semantics": "camera-to-world",
        "preprocess_mode": "crop",
        "preprocess_image_size": 518,
        "preprocess_patch_size": 14,
        "alignment_matrix": alignment.tolist(),
        "scene_diagonal": _estimate_scene_diagonal(depth, intrinsic, c2w),
        "chunks": entries,
    }
    return MeshSourcePackage(begin=begin, manifest=manifest, chunks=chunks)


def upload_mesh_source_package(
    backend_url: str,
    job_id: str,
    package: MeshSourcePackage,
    headers_factory: Callable[..., dict[str, str]],
    timeout: int = 300,
) -> dict[str, Any]:
    base = backend_url.rstrip("/")

    def send(path: str, method: str, payload: bytes, content_type: str):
        request = urllib.request.Request(
            f"{base}{path}",
            data=payload,
            headers=headers_factory(**{"Content-Type": content_type}),
            method=method,
        )
        return urllib.request.urlopen(request, timeout=timeout)

    send(
        f"/api/v1/gpu/mesh-sources/{job_id}/begin",
        "POST",
        json.dumps(package.begin).encode("utf-8"),
        "application/json",
    ).read()
    for name, data in package.chunks:
        digest = hashlib.sha256(data).hexdigest()
        query = urllib.parse.urlencode({"sha256": digest, "size_bytes": len(data)})
        send(
            f"/api/v1/gpu/mesh-sources/{job_id}/chunks/{name}?{query}",
            "PUT",
            data,
            "application/octet-stream",
        ).read()
    response = send(
        f"/api/v1/gpu/mesh-sources/{job_id}/complete",
        "POST",
        json.dumps({"manifest": package.manifest}).encode("utf-8"),
        "application/json",
    )
    return json.loads(response.read())
