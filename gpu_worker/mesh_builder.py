from __future__ import annotations

import argparse
import io
import logging
import tempfile
from dataclasses import dataclass, field
from typing import Any

import numpy as np

logger = logging.getLogger("gpu-worker.mesh")

_MIN_CANDIDATE_VERTICES = 250
_MIN_CANDIDATE_TRIANGLES = 500
_MAX_FINAL_TRIANGLES = 150_000
_MIN_CANDIDATE_SCALE_RATIO = 0.25
_MAX_CANDIDATE_SCALE_RATIO = 5.0


@dataclass
class MeshBuildResult:
    data: bytes | None = None
    error: str | None = None
    stats: dict[str, int | float | str] = field(default_factory=dict)

    @property
    def success(self) -> bool:
        return self.data is not None and self.error is None


class MeshInputError(ValueError):
    pass


class MeshCandidateError(ValueError):
    pass


def _srgb_to_linear(colors: np.ndarray) -> np.ndarray:
    """Convert normalized sRGB values to the linear colors expected by glTF."""
    srgb = np.clip(np.asarray(colors, dtype=np.float64), 0.0, 1.0)
    return np.where(
        srgb <= 0.04045,
        srgb / 12.92,
        np.power((srgb + 0.055) / 1.055, 2.4),
    )


def _apply_alignment(points: np.ndarray, alignment_matrix: Any | None) -> tuple[np.ndarray, bool]:
    if alignment_matrix is None:
        return points, False

    matrix = np.asarray(alignment_matrix, dtype=np.float64)
    if matrix.ndim == 3 and matrix.shape[0] == 1:
        matrix = matrix[0]
    if matrix.shape not in {(3, 3), (3, 4), (4, 4)}:
        raise MeshInputError(f"alignment_matrix 形状无效: {matrix.shape}")
    if not np.isfinite(matrix).all():
        raise MeshInputError("alignment_matrix 包含 NaN/Inf")

    if matrix.shape == (3, 3):
        aligned = points @ matrix.T
    elif matrix.shape == (3, 4):
        aligned = points @ matrix[:, :3].T + matrix[:, 3]
    elif np.allclose(matrix[3], [0.0, 0.0, 0.0, 1.0]):
        aligned = points @ matrix[:3, :3].T + matrix[:3, 3]
    else:
        aligned = np.empty_like(points, dtype=np.float64)
        chunk_size = 250_000
        for start in range(0, len(points), chunk_size):
            stop = min(start + chunk_size, len(points))
            chunk = points[start:stop]
            homogeneous = np.concatenate([chunk, np.ones((len(chunk), 1))], axis=1)
            transformed = homogeneous @ matrix.T
            w = transformed[:, 3]
            valid_w = np.isfinite(w) & (np.abs(w) > np.finfo(np.float64).eps)
            aligned_chunk = aligned[start:stop]
            aligned_chunk[:] = np.nan
            aligned_chunk[valid_w] = transformed[valid_w, :3] / w[valid_w, None]
    return aligned, True


def _robust_point_bounds(points: np.ndarray) -> tuple[np.ndarray, np.ndarray, float]:
    """Return 1st/99th percentile bounds and their diagonal length."""
    values = np.asarray(points, dtype=np.float64)
    if values.ndim != 2 or values.shape[1] != 3 or len(values) == 0:
        raise MeshInputError(f"无法计算点云鲁棒包围盒: shape={values.shape}")
    finite_values = values[np.isfinite(values).all(axis=1)]
    if len(finite_values) == 0:
        raise MeshInputError("无法计算点云鲁棒包围盒: 没有有限点")

    lower, upper = np.percentile(finite_values, [1.0, 99.0], axis=0)
    diagonal = float(np.linalg.norm(upper - lower))
    if not np.isfinite(diagonal) or diagonal <= np.finfo(np.float64).eps:
        raise MeshInputError(f"点云鲁棒包围盒无效: diagonal={diagonal}")
    return lower, upper, diagonal


