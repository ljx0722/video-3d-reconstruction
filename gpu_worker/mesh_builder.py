from __future__ import annotations

import argparse
import io
import logging
import tempfile
from dataclasses import dataclass, field
from typing import Any

import numpy as np

logger = logging.getLogger("gpu-worker.mesh")


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


def _prepare_inputs(vis_pred: dict[str, Any], conf_pct: float) -> tuple[np.ndarray, np.ndarray, dict[str, int | float | str]]:
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
    colors = np.clip(colors_flat[mask], 0.0, 1.0)
    stats: dict[str, int | float | str] = {
        "input_points": input_points,
        "filtered_points": len(points),
        "confidence_percentile": float(np.clip(conf_pct, 0.0, 100.0)),
        "confidence_cutoff": cutoff,
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


def build_mesh(vis_pred: dict[str, Any], conf_pct: float, tmpdir: str) -> MeshBuildResult:
    try:
        import open3d as o3d
    except ImportError:
        return MeshBuildResult(error="GPU Worker 未安装 open3d，无法生成 Mesh")

    stats: dict[str, int | float | str] = {"open3d_version": getattr(o3d, "__version__", "unknown")}
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

        pcd = o3d.geometry.PointCloud()
        pcd.points = o3d.utility.Vector3dVector(points)
        pcd.colors = o3d.utility.Vector3dVector(colors)

        bounds = pcd.get_max_bound() - pcd.get_min_bound()
        bbox_diag = float(np.linalg.norm(bounds))
        if not np.isfinite(bbox_diag) or bbox_diag <= 1e-6:
            raise MeshInputError(f"点云包围盒无效: diagonal={bbox_diag}")

        voxel_size = max(1e-4, bbox_diag * 0.005)
        pcd = pcd.voxel_down_sample(voxel_size)
        stats["voxel_size"] = voxel_size
        stats["downsampled_points"] = len(pcd.points)
        logger.info("Mesh downsample: %d points (voxel=%.6f)", len(pcd.points), voxel_size)
        if len(pcd.points) < 100:
            raise MeshInputError(f"降采样后有效点数不足: {len(pcd.points)} < 100")

        downsampled_bounds = pcd.get_max_bound() - pcd.get_min_bound()
        downsampled_diag = float(np.linalg.norm(downsampled_bounds))
        radius = max(voxel_size * 3.0, downsampled_diag * 0.01)
        pcd.estimate_normals(o3d.geometry.KDTreeSearchParamHybrid(radius=radius, max_nn=30))
        try:
            pcd.orient_normals_consistent_tangent_plane(k=min(30, len(pcd.points) - 1))
        except Exception as exc:
            logger.warning("Consistent normal orientation failed, using estimated normals: %s", exc)
        pcd.normalize_normals()

        mesh = None
        algorithm = "poisson"
        try:
            candidate, densities = o3d.geometry.TriangleMesh.create_from_point_cloud_poisson(
                pcd, depth=6, scale=1.05, linear_fit=False
            )
            if len(densities):
                density_values = np.asarray(densities)
                candidate.remove_vertices_by_mask(density_values < np.quantile(density_values, 0.05))
            candidate = candidate.crop(pcd.get_axis_aligned_bounding_box())
            if len(candidate.triangles) >= 5:
                mesh = candidate
            else:
                logger.warning("Poisson produced only %d faces; trying Ball Pivoting", len(candidate.triangles))
        except Exception as exc:
            logger.warning("Poisson reconstruction failed; trying Ball Pivoting: %s", exc)

        if mesh is None:
            algorithm = "ball_pivoting"
            mesh = _ball_pivoting(o3d, pcd, stats)

        if len(mesh.triangles) < 5:
            raise RuntimeError(f"{algorithm} 仅生成 {len(mesh.triangles)} 个三角面")

        if len(mesh.triangles) > 300_000:
            mesh = mesh.simplify_quadric_decimation(target_number_of_triangles=300_000)
        mesh.remove_degenerate_triangles()
        mesh.remove_duplicated_triangles()
        mesh.remove_duplicated_vertices()
        mesh.remove_unreferenced_vertices()
        mesh.compute_vertex_normals()

        pcd_tree = o3d.geometry.KDTreeFlann(pcd)
        pcd_colors = np.asarray(pcd.colors)
        mesh_vertices = np.asarray(mesh.vertices)
        mesh_colors = np.full((len(mesh_vertices), 3), 0.6, dtype=np.float64)
        for index, vertex in enumerate(mesh_vertices):
            count, indices, _ = pcd_tree.search_knn_vector_3d(vertex, 1)
            if count:
                mesh_colors[index] = pcd_colors[indices[0]]
        mesh.vertex_colors = o3d.utility.Vector3dVector(np.clip(mesh_colors, 0.0, 1.0))

        stats.update({
            "algorithm": algorithm,
            "mesh_vertices": len(mesh.vertices),
            "mesh_triangles": len(mesh.triangles),
        })
        logger.info(
            "Mesh built with %s: %d vertices, %d triangles",
            algorithm,
            len(mesh.vertices),
            len(mesh.triangles),
        )

        import trimesh

        faces = np.asarray(mesh.triangles, dtype=np.int64)
        vertex_colors = np.clip(np.asarray(mesh.vertex_colors) * 255.0, 0, 255).astype(np.uint8)
        alpha = np.full((len(vertex_colors), 1), 255, dtype=np.uint8)
        rgba = np.concatenate([vertex_colors, alpha], axis=1)
        exported_mesh = trimesh.Trimesh(
            vertices=np.asarray(mesh.vertices),
            faces=faces,
            vertex_colors=rgba,
            process=False,
        )
        data = trimesh.Scene(exported_mesh).export(file_type="glb")
        if not isinstance(data, bytes) or len(data) < 20 or data[:4] != b"glTF":
            raise RuntimeError("trimesh 未能导出有效 Mesh GLB")

        loaded = trimesh.load(io.BytesIO(data), file_type="glb", force="scene")
        loaded_faces = sum(
            len(geometry.faces)
            for geometry in loaded.geometry.values()
            if hasattr(geometry, "faces")
        )
        if loaded_faces < 5:
            raise RuntimeError("Mesh GLB 重载验证失败")
        stats["glb_bytes"] = len(data)
        stats["reloaded_triangles"] = loaded_faces
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
            {"world_points_from_depth": points, "images": colors, "depth_conf": confidence},
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
