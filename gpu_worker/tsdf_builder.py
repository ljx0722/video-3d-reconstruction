from __future__ import annotations

import io
import json
import logging
import tempfile
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Mapping

import numpy as np

logger = logging.getLogger("gpu-worker.tsdf")


@dataclass
class TsdfBuildResult:
    data: bytes | None = None
    error: str | None = None
    stats: dict[str, int | float | str] = field(default_factory=dict)

    @property
    def success(self) -> bool:
        return self.data is not None and self.error is None


class TsdfInputError(ValueError):
    pass


def c2w_to_w2c(c2w: np.ndarray) -> np.ndarray:
    matrix = np.asarray(c2w, dtype=np.float64)
    if matrix.shape != (4, 4) or not np.isfinite(matrix).all():
        raise TsdfInputError("C2W must be a finite 4x4 matrix")
    try:
        inverse = np.linalg.inv(matrix)
    except np.linalg.LinAlgError as exc:
        raise TsdfInputError("C2W is singular") from exc
    if not np.allclose(matrix @ inverse, np.eye(4), atol=1e-5):
        raise TsdfInputError("C2W inversion failed")
    return inverse


def filter_depth_confidence(
    depth: np.ndarray,
    confidence: np.ndarray,
    percentile: float,
    depth_min: float,
    depth_max: float,
    keep_mask: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray, float]:
    depth_values = np.asarray(depth, dtype=np.float32)
    confidence_values = np.asarray(confidence, dtype=np.float32)
    if depth_values.shape != confidence_values.shape or depth_values.ndim != 2:
        raise TsdfInputError("Depth and confidence must be matching 2D arrays")
    mask = None
    if keep_mask is not None:
        mask = np.asarray(keep_mask, dtype=bool)
        if mask.shape != depth_values.shape:
            raise TsdfInputError("Keep mask shape does not match depth")
    confidence_region = confidence_values if mask is None else confidence_values[mask]
    valid_confidence = confidence_region[np.isfinite(confidence_region)]
    cutoff = float(np.percentile(valid_confidence, percentile)) if valid_confidence.size else 0.0
    valid = (
        np.isfinite(depth_values)
        & np.isfinite(confidence_values)
        & (depth_values >= depth_min)
        & (depth_values <= depth_max)
        & (confidence_values >= cutoff)
    )
    if mask is not None:
        valid &= mask
    filtered = np.where(valid, depth_values, 0.0).astype(np.float32)
    return filtered, valid, cutoff


def unpack_sidecar_chunk(data: bytes, expected_frames: int | None = None) -> dict[str, np.ndarray]:
    try:
        with np.load(io.BytesIO(data), allow_pickle=False) as loaded:
            result = {name: loaded[name].copy() for name in loaded.files}
    except Exception as exc:
        raise TsdfInputError(f"Invalid mesh source NPZ: {exc}") from exc
    required = {"depth", "confidence", "intrinsic", "c2w", "frame_indices"}
    missing = required - result.keys()
    if missing:
        raise TsdfInputError(f"Mesh source chunk missing arrays: {sorted(missing)}")
    depth = np.asarray(result["depth"])
    frame_count = depth.shape[0] if depth.ndim == 3 else -1
    if frame_count < 1 or (expected_frames is not None and frame_count != expected_frames):
        raise TsdfInputError("Mesh source chunk frame count mismatch")
    if np.asarray(result["confidence"]).shape != depth.shape:
        raise TsdfInputError("Mesh source confidence shape mismatch")
    if np.asarray(result["intrinsic"]).shape != (frame_count, 3, 3):
        raise TsdfInputError("Mesh source intrinsic shape mismatch")
    if np.asarray(result["c2w"]).shape != (frame_count, 4, 4):
        raise TsdfInputError("Mesh source C2W shape mismatch")
    if np.asarray(result["frame_indices"]).shape != (frame_count,):
        raise TsdfInputError("Mesh source frame index shape mismatch")
    return result