def _validate_mesh_candidate(
    vertices: np.ndarray,
    faces: np.ndarray,
    reference_diag: float,
) -> dict[str, int | float]:
    """Validate geometry without requiring Open3D so it can be unit-tested."""
    vertex_values = np.asarray(vertices)
    face_values = np.asarray(faces)
    if vertex_values.ndim != 2 or vertex_values.shape[1] != 3:
        raise MeshCandidateError(f"候选 Mesh 顶点形状无效: {vertex_values.shape}")
    if face_values.ndim != 2 or face_values.shape[1] != 3:
        raise MeshCandidateError(f"候选 Mesh 三角面形状无效: {face_values.shape}")
    if len(vertex_values) < _MIN_CANDIDATE_VERTICES:
        raise MeshCandidateError(
            f"候选 Mesh 顶点不足: {len(vertex_values)} < {_MIN_CANDIDATE_VERTICES}"
        )
    if len(face_values) < _MIN_CANDIDATE_TRIANGLES:
        raise MeshCandidateError(
            f"候选 Mesh 三角面不足: {len(face_values)} < {_MIN_CANDIDATE_TRIANGLES}"
        )

    try:
        vertices_are_finite = bool(np.isfinite(vertex_values).all())
        faces_are_finite = bool(np.isfinite(face_values).all())
    except TypeError as exc:
        raise MeshCandidateError("候选 Mesh 顶点或三角面不是数值") from exc
    if not vertices_are_finite:
        raise MeshCandidateError("候选 Mesh 顶点包含 NaN/Inf")
    if not faces_are_finite:
        raise MeshCandidateError("候选 Mesh 三角面包含 NaN/Inf")

    if not np.issubdtype(face_values.dtype, np.integer):
        if not np.equal(face_values, np.floor(face_values)).all():
            raise MeshCandidateError("候选 Mesh 三角面索引不是整数")
    face_indices = face_values.astype(np.int64, copy=False)
    if np.any(face_indices < 0) or np.any(face_indices >= len(vertex_values)):
        raise MeshCandidateError("候选 Mesh 三角面索引越界")

    vertices_float = vertex_values.astype(np.float64, copy=False)
    candidate_diag = float(
        np.linalg.norm(np.max(vertices_float, axis=0) - np.min(vertices_float, axis=0))
    )
    if not np.isfinite(candidate_diag) or candidate_diag <= np.finfo(np.float64).eps:
        raise MeshCandidateError(f"候选 Mesh 包围盒无效: diagonal={candidate_diag}")
    if not np.isfinite(reference_diag) or reference_diag <= np.finfo(np.float64).eps:
        raise MeshCandidateError(f"参考点云尺度无效: diagonal={reference_diag}")
    scale_ratio = candidate_diag / float(reference_diag)
    if not (_MIN_CANDIDATE_SCALE_RATIO <= scale_ratio <= _MAX_CANDIDATE_SCALE_RATIO):
        raise MeshCandidateError(
            "候选 Mesh 包围盒尺度不合理: "
            f"ratio={scale_ratio:.6g}, expected="
            f"[{_MIN_CANDIDATE_SCALE_RATIO}, {_MAX_CANDIDATE_SCALE_RATIO}]"
        )

    triangles = vertices_float[face_indices]
    cross_products = np.cross(triangles[:, 1] - triangles[:, 0], triangles[:, 2] - triangles[:, 0])
    triangle_areas = 0.5 * np.linalg.norm(cross_products, axis=1)
    total_area = float(np.sum(triangle_areas, dtype=np.float64))
    minimum_area = max(np.finfo(np.float64).eps, float(reference_diag) ** 2 * 1e-12)
    if not np.isfinite(total_area) or total_area <= minimum_area:
        raise MeshCandidateError(f"候选 Mesh 面积无效: area={total_area}")

    return {
        "vertices": len(vertex_values),
        "triangles": len(face_indices),
        "bbox_diagonal": candidate_diag,
        "bbox_scale_ratio": scale_ratio,
        "surface_area": total_area,
    }


