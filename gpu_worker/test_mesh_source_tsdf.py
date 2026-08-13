import io
import importlib.util
import unittest

import numpy as np

from gpu_worker.mesh_source import MeshSourceError, build_mesh_source_package
from gpu_worker.tsdf_builder import build_tsdf_mesh, c2w_to_w2c, filter_depth_confidence, unpack_sidecar_chunk


class MeshSourcePackageTests(unittest.TestCase):
    def test_builds_chunked_sidecar_with_expected_dtypes_and_scale(self):
        frame_count, height, width = 10, 4, 6
        depth = np.full((frame_count, height, width), 2.0, dtype=np.float32)
        confidence = np.arange(frame_count * height * width, dtype=np.float32).reshape(frame_count, height, width)
        intrinsic = np.broadcast_to(
            np.array([[4.0, 0, 2.5], [0, 4.0, 1.5], [0, 0, 1]], dtype=np.float32),
            (frame_count, 3, 3),
        ).copy()
        c2w = np.broadcast_to(np.eye(4, dtype=np.float32), (frame_count, 4, 4)).copy()
        c2w[:, 0, 3] = np.linspace(0, 1, frame_count)

        package = build_mesh_source_package(
            {"depth": depth, "depth_conf": confidence, "intrinsic": intrinsic, "extrinsic": c2w},
            np.arange(frame_count) * 3,
            np.eye(4, dtype=np.float32),
            chunk_frames=8,
        )

        self.assertEqual(package.manifest["version"], "mesh-source-v1")
        self.assertEqual(package.manifest["chunk_count"], 2)
        self.assertGreater(package.manifest["scene_diagonal"], 0)
        first = unpack_sidecar_chunk(package.chunks[0][1], expected_frames=8)
        self.assertEqual(first["depth"].dtype, np.float16)
        self.assertEqual(first["confidence"].dtype, np.float16)
        self.assertEqual(first["intrinsic"].dtype, np.float32)
        self.assertEqual(first["c2w"].dtype, np.float32)
        np.testing.assert_array_equal(first["frame_indices"], np.arange(8) * 3)

    def test_rejects_mismatched_sidecar_shapes(self):
        with self.assertRaisesRegex(MeshSourceError, "does not match"):
            build_mesh_source_package(
                {
                    "depth": np.ones((2, 3, 4)),
                    "depth_conf": np.ones((2, 3, 5)),
                    "intrinsic": np.broadcast_to(np.eye(3), (2, 3, 3)),
                    "extrinsic": np.broadcast_to(np.eye(4), (2, 4, 4)),
                },
                np.arange(2),
                np.eye(4),
            )


class TsdfMathTests(unittest.TestCase):
    def test_c2w_to_w2c_is_exact_inverse(self):
        c2w = np.eye(4)
        c2w[:3, 3] = [1, 2, 3]
        w2c = c2w_to_w2c(c2w)
        np.testing.assert_allclose(w2c[:3, 3], [-1, -2, -3])
        np.testing.assert_allclose(c2w @ w2c, np.eye(4))

    def test_filters_depth_by_keep_mask_and_uses_mask_region_for_cutoff(self):
        depth = np.ones((2, 2), dtype=np.float32)
        confidence = np.array([[1, 100], [2, 3]], dtype=np.float32)
        keep = np.array([[False, True], [False, True]])
        filtered, valid, cutoff = filter_depth_confidence(depth, confidence, 50, 0.05, 10, keep)
        self.assertEqual(cutoff, 51.5)
        np.testing.assert_array_equal(valid, [[False, True], [False, False]])
        np.testing.assert_array_equal(filtered, [[0, 1], [0, 0]])

    def test_empty_keep_mask_produces_no_valid_depth(self):
        depth = np.ones((2, 2), dtype=np.float32)
        confidence = np.ones_like(depth)
        filtered, valid, _ = filter_depth_confidence(depth, confidence, 0, 0.05, 10, np.zeros_like(depth, dtype=bool))
        self.assertFalse(np.any(valid))
        self.assertFalse(np.any(filtered))

    @unittest.skipUnless(importlib.util.find_spec("open3d"), "Open3D is not installed")
    def test_integrates_synthetic_rgbd_with_real_open3d_kernel(self):
        height = width = 32
        frame_count = 3
        depth = np.full((frame_count, height, width), 1.0, dtype=np.float32)
        confidence = np.ones_like(depth)
        intrinsic = np.broadcast_to(
            np.array([[32.0, 0, 15.5], [0, 32.0, 15.5], [0, 0, 1]], dtype=np.float32),
            (frame_count, 3, 3),
        ).copy()
        c2w = np.broadcast_to(np.eye(4, dtype=np.float32), (frame_count, 4, 4)).copy()
        c2w[:, 0, 3] = [-0.05, 0.0, 0.05]
        package = build_mesh_source_package(
            {"depth": depth, "depth_conf": confidence, "intrinsic": intrinsic, "extrinsic": c2w},
            np.arange(frame_count),
            np.eye(4),
            chunk_frames=3,
        )
        chunk_map = dict(package.chunks)
        result = build_tsdf_mesh(
            package.manifest,
            lambda entry: chunk_map[entry["name"]],
            lambda indices, h, w: np.ones((len(indices), h, w, 3), dtype=np.float32) * 0.5,
            {
                "tsdf_voxel_size_ratio": 0.005,
                "tsdf_truncation_multiplier": 4.0,
                "confidence_percentile": 0,
                "depth_min": 0.05,
                "depth_max": 2.0,
                "frame_stride": 1,
                "min_tsdf_weight": 0.1,
                "target_triangles": 50_000,
                "tsdf_block_count": 2_000,
            },
        )
        self.assertTrue(result.success, result.error)
        self.assertGreater(result.stats["mesh_triangles"], 0)
        self.assertEqual(result.data[:4], b"glTF")


if __name__ == "__main__":
    unittest.main()