def estimate_scene_diagonal(chunks: Iterable[dict[str, np.ndarray]]) -> float:
    points: list[np.ndarray] = []
    for chunk in chunks:
        depth = np.asarray(chunk["depth"], dtype=np.float64)
        intrinsic = np.asarray(chunk["intrinsic"], dtype=np.float64)
        c2w = np.asarray(chunk["c2w"], dtype=np.float64)
        for index in range(len(depth)):
            values = depth[index]
            valid = np.isfinite(values) & (values > 0)
            ys, xs = np.nonzero(valid)
            if not len(xs):
                continue
            stride = max(1, len(xs) // 2000)
            xs = xs[::stride]
            ys = ys[::stride]
            z = values[ys, xs]
            k = intrinsic[index]
            camera = np.column_stack([
                (xs - k[0, 2]) * z / k[0, 0],
                (ys - k[1, 2]) * z / k[1, 1],
                z,
                np.ones_like(z),
            ])
            world = camera @ c2w[index].T
            points.append(world[:, :3])
    if not points:
        raise TsdfInputError("Cannot estimate scene scale from depth")
    values = np.concatenate(points, axis=0)
    lower, upper = np.percentile(values, [1, 99], axis=0)
    diagonal = float(np.linalg.norm(upper - lower))
    if not np.isfinite(diagonal) or diagonal <= 0:
        raise TsdfInputError("Estimated scene scale is invalid")
    return diagonal


def build_tsdf_mesh(
    manifest: Mapping[str, Any],
    chunk_loader: Callable[[dict[str, Any]], bytes],
    color_loader: Callable[[np.ndarray, int, int], np.ndarray],
    config: Mapping[str, Any],
    progress_callback: Callable[[float, str], None] | None = None,
    cancel_check: Callable[[], bool] | None = None,
    mask_loader: Callable[[np.ndarray, int, int], np.ndarray] | None = None,
) -> TsdfBuildResult:
    stats: dict[str, int | float | str] = {"algorithm": "tsdf"}
    try:
        if manifest.get("version") != "mesh-source-v1":
            raise TsdfInputError("Unsupported mesh source version")
        entries = manifest.get("chunks")
        if not isinstance(entries, list) or not entries:
            raise TsdfInputError("Mesh source manifest has no chunks")
        diagonal = float(manifest.get("scene_diagonal", 0))
        if not np.isfinite(diagonal) or diagonal <= 0:
            raise TsdfInputError("Mesh source manifest has invalid scene_diagonal")
        voxel_size = max(diagonal * float(config.get("tsdf_voxel_size_ratio", 0.0025)), 1e-6)
        truncation_multiplier = float(config.get("tsdf_truncation_multiplier", 4.0))
        truncation = voxel_size * truncation_multiplier
        stats.update({
            "scene_diagonal": diagonal,
            "voxel_size": voxel_size,
            "sdf_truncation": truncation,
            "trunc_voxel_multiplier": truncation_multiplier,
        })

        try:
            import open3d as o3d
        except ImportError as exc:
            raise RuntimeError("GPU Worker 未安装 open3d，无法生成 TSDF Mesh") from exc

        device = o3d.core.Device("CUDA:0") if o3d.core.cuda.is_available() else o3d.core.Device("CPU:0")
        stats["device"] = str(device)
        vbg = o3d.t.geometry.VoxelBlockGrid(
            attr_names=("tsdf", "weight", "color"),
            attr_dtypes=(o3d.core.float32, o3d.core.float32, o3d.core.float32),
            attr_channels=((1,), (1,), (3,)),
            voxel_size=voxel_size,
            block_resolution=16,
            block_count=int(config.get("tsdf_block_count", 20_000)),
            device=device,
        )

        percentile = float(config.get("confidence_percentile", 10))
        depth_min = float(config.get("depth_min", 0.05))
        depth_max = float(config.get("depth_max", 100))
        frame_stride = int(config.get("frame_stride", 1))
        valid_frames = 0
        valid_pixels = 0
        total_pixels = 0
        frame_offset = 0
        for entry in entries:
            chunk = unpack_sidecar_chunk(
                chunk_loader(entry),
                int(entry["frame_stop"]) - int(entry["frame_start"]),
            )
            depth_values = np.asarray(chunk["depth"], dtype=np.float32)
            confidence_values = np.asarray(chunk["confidence"], dtype=np.float32)
            frame_indices = np.asarray(chunk["frame_indices"], dtype=np.int32)
            colors = color_loader(frame_indices, manifest["image_height"], manifest["image_width"])
            masks = mask_loader(frame_indices, manifest["image_height"], manifest["image_width"]) if mask_loader else None
            masked_pixels = 0
            for local_index in range(len(depth_values)):
                if int(frame_indices[local_index]) % frame_stride:
                    continue
                if cancel_check and cancel_check():
                    raise RuntimeError("TSDF reconstruction cancelled")
                pre_mask_valid = (
                    np.isfinite(depth_values[local_index])
                    & np.isfinite(confidence_values[local_index])
                    & (depth_values[local_index] >= depth_min)
                    & (depth_values[local_index] <= depth_max)
                )
                mask = np.asarray(masks[local_index], dtype=bool) if masks is not None else None
                if mask is not None and mask.shape != depth_values[local_index].shape:
                    raise TsdfInputError(f"Mask shape {mask.shape} does not match depth {depth_values[local_index].shape}")
                depth, valid, cutoff = filter_depth_confidence(
                    depth_values[local_index], confidence_values[local_index], percentile, depth_min, depth_max, mask
                )
                if mask is not None:
                    masked_pixels += int(np.count_nonzero(pre_mask_valid & ~mask))
                total_pixels += valid.size
                valid_pixels += int(np.count_nonzero(valid))
                if not np.any(valid):
                    continue
                color = np.asarray(colors[local_index])
                if color.shape != (*depth.shape, 3):
                    raise TsdfInputError(f"Color shape {color.shape} does not match depth {depth.shape}")
                color = np.clip(color, 0, 1).astype(np.float32)
                depth = np.ascontiguousarray(depth)
                depth_image = o3d.t.geometry.Image(o3d.core.Tensor(depth, device=device))
                color_image = o3d.t.geometry.Image(o3d.core.Tensor(color, device=device))
                camera_device = o3d.core.Device("CPU:0")
                intrinsic = o3d.core.Tensor(
                    np.asarray(chunk["intrinsic"][local_index], dtype=np.float64),
                    device=camera_device,
                )
                extrinsic = o3d.core.Tensor(
                    c2w_to_w2c(chunk["c2w"][local_index]),
                    device=camera_device,
                )
                frustum = vbg.compute_unique_block_coordinates(
                    depth_image, intrinsic, extrinsic, 1.0, depth_max, truncation_multiplier
                )
                vbg.integrate(
                    frustum, depth_image, color_image, intrinsic, intrinsic,
                    extrinsic, 1.0, depth_max, truncation_multiplier,
                )
                valid_frames += 1
                stats["last_confidence_cutoff"] = cutoff
                if progress_callback:
                    progress_callback(0.1 + 0.75 * (frame_offset + local_index + 1) / manifest["frame_count"], "正在融合 RGB-D 帧")
            frame_offset += len(depth_values)

        if valid_frames == 0:
            raise TsdfInputError("No valid RGB-D frames remained after filtering")
        mesh = vbg.extract_triangle_mesh(weight_threshold=float(config.get("min_tsdf_weight", 1.0)))
        mesh = mesh.cpu()
        vertices = mesh.vertex.positions.numpy()
        triangles = mesh.triangle.indices.numpy()
        if len(vertices) < 3 or len(triangles) < 1:
            raise RuntimeError("TSDF did not produce a mesh")
        alignment = np.asarray(manifest.get("alignment_matrix"), dtype=np.float64)
        homogeneous = np.concatenate([vertices, np.ones((len(vertices), 1))], axis=1)
        vertices = (homogeneous @ alignment.T)[:, :3]

        import trimesh
        vertex_colors = None
        if "colors" in mesh.vertex:
            rgb = np.clip(mesh.vertex.colors.numpy(), 0, 1)
            vertex_colors = np.concatenate([rgb * 255, np.full((len(rgb), 1), 255)], axis=1).astype(np.uint8)
        exported = trimesh.Trimesh(
            vertices=vertices,
            faces=triangles,
            vertex_colors=vertex_colors,
            process=False,
        )
        target = int(config.get("target_triangles", 300_000))
        if len(exported.faces) > target:
            exported = exported.simplify_quadric_decimation(face_count=target)
        data = trimesh.Scene(exported).export(file_type="glb")
        if not isinstance(data, bytes) or data[:4] != b"glTF":
            raise RuntimeError("Failed to export TSDF mesh GLB")
        stats.update({
            "valid_frames": valid_frames,
            "valid_pixel_ratio": valid_pixels / max(total_pixels, 1),
            "mesh_vertices": len(exported.vertices),
            "mesh_triangles": len(exported.faces),
            "glb_bytes": len(data),
        })
        if masks is not None:
            stats["mask_filtered_pixels"] = masked_pixels
            stats["mask_pixel_ratio"] = masked_pixels / max(total_pixels, 1)

        try:
            from mesh_quality import compute_mesh_quality
        except ImportError:
            from gpu_worker.mesh_quality import compute_mesh_quality
        quality = compute_mesh_quality(
            exported,
            scene_diagonal=float(diagonal),
            voxel_size=float(voxel_size),
        )
        stats.update(quality)

        return TsdfBuildResult(data=data, stats=stats)
    except Exception as exc:
        logger.exception("TSDF reconstruction failed")
        return TsdfBuildResult(error=str(exc), stats=stats)
