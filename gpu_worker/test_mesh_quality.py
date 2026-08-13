import unittest

import numpy as np
import trimesh

from gpu_worker.mesh_quality import (
    compute_mesh_quality,
    _edge_classification,
    _degenerate_faces,
    _self_intersecting,
)


class EdgeClassificationTests(unittest.TestCase):
    def test_closed_triangle_mesh_has_no_boundary(self):
        # tetrahedron: 4 triangles, watertight
        v = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1]], dtype=float)
        f = np.array([[0, 1, 2], [0, 2, 3], [0, 3, 1], [1, 3, 2]])
        boundary, non_manifold = _edge_classification(f)
        self.assertEqual(boundary, 0)
        self.assertEqual(non_manifold, 0)

    def test_open_triangle_has_boundary(self):
        f = np.array([[0, 1, 2]])
        boundary, non_manifold = _edge_classification(f)
        self.assertEqual(boundary, 3)
        self.assertEqual(non_manifold, 0)

    def test_three_faces_sharing_edge_are_non_manifold(self):
        # edge (0,1) shared by three faces
        f = np.array([[0, 1, 2], [0, 1, 3], [0, 1, 4]])
        boundary, non_manifold = _edge_classification(f)
        self.assertEqual(non_manifold, 1)

    def test_degenerate_face_count(self):
        f = np.array([[0, 0, 1], [0, 1, 2]])
        self.assertEqual(_degenerate_faces(f), 1)


class SelfIntersectionTests(unittest.TestCase):
    def test_crossing_triangles_intersect(self):
        # one triangle in the XY plane, one vertical piercing it
        v = np.array([[0, 0, 0], [2, 0, 0], [0, 2, 0], [0.5, 0.5, -1], [0.5, 0.5, 1], [0.5, 1.5, 0]], dtype=float)
        f = np.array([[0, 1, 2], [3, 4, 5]])
        mesh = trimesh.Trimesh(vertices=v, faces=f, process=False)
        self.assertTrue(_self_intersecting(mesh))

    def test_disjoint_triangles_do_not_intersect(self):
        v = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [5, 5, 5], [6, 5, 5], [5, 6, 5]], dtype=float)
        f = np.array([[0, 1, 2], [3, 4, 5]])
        mesh = trimesh.Trimesh(vertices=v, faces=f, process=False)
        self.assertFalse(_self_intersecting(mesh))


class ComputeMeshQualityTests(unittest.TestCase):
    def test_watertight_box_qualifies_as_entity(self):
        mesh = trimesh.creation.box()
        quality = compute_mesh_quality(mesh, scene_diagonal=mesh.scale * 2.0, voxel_size=0.05)
        self.assertTrue(quality["watertight"])
        self.assertEqual(quality["boundary_edges"], 0)
        self.assertEqual(quality["non_manifold_edges"], 0)
        self.assertIs(quality["entity_qualified"], True)
        self.assertEqual(quality["surface_type"], "entity")

    def test_open_plane_is_surface_not_entity(self):
        mesh = trimesh.Trimesh(
            vertices=np.array([[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]], dtype=float),
            faces=np.array([[0, 1, 2], [0, 2, 3]]),
            process=False,
        )
        quality = compute_mesh_quality(mesh, scene_diagonal=1.0, voxel_size=0.05)
        self.assertFalse(quality["watertight"])
        self.assertGreater(quality["boundary_edges"], 0)
        self.assertIs(quality["entity_qualified"], False)
        self.assertEqual(quality["surface_type"], "surface")

    def test_point_metrics_computed_from_source_points(self):
        mesh = trimesh.creation.box()
        points = mesh.vertices + np.array([[0, 0, 1.0]]) * 0.0
        quality = compute_mesh_quality(mesh, source_points=points, voxel_size=0.05)
        self.assertIn("point_to_surface_p50", quality)
        self.assertIn("coverage", quality)


if __name__ == "__main__":
    unittest.main()
