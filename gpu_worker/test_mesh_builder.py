import tempfile
import unittest
from unittest import mock

import numpy as np

from gpu_worker.mesh_builder import MeshInputError, _prepare_inputs, build_mesh


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

    def test_reports_missing_open3d(self):
        with tempfile.TemporaryDirectory() as tmpdir, mock.patch.dict("sys.modules", {"open3d": None}):
            result = build_mesh(
                {"world_points_from_depth": np.zeros((1000, 3), dtype=np.float32)},
                0,
                tmpdir,
            )
        self.assertFalse(result.success)
        self.assertIn("open3d", result.error or "")


if __name__ == "__main__":
    unittest.main()