def _prepare_inputs(
    vis_pred: dict[str, Any], conf_pct: float
) -> tuple[np.ndarray, np.ndarray, dict[str, int | float | str]]:
    xyz = vis_pred.get("world_points_from_depth")
    confidence_key = "depth_conf"
    if xyz is None:
        xyz = vis_pred.get("world_points")
        confidence_key = "world_points_conf"
    if xyz is None:
        raise MeshInputError("模型输出缺少 world_points_from_depth/world_points")

    xyz = np.asarray(xyz)
    if xyz.ndim < 2 or xyz.shape[-1] != 3:
        raise MeshInputError(f"点坐标形状无效: {xyz.shape}")

    xyz_flat = xyz.reshape(-1, 3).astype(np.float64, copy=False)
    xyz_flat, alignment_applied = _apply_alignment(
        xyz_flat, vis_pred.get("alignment_matrix")
    )
    input_points = len(xyz_flat)
    mask = np.isfinite(xyz_flat).all(axis=1)

    depth_conf = vis_pred.get(confidence_key)
    cutoff = 0.0
    if depth_conf is not None:
        conf_flat = np.asarray(depth_conf).reshape(-1).astype(np.float64, copy=False)
        if len(conf_flat) != input_points:
            raise MeshInputError(
                f"置信度与点坐标数量不一致: confidence={len(conf_flat)}, points={input_points}"
            )
        finite_conf = np.isfinite(conf_flat)
        valid_conf = conf_flat[finite_conf]
        if valid_conf.size == 0:
            raise MeshInputError("置信度全部为 NaN/Inf")
        percentile = float(np.clip(conf_pct, 0.0, 100.0))
        cutoff = float(np.percentile(valid_conf, percentile)) if percentile > 0 else 0.0
        mask &= finite_conf & (conf_flat >= cutoff) & (conf_flat > 1e-5)

    images = vis_pred.get("images")
    if images is None:
        colors_flat = np.full((input_points, 3), 0.6, dtype=np.float64)
    else:
        colors = np.asarray(images)
        if colors.ndim == 4 and colors.shape[1] == 3:
            colors = np.transpose(colors, (0, 2, 3, 1))
        if colors.ndim < 2 or colors.shape[-1] != 3:
            raise MeshInputError(f"图像颜色形状无效: {colors.shape}")
        colors_flat = colors.reshape(-1, 3).astype(np.float64, copy=False)
        if len(colors_flat) != input_points:
            raise MeshInputError(
                f"颜色与点坐标数量不一致: colors={len(colors_flat)}, points={input_points}"
            )
        colors_flat = np.nan_to_num(colors_flat, nan=0.6, posinf=1.0, neginf=0.0)
        if colors_flat.size and float(np.max(colors_flat)) > 1.0:
            colors_flat = colors_flat / 255.0

    points = xyz_flat[mask]
    colors = _srgb_to_linear(colors_flat[mask])
    if len(points) >= 1000:
        robust_min, robust_max, robust_diag = _robust_point_bounds(points)
        padding = np.maximum((robust_max - robust_min) * 0.1, robust_diag * 1e-4)
        robust_mask = np.all(
            (points >= robust_min - padding) & (points <= robust_max + padding), axis=1
        )
        if int(np.count_nonzero(robust_mask)) >= max(1000, int(len(points) * 0.9)):
            points = points[robust_mask]
            colors = colors[robust_mask]
    stats: dict[str, int | float | str] = {
        "input_points": input_points,
        "filtered_points": len(points),
        "extreme_outliers_removed": int(np.count_nonzero(mask)) - len(points),
        "confidence_percentile": float(np.clip(conf_pct, 0.0, 100.0)),
        "confidence_cutoff": cutoff,
        "alignment_applied": int(alignment_applied),
        "color_space": "linear-srgb",
    }
    return points, colors, stats


def _ball_pivoting(o3d: Any, pcd: Any, stats: dict[str, int | float | str]) -> Any:
    distances = np.asarray(pcd.compute_nearest_neighbor_distance(), dtype=np.float64)
    distances = distances[np.isfinite(distances) & (distances > 0)]
    if distances.size == 0:
        raise RuntimeError("无法估算 Ball Pivoting 半径")
    base_radius = float(np.median(distances))
    radii = [base_radius * 1.5, base_radius * 3.0, base_radius * 6.0]
    stats["ball_pivot_base_radius"] = base_radius
    return o3d.geometry.TriangleMesh.create_from_point_cloud_ball_pivoting(
        pcd, o3d.utility.DoubleVector(radii)
    )


def _clean_mesh(mesh: Any) -> None:
    mesh.remove_degenerate_triangles()
    mesh.remove_duplicated_triangles()
    mesh.remove_duplicated_vertices()
    mesh.remove_unreferenced_vertices()


