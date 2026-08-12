import importlib.util
import json
import pathlib
import sys
import unittest
from unittest import mock

import numpy as np
import trimesh


ROOT = pathlib.Path(__file__).resolve().parents[1]
GLB_EXPORT_PATH = ROOT / "lingbot-map-vendor" / "lingbot_map" / "vis" / "glb_export.py"

sky_segmentation = mock.Mock()
sky_segmentation._SKYSEG_INPUT_SIZE = (384, 384)
sky_segmentation._SKYSEG_SOFT_THRESHOLD = 0.5
sky_segmentation._mask_to_float = lambda value: value
sky_segmentation._mask_to_uint8 = lambda value: value
sky_segmentation._result_map_to_non_sky_conf = lambda value: value
cv2_module = mock.Mock()
with mock.patch.dict(sys.modules, {
    "cv2": cv2_module,
    "lingbot_map.vis.sky_segmentation": sky_segmentation,
}):
    GLB_EXPORT_SPEC = importlib.util.spec_from_file_location("artifact_v2_glb_export", GLB_EXPORT_PATH)
    glb_export = importlib.util.module_from_spec(GLB_EXPORT_SPEC)
    assert GLB_EXPORT_SPEC.loader is not None
    GLB_EXPORT_SPEC.loader.exec_module(glb_export)

compute_scene_alignment = glb_export.compute_scene_alignment
predictions_to_glb = glb_export.predictions_to_glb

GPU_SERVER_PATH = pathlib.Path(__file__).with_name("gpu_server.py")
GPU_SERVER_SPEC = importlib.util.spec_from_file_location("artifact_v2_gpu_server", GPU_SERVER_PATH)
gpu_server = importlib.util.module_from_spec(GPU_SERVER_SPEC)
assert GPU_SERVER_SPEC.loader is not None
GPU_SERVER_SPEC.loader.exec_module(gpu_server)


class ArtifactV2Tests(unittest.TestCase):
    def test_compute_scene_alignment_matches_exported_scene_transform(self):
        extrinsics = np.eye(4, dtype=np.float64)[None]
        extrinsics[0, :3, 3] = [1.0, 2.0, 3.0]
        expected = compute_scene_alignment(extrinsics)

        scene = trimesh.Scene(trimesh.PointCloud(vertices=[[0.0, 0.0, 0.0]]))
        glb_export.apply_scene_alignment(scene, extrinsics)
        np.testing.assert_allclose(scene.graph[scene.graph.nodes_geometry[0]][0], expected)

    def test_point_glb_colors_are_linearized_from_srgb(self):
        predictions = {
            "world_points": np.array([[[[0.0, 0.0, 0.0]]]], dtype=np.float32),
            "world_points_conf": np.ones((1, 1, 1), dtype=np.float32),
            "images": np.full((1, 3, 1, 1), 0.5, dtype=np.float32),
            "extrinsic": np.eye(4, dtype=np.float32)[None, :3, :4],
        }
        scene = predictions_to_glb(predictions, conf_thres=0, show_cam=False)
        point_cloud = next(iter(scene.geometry.values()))
        expected = int(round((((0.5 + 0.055) / 1.055) ** 2.4) * 255.0))
        np.testing.assert_array_equal(point_cloud.colors[0, :3], [expected] * 3)

    def test_confidence_and_status_metadata_are_safe(self):
        self.assertEqual(gpu_server._clamp_conf_percentile(-5), 0.0)
        self.assertEqual(gpu_server._clamp_conf_percentile(150), 100.0)
        self.assertEqual(gpu_server._clamp_conf_percentile("not-a-number"), 1.5)

        settings = {
            "conf_threshold": 12.5,
            "_conf_pct": 12.5,
            "_dynamic_stride": 2,
            "_artifact_keyframes": 8,
            "GPU_SECRET": "must-not-leak",
        }
        metadata = gpu_server._artifact_metadata(settings)
        self.assertEqual(metadata["version"], 2)
        self.assertEqual(metadata["color_space"], "linear-srgb")
        self.assertEqual(metadata["confidence_percentile"], 12.5)
        self.assertNotIn("GPU_SECRET", metadata)

        captured = {}

        def fake_urlopen(request, timeout):
            captured.update(json.loads(request.data))
            return mock.Mock()

        with mock.patch.object(gpu_server.urllib.request, "urlopen", fake_urlopen):
            gpu_server._update_status(
                "job-id",
                "completed",
                1.0,
                artifact_metadata=metadata,
                mesh_stats={"mesh_triangles": 7, "alignment_applied": True},
            )
        self.assertEqual(captured["artifact_metadata"], metadata)
        self.assertEqual(captured["mesh_stats"]["mesh_triangles"], 7)
        self.assertNotIn("Authorization", json.dumps(captured))
        self.assertNotIn("must-not-leak", json.dumps(captured))


if __name__ == "__main__":
    unittest.main()
