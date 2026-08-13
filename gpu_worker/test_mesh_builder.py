import tempfile
import unittest
from unittest import mock

import numpy as np

from gpu_worker.mesh_builder import (
    MeshBuildConfig,
    MeshCandidateError,
    MeshInputError,
    _prepare_inputs,
    _robust_point_bounds,
    _srgb_to_linear,
    _validate_mesh_candidate,
    build_mesh,
    extract_legacy_point_glb,
)


class MeshInputTests(unittest.TestCase):
    def test_filters_nonfinite_points_and_matching_colors(self):
        points = np.zeros((1, 2, 2, 3), dtype=np.float32)
        points[0, 0, 0] = [np.nan, 0, 0]
        points[0, 0, 1] = [1, 0, 0]
        points[0, 1, 0] = [0, 1, 0]
        points[0, 1, 1] = [0, 0, 1]
        colors = np.ones((1, 3, 2, 2), dtype=np.float32)
        confidence = np.ones((1, 2, 2), dtype=np.float32)

        filtered_points, filtered_colors, stats = _prepare_inputs(
            {
                "world_points_from_depth": points,
                "images": colors,
                "depth_conf": confidence,
            },
            0,
        )

        self.assertEqual(filtered_points.shape, (3, 3))
        self.assertEqual(filtered_colors.shape, (3, 3))
        self.assertEqual(stats["input_points"], 4)
        self.assertEqual(stats["filtered_points"], 3)

    def test_converts_srgb_colors_to_linear(self):
        colors = np.array(
            [[0.0, 0.04045, 0.5], [1.0, 128.0 / 255.0, 1.0]], dtype=np.float64
        )
        expected_first = np.array([0.0, 0.04045 / 12.92, ((0.5 + 0.055) / 1.055) ** 2.4])

        direct = _srgb_to_linear(colors[0])
        _, converted, stats = _prepare_inputs(
            {
                "world_points_from_depth": np.zeros((2, 3), dtype=np.float32),
                "images": colors,
            },
            0,
        )

        np.testing.assert_allclose(direct, expected_first, rtol=1e-12, atol=1e-12)
        np.testing.assert_allclose(converted[0], expected_first, rtol=1e-12, atol=1e-12)
        np.testing.assert_allclose(converted[1, [0, 2]], [1.0, 1.0], rtol=1e-12)
        self.assertAlmostEqual(converted[1, 1], ((128.0 / 255.0 + 0.055) / 1.055) ** 2.4)
        self.assertEqual(stats["color_space"], "linear-srgb")

    def test_applies_homogeneous_alignment_matrix(self):
        points = np.array([[1.0, 2.0, 3.0], [-1.0, 0.0, 2.0]])
        alignment = np.array(
            [
                [0.0, -1.0, 0.0, 10.0],
                [1.0, 0.0, 0.0, -2.0],
                [0.0, 0.0, 2.0, 1.0],
                [0.0, 0.0, 0.0, 1.0],
            ]
        )

        aligned, _, stats = _prepare_inputs(
            {"world_points_from_depth": points, "alignment_matrix": alignment},
            0,
        )

        np.testing.assert_allclose(aligned, [[8.0, -1.0, 7.0], [10.0, -3.0, 5.0]])
        self.assertEqual(stats["alignment_applied"], 1)

    def test_rejects_invalid_alignment_matrix(self):
        with self.assertRaisesRegex(MeshInputError, "alignment_matrix 形状无效"):
            _prepare_inputs(
                {
                    "world_points_from_depth": np.zeros((2, 3)),
                    "alignment_matrix": np.eye(2),
                },
                0,
            )

    def test_rejects_confidence_shape_mismatch(self):
        with self.assertRaisesRegex(MeshInputError, "置信度与点坐标数量不一致"):
            _prepare_inputs(
                {
                    "world_points_from_depth": np.zeros((2, 2, 3), dtype=np.float32),
                    "depth_conf": np.ones(3, dtype=np.float32),
                },
                0,
            )

    def test_uses_confidence_for_selected_point_branch(self):
        depth_points = np.zeros((1, 2, 2, 3), dtype=np.float32)
        pointmap_points = np.zeros((1, 3, 3, 3), dtype=np.float32)
        _, _, depth_stats = _prepare_inputs(
            {
                "world_points_from_depth": depth_points,
                "world_points": pointmap_points,
                "depth_conf": np.ones((1, 2, 2), dtype=np.float32),
                "world_points_conf": np.ones((1, 3, 3), dtype=np.float32),
            },
            0,
        )
        self.assertEqual(depth_stats["input_points"], 4)

        _, _, pointmap_stats = _prepare_inputs(
            {
                "world_points": pointmap_points,
                "world_points_conf": np.ones((1, 3, 3), dtype=np.float32),
                "depth_conf": np.ones((1, 2, 2), dtype=np.float32),
            },
            0,
        )
        self.assertEqual(pointmap_stats["input_points"], 9)

    def test_preserves_linear_colors_for_artifact_v2(self):
        source = np.array([[0.5, 0.25, 0.75], [0.1, 0.2, 0.3]], dtype=np.float64)
        _, converted, stats = _prepare_inputs(
            {
                "world_points_from_depth": np.zeros((2, 3), dtype=np.float32),
                "images": source,
                "input_color_space": "linear-srgb",
                "source_prealigned": True,
            },
            0,
        )
        np.testing.assert_allclose(converted, source)
        self.assertEqual(stats["source_prealigned"], 1)
        self.assertEqual(stats["alignment_applied"], 0)

    def test_rejects_second_alignment_for_prealigned_source(self):
        with self.assertRaisesRegex(MeshInputError, "不得再次应用"):
            _prepare_inputs(
                {
                    "world_points_from_depth": np.zeros((2, 3)),
                    "source_prealigned": True,
                    "alignment_matrix": np.eye(4),
                },
                0,
            )

    def test_validates_typed_mesh_config(self):
        config = MeshBuildConfig.from_mapping({"poisson_depth": 8, "target_triangles": 300_000})
        self.assertEqual(config.poisson_depth, 8)
        with self.assertRaisesRegex(MeshInputError, "未知 Mesh 参数"):
            MeshBuildConfig.from_mapping({"unknown": 1})
        with self.assertRaisesRegex(MeshInputError, "严格递增"):
            MeshBuildConfig.from_mapping({"bpa_radius_multipliers": [3, 2, 6]})

    def test_extracts_point_nodes_and_skips_triangle_camera_geometry(self):
        import trimesh

        points = trimesh.points.PointCloud(
            vertices=np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0]]),
            colors=np.array([[128, 64, 32, 255], [255, 255, 255, 255]], dtype=np.uint8),
        )
        camera = trimesh.creation.box(extents=[0.1, 0.1, 0.1])
        scene = trimesh.Scene()
        transform = np.eye(4)
        transform[:3, 3] = [10, 2, 3]
        scene.add_geometry(points, node_name="points", transform=transform)
        scene.add_geometry(camera, node_name="camera")

        extracted, stats = extract_legacy_point_glb(scene.export(file_type="glb"), "linear-srgb")
        np.testing.assert_allclose(
            extracted["world_points_from_depth"], [[10, 2, 3], [11, 2, 3]]
        )
        self.assertEqual(stats["glb_point_nodes"], 1)
        self.assertEqual(stats["glb_triangle_nodes_skipped"], 1)
        self.assertTrue(extracted["source_prealigned"])
        self.assertEqual(extracted["input_color_space"], "linear-srgb")

    def test_reports_missing_open3d(self):
        with tempfile.TemporaryDirectory() as tmpdir, mock.patch.dict(
            "sys.modules", {"open3d": None}
        ):
            result = build_mesh(
                {"world_points_from_depth": np.zeros((1000, 3), dtype=np.float32)},
                0,
                tmpdir,
            )
        self.assertFalse(result.success)
        self.assertIn("open3d", result.error or "")