def _validate_open3d_candidate(mesh: Any, reference_diag: float) -> dict[str, int | float]:
    return _validate_mesh_candidate(
        np.asarray(mesh.vertices), np.asarray(mesh.triangles), reference_diag
    )


def _keep_significant_components(
    mesh: Any, stats: dict[str, int | float | str]
) -> None:
    triangle_count = len(mesh.triangles)
    if triangle_count == 0:
        raise MeshCandidateError("候选 Mesh 没有三角面")

    labels_vector, counts_vector, areas_vector = mesh.cluster_connected_triangles()
    labels = np.asarray(labels_vector, dtype=np.int64)
    counts = np.asarray(counts_vector, dtype=np.int64)
    areas = np.asarray(areas_vector, dtype=np.float64)
    if len(labels) != triangle_count or len(counts) == 0:
        raise MeshCandidateError("Mesh 连通分量分析失败")

    largest_id = int(np.argmax(counts))
    largest_count = int(counts[largest_id])
    largest_area = float(areas[largest_id]) if largest_id < len(areas) else 0.0
    minimum_count = max(500, int(np.ceil(largest_count * 0.02)))
    minimum_area = largest_area * 0.01 if np.isfinite(largest_area) else np.inf

    keep_ids = {largest_id}
    for component_id, count in enumerate(counts):
        area = float(areas[component_id]) if component_id < len(areas) else 0.0
        if int(count) >= minimum_count and np.isfinite(area) and area >= minimum_area:
            keep_ids.add(component_id)

    remove_mask = ~np.isin(labels, np.fromiter(keep_ids, dtype=np.int64))
    removed_triangles = int(np.count_nonzero(remove_mask))
    if removed_triangles:
        mesh.remove_triangles_by_mask(remove_mask)
        _clean_mesh(mesh)

    stats.update(
        {
            "connected_components_before": len(counts),
            "connected_components_kept": len(keep_ids),
            "component_triangles_removed": removed_triangles,
        }
    )


def _interpolate_vertex_colors(o3d: Any, pcd: Any, vertices: np.ndarray) -> np.ndarray:
    pcd_tree = o3d.geometry.KDTreeFlann(pcd)
    pcd_colors = np.asarray(pcd.colors, dtype=np.float64)
    mesh_colors = np.full((len(vertices), 3), _srgb_to_linear(np.array(0.6)), dtype=np.float64)
    for index, vertex in enumerate(vertices):
        count, indices, squared_distances = pcd_tree.search_knn_vector_3d(vertex, 4)
        if not count:
            continue
        neighbor_colors = pcd_colors[np.asarray(indices[:count], dtype=np.int64)]
        distances = np.sqrt(
            np.maximum(np.asarray(squared_distances[:count], dtype=np.float64), 0.0)
        )
        exact = distances <= 1e-12
        if np.any(exact):
            mesh_colors[index] = np.mean(neighbor_colors[exact], axis=0)
            continue
        weights = 1.0 / np.maximum(distances, 1e-12)
        mesh_colors[index] = np.average(neighbor_colors, axis=0, weights=weights)
    return np.clip(mesh_colors, 0.0, 1.0)


def _validate_reloaded_glb(
    loaded: Any,
    expected_faces: int,
    expected_bbox_diag: float,
) -> dict[str, int | float]:
    loaded_faces = 0
    loaded_normals = 0
    geometries = [
        geometry
        for geometry in loaded.geometry.values()
        if hasattr(geometry, "faces") and hasattr(geometry, "vertices")
    ]
    if not geometries:
        raise RuntimeError("Mesh GLB 重载后没有几何体")

    for geometry in geometries:
        vertices = np.asarray(geometry.vertices)
        faces = np.asarray(geometry.faces)
        if vertices.ndim != 2 or vertices.shape[1] != 3 or not np.isfinite(vertices).all():
            raise RuntimeError("Mesh GLB 重载后的顶点无效")
        if faces.ndim != 2 or faces.shape[1] != 3 or not np.isfinite(faces).all():
            raise RuntimeError("Mesh GLB 重载后的三角面无效")
        face_indices = faces.astype(np.int64, copy=False)
        if np.any(face_indices < 0) or np.any(face_indices >= len(vertices)):
            raise RuntimeError("Mesh GLB 重载后的三角面索引越界")
        loaded_faces += len(face_indices)

        normals = getattr(geometry, "vertex_normals", None)
        if normals is not None:
            normal_values = np.asarray(normals, dtype=np.float64)
            if normal_values.size:
                normal_lengths = np.linalg.norm(normal_values, axis=1)
                if (
                    normal_values.shape != vertices.shape
                    or not np.isfinite(normal_values).all()
                    or np.any(normal_lengths <= 1e-8)
                ):
                    raise RuntimeError("Mesh GLB 重载后的顶点法线无效")
                loaded_normals += len(normal_values)

    if loaded_faces != expected_faces:
        raise RuntimeError(
            f"Mesh GLB 重载后三角面数量不一致: {loaded_faces} != {expected_faces}"
        )

    bounds = np.asarray(loaded.bounds, dtype=np.float64)
    if bounds.shape != (2, 3) or not np.isfinite(bounds).all():
        raise RuntimeError("Mesh GLB 重载后的包围盒无效")
    loaded_bbox_diag = float(np.linalg.norm(bounds[1] - bounds[0]))
    if not np.isfinite(loaded_bbox_diag) or loaded_bbox_diag <= np.finfo(np.float64).eps:
        raise RuntimeError("Mesh GLB 重载后的包围盒为空")
    bbox_ratio = loaded_bbox_diag / expected_bbox_diag
    if not 0.99 <= bbox_ratio <= 1.01:
        raise RuntimeError(f"Mesh GLB 重载后的包围盒尺度变化过大: ratio={bbox_ratio}")

    return {
        "reloaded_triangles": loaded_faces,
        "reloaded_bbox_diagonal": loaded_bbox_diag,
        "reloaded_bbox_ratio": bbox_ratio,
        "reloaded_vertex_normals": loaded_normals,
    }