class RobustBoundsTests(unittest.TestCase):
    def test_percentile_bounds_ignore_extreme_outliers_for_scale(self):
        axis = np.linspace(-1.0, 1.0, 10_000)
        points = np.column_stack([axis, axis * 0.5, axis * 0.25])
        points = np.vstack([points, [1e9, -1e9, 1e9]])

        lower, upper, diagonal = _robust_point_bounds(points)

        self.assertLess(diagonal, 3.0)
        self.assertGreater(diagonal, 2.0)
        self.assertTrue(np.all(np.abs(lower) < 2.0))
        self.assertTrue(np.all(np.abs(upper) < 2.0))
        self.assertGreater(np.linalg.norm(np.ptp(points, axis=0)), 1e9)


class MeshCandidateValidationTests(unittest.TestCase):
    @staticmethod
    def _valid_candidate():
        vertex_count = 300
        angles = np.linspace(0.0, 2.0 * np.pi, vertex_count, endpoint=False)
        vertices = np.column_stack([np.cos(angles), np.sin(angles), angles / (2.0 * np.pi)])
        faces = np.array(
            [[0, index, index + 1] for index in range(1, vertex_count - 1)],
            dtype=np.int64,
        )
        faces = np.vstack([faces, faces[:202][:, ::-1]])
        return vertices, faces

    def test_accepts_finite_mesh_with_enough_area_and_reasonable_scale(self):
        vertices, faces = self._valid_candidate()

        metrics = _validate_mesh_candidate(vertices, faces, reference_diag=3.0)

        self.assertEqual(metrics["vertices"], 300)
        self.assertEqual(metrics["triangles"], 500)
        self.assertGreater(metrics["surface_area"], 0.0)
        self.assertGreater(metrics["bbox_scale_ratio"], 0.02)
        self.assertLess(metrics["bbox_scale_ratio"], 5.0)

    def test_rejects_nonfinite_vertices(self):
        vertices, faces = self._valid_candidate()
        vertices[10, 0] = np.nan

        with self.assertRaisesRegex(MeshCandidateError, "顶点包含 NaN/Inf"):
            _validate_mesh_candidate(vertices, faces, reference_diag=3.0)

    def test_rejects_zero_area_faces(self):
        vertices = np.column_stack(
            [np.linspace(0.0, 1.0, 300), np.zeros(300), np.zeros(300)]
        )
        faces = np.tile(np.array([[0, 1, 2]], dtype=np.int64), (500, 1))

        with self.assertRaisesRegex(MeshCandidateError, "面积无效"):
            _validate_mesh_candidate(vertices, faces, reference_diag=1.0)

    def test_rejects_unreasonable_bbox_scale(self):
        vertices, faces = self._valid_candidate()

        with self.assertRaisesRegex(MeshCandidateError, "尺度不合理"):
            _validate_mesh_candidate(vertices * 1e6, faces, reference_diag=1.0)


if __name__ == "__main__":
    unittest.main()