def build_mesh(vis_pred: dict[str, Any], conf_pct: float, tmpdir: str) -> MeshBuildResult:
    try:
        import open3d as o3d
    except ImportError:
        return MeshBuildResult(error="GPU Worker 未安装 open3d，无法生成 Mesh")

    stats: dict[str, int | float | str] = {
        "open3d_version": getattr(o3d, "__version__", "unknown")
    }
    try:
        points, colors, input_stats = _prepare_inputs(vis_pred, conf_pct)
        stats.update(input_stats)
        logger.info(
            "Mesh input: %d/%d points (confidence cutoff %.6f)",
            len(points),
            stats["input_points"],
            stats["confidence_cutoff"],
        )
        if len(points) < 1000:
            raise MeshInputError(f"有效点数不足: {len(points)} < 1000")

        robust_min, robust_max, robust_bbox_diag = _robust_point_bounds(points)
        stats.update(
            {
                "robust_bbox_diagonal": robust_bbox_diag,
                "robust_bbox_min_x": float(robust_min[0]),
                "robust_bbox_min_y": float(robust_min[1]),
                "robust_bbox_min_z": float(robust_min[2]),
                "robust_bbox_max_x": float(robust_max[0]),
                "robust_bbox_max_y": float(robust_max[1]),
                "robust_bbox_max_z": float(robust_max[2]),
            }
        )

        pcd = o3d.geometry.PointCloud()
        pcd.points = o3d.utility.Vector3dVector(points)
        pcd.colors = o3d.utility.Vector3dVector(colors)

        voxel_size = max(robust_bbox_diag * 0.0025, 1e-9)
        pcd = pcd.voxel_down_sample(voxel_size)
        stats["voxel_size"] = voxel_size
        stats["downsampled_points_before_outlier_removal"] = len(pcd.points)
        logger.info("Mesh downsample: %d points (voxel=%.6g)", len(pcd.points), voxel_size)
        if len(pcd.points) < 100:
            raise MeshInputError(f"降采样后有效点数不足: {len(pcd.points)} < 100")

        outlier_neighbors = min(30, len(pcd.points) - 1)
        pcd, retained_indices = pcd.remove_statistical_outlier(
            nb_neighbors=outlier_neighbors, std_ratio=2.0
        )
        stats.update(
            {
                "outlier_nb_neighbors": outlier_neighbors,
                "outlier_std_ratio": 2.0,
                "statistical_inliers": len(retained_indices),
                "statistical_outliers_removed":
                    int(stats["downsampled_points_before_outlier_removal"]) - len(pcd.points),
                "downsampled_points": len(pcd.points),
            }
        )
        logger.info(
            "Statistical outlier removal retained %d points", len(pcd.points)
        )
        if len(pcd.points) < 100:
            raise MeshInputError(f"离群点清理后有效点数不足: {len(pcd.points)} < 100")

        _, _, reconstruction_diag = _robust_point_bounds(np.asarray(pcd.points))
        stats["reconstruction_bbox_diagonal"] = reconstruction_diag
        radius = max(voxel_size * 3.0, reconstruction_diag * 0.01)
        stats["normal_radius"] = radius
        pcd.estimate_normals(
            o3d.geometry.KDTreeSearchParamHybrid(radius=radius, max_nn=30)
        )
        try:
            pcd.orient_normals_consistent_tangent_plane(
                k=min(30, len(pcd.points) - 1)
            )
        except Exception as exc:
            logger.warning(
                "Consistent normal orientation failed, using estimated normals: %s", exc
            )
        pcd.normalize_normals()

        mesh = None
        algorithm = "poisson"
        try:
            candidate, densities = o3d.geometry.TriangleMesh.create_from_point_cloud_poisson(
                pcd, depth=7, scale=1.05, linear_fit=False
            )
            density_values = np.asarray(densities, dtype=np.float64)
            if density_values.size:
                finite_density = density_values[np.isfinite(density_values)]
                if finite_density.size:
                    density_cutoff = float(np.quantile(finite_density, 0.05))
                    candidate.remove_vertices_by_mask(
                        ~np.isfinite(density_values) | (density_values < density_cutoff)
                    )
                    stats["poisson_density_cutoff"] = density_cutoff
            candidate = candidate.crop(pcd.get_axis_aligned_bounding_box())
            _clean_mesh(candidate)
            candidate_stats = _validate_open3d_candidate(candidate, reconstruction_diag)
            stats.update(
                {
                    "poisson_candidate_vertices": candidate_stats["vertices"],
                    "poisson_candidate_triangles": candidate_stats["triangles"],
                    "poisson_candidate_area": candidate_stats["surface_area"],
                    "poisson_candidate_bbox_ratio": candidate_stats["bbox_scale_ratio"],
                }
            )
            mesh = candidate
        except Exception as exc:
            stats["poisson_error"] = str(exc)
            logger.warning(
                "Poisson reconstruction did not produce a valid candidate; "
                "trying Ball Pivoting: %s",
                exc,
            )

        if mesh is None:
            algorithm = "ball_pivoting"
            try:
                candidate = _ball_pivoting(o3d, pcd, stats)
                _clean_mesh(candidate)
                candidate_stats = _validate_open3d_candidate(
                    candidate, reconstruction_diag
                )
                stats.update(
                    {
                        "bpa_candidate_vertices": candidate_stats["vertices"],
                        "bpa_candidate_triangles": candidate_stats["triangles"],
                        "bpa_candidate_area": candidate_stats["surface_area"],
                        "bpa_candidate_bbox_ratio": candidate_stats["bbox_scale_ratio"],
                    }
                )
                mesh = candidate
            except Exception as exc:
                raise RuntimeError(
                    f"Poisson 与 Ball Pivoting 均未生成有效 Mesh: {exc}"
                ) from exc

        _keep_significant_components(mesh, stats)
        _validate_open3d_candidate(mesh, reconstruction_diag)

        triangles_before_cap = len(mesh.triangles)
        if triangles_before_cap > _MAX_FINAL_TRIANGLES:
            mesh = mesh.simplify_quadric_decimation(
                target_number_of_triangles=_MAX_FINAL_TRIANGLES
            )
            _clean_mesh(mesh)
            if len(mesh.triangles) > _MAX_FINAL_TRIANGLES:
                mesh = mesh.simplify_quadric_decimation(
                    target_number_of_triangles=_MAX_FINAL_TRIANGLES
                )
                _clean_mesh(mesh)
        triangles_after_cap = len(mesh.triangles)
        if triangles_after_cap > _MAX_FINAL_TRIANGLES:
            raise RuntimeError(
                f"Mesh 三角面无法压缩到上限: {triangles_after_cap} > {_MAX_FINAL_TRIANGLES}"
            )
        stats.update(
            {
                "triangle_cap": _MAX_FINAL_TRIANGLES,
                "mesh_triangles_before_cap": triangles_before_cap,
                "mesh_triangles_after_cap": triangles_after_cap,
            }
        )

        final_metrics = _validate_open3d_candidate(mesh, reconstruction_diag)
        mesh.compute_vertex_normals()
        mesh.normalize_normals()
        mesh_vertices = np.asarray(mesh.vertices, dtype=np.float64)
        vertex_normals = np.asarray(mesh.vertex_normals, dtype=np.float64)
        normal_lengths = np.linalg.norm(vertex_normals, axis=1)
        if (
            vertex_normals.shape != mesh_vertices.shape
            or not np.isfinite(vertex_normals).all()
            or np.any(normal_lengths <= 1e-8)
        ):
            raise RuntimeError("Mesh 顶点法线无效")
        vertex_normals = vertex_normals / normal_lengths[:, None]
        mesh.vertex_normals = o3d.utility.Vector3dVector(vertex_normals)

        mesh_colors = _interpolate_vertex_colors(o3d, pcd, mesh_vertices)
        mesh.vertex_colors = o3d.utility.Vector3dVector(mesh_colors)

        stats.update(
            {
                "algorithm": algorithm,
                "mesh_vertices": len(mesh.vertices),
                "mesh_triangles": len(mesh.triangles),
                "mesh_surface_area": final_metrics["surface_area"],
                "mesh_bbox_diagonal": final_metrics["bbox_diagonal"],
                "mesh_bbox_scale_ratio": final_metrics["bbox_scale_ratio"],
                "color_interpolation_neighbors": 4,
            }
        )
        logger.info(
            "Mesh built with %s: %d vertices, %d triangles",
            algorithm,
            len(mesh.vertices),
            len(mesh.triangles),
        )

        import trimesh

        faces = np.asarray(mesh.triangles, dtype=np.int64)
        vertex_colors = np.clip(np.asarray(mesh.vertex_colors) * 255.0, 0, 255).astype(
            np.uint8
        )
        alpha = np.full((len(vertex_colors), 1), 255, dtype=np.uint8)
        rgba = np.concatenate([vertex_colors, alpha], axis=1)
        exported_mesh = trimesh.Trimesh(
            vertices=mesh_vertices,
            faces=faces,
            vertex_colors=rgba,
            vertex_normals=vertex_normals,
            process=False,
        )
        data = trimesh.Scene(exported_mesh).export(file_type="glb")
        if not isinstance(data, bytes) or len(data) < 20 or data[:4] != b"glTF":
            raise RuntimeError("trimesh 未能导出有效 Mesh GLB")

        loaded = trimesh.load(
            io.BytesIO(data), file_type="glb", force="scene", process=False
        )
        reload_stats = _validate_reloaded_glb(
            loaded,
            expected_faces=len(faces),
            expected_bbox_diag=float(final_metrics["bbox_diagonal"]),
        )
        stats.update(reload_stats)
        stats["glb_bytes"] = len(data)
        return MeshBuildResult(data=data, stats=stats)
    except Exception as exc:
        logger.exception("Mesh reconstruction failed")
        return MeshBuildResult(error=str(exc), stats=stats)


def _self_test() -> None:
    phi = np.linspace(0.05, np.pi - 0.05, 32)
    theta = np.linspace(0.0, 2.0 * np.pi, 64, endpoint=False)
    phi_grid, theta_grid = np.meshgrid(phi, theta, indexing="ij")
    points = np.stack(
        [
            np.sin(phi_grid) * np.cos(theta_grid),
            np.sin(phi_grid) * np.sin(theta_grid),
            np.cos(phi_grid),
        ],
        axis=-1,
    )
    colors = (points + 1.0) / 2.0
    confidence = np.ones(points.shape[:-1], dtype=np.float32)
    with tempfile.TemporaryDirectory() as tmpdir:
        result = build_mesh(
            {
                "world_points_from_depth": points,
                "images": colors,
                "depth_conf": confidence,
            },
            0.0,
            tmpdir,
        )
    if not result.success:
        raise SystemExit(f"Mesh self-test failed: {result.error}; stats={result.stats}")
    print(f"Mesh self-test passed: {result.stats}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        logging.basicConfig(level=logging.INFO)
        _self_test()
