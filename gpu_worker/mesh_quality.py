from __future__ import annotations

import numpy as np
import trimesh

MAX_SELF_INTERSECTION_FACES = 200_000


def _edge_classification(faces: np.ndarray) -> tuple[int, int]:
    faces = np.asarray(faces, dtype=np.int64)
    if len(faces) == 0:
        return 0, 0
    edges = np.vstack([faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]])
    edges = np.sort(edges, axis=1)
    _, counts = np.unique(edges, axis=0, return_counts=True)
    boundary = int(np.count_nonzero(counts == 1))
    non_manifold = int(np.count_nonzero(counts >= 3))
    return boundary, non_manifold


def _degenerate_faces(faces: np.ndarray) -> int:
    faces = np.asarray(faces)
    if len(faces) == 0:
        return 0
    repeated = (faces[:, 0] == faces[:, 1]) | (faces[:, 1] == faces[:, 2]) | (faces[:, 2] == faces[:, 0])
    return int(np.count_nonzero(repeated))


def _valid_normal_ratio(triangles: np.ndarray) -> float:
    triangles = np.asarray(triangles, dtype=np.float64)
    if len(triangles) == 0:
        return 0.0
    result = trimesh.triangles.normals(triangles)
    if isinstance(result, tuple):
        normals = np.asarray(result[0], dtype=np.float64)
    else:
        normals = np.asarray(result, dtype=np.float64)
    if normals.ndim != 2 or normals.shape[0] != len(triangles):
        return 0.0
    magnitude = np.linalg.norm(normals, axis=1)
    valid = np.isfinite(normals).all(axis=1) & (magnitude > 1e-12)
    return float(np.count_nonzero(valid) / len(normals))


def _connected_components(mesh: trimesh.Trimesh) -> int:
    if len(mesh.faces) == 0:
        return 0
    return len(trimesh.graph.connected_components(mesh.edges, min_len=1))


def _segments_intersect_triangle(segments: np.ndarray, tri: np.ndarray) -> np.ndarray:
    a = segments[:, 0]
    b = segments[:, 1]
    v0, v1, v2 = tri[0], tri[1], tri[2]
    e1 = v1 - v0
    e2 = v2 - v0
    direction = b - a
    pvec = np.cross(direction, e2)
    det = pvec @ e1
    tvec = a - v0
    inv_det = np.zeros_like(det)
    np.divide(1.0, det, out=inv_det, where=np.abs(det) > 1e-14)
    u = (tvec * pvec).sum(axis=1) * inv_det
    qvec = np.cross(tvec, e1)
    v = (direction * qvec).sum(axis=1) * inv_det
    t = (e2 * qvec).sum(axis=1) * inv_det
    hit = (
        (np.abs(det) > 1e-14)
        & (u >= -1e-12)
        & (v >= -1e-12)
        & (u + v <= 1 + 1e-12)
        & (t >= 0.0)
        & (t <= 1.0)
    )
    return hit


def _triangles_intersect(t0: np.ndarray, t1: np.ndarray) -> bool:
    seg0 = np.stack([
        [t0[0], t0[1]],
        [t0[1], t0[2]],
        [t0[2], t0[0]],
    ])
    seg1 = np.stack([
        [t1[0], t1[1]],
        [t1[1], t1[2]],
        [t1[2], t1[0]],
    ])
    if _segments_intersect_triangle(seg0, t1).any():
        return True
    if _segments_intersect_triangle(seg1, t0).any():
        return True
    return False


def _self_intersecting(mesh: trimesh.Trimesh) -> bool:
    faces = np.asarray(mesh.faces)
    if len(faces) < 2:
        return False
    triangles = np.asarray(mesh.triangles, dtype=np.float64)
    lower = triangles.min(axis=1)
    upper = triangles.max(axis=1)
    centroid = 0.5 * (lower + upper)
    radius = np.linalg.norm(upper - lower, axis=1) * 0.5

    from scipy.spatial import cKDTree

    tree = cKDTree(centroid)
    max_radius = float(radius.max())
    candidate_pairs: list[tuple[int, int]] = []
    vertex_sets: list[set[int]] = []
    for index in range(len(centroid)):
        neighbors = tree.query_ball_point(centroid[index], r=radius[index] + max_radius)
        for neighbor in neighbors:
            if neighbor <= index:
                continue
            vertex_sets.append({int(faces[index, 0]), int(faces[index, 1]), int(faces[index, 2]), int(faces[neighbor, 0]), int(faces[neighbor, 1]), int(faces[neighbor, 2])})
            candidate_pairs.append((index, neighbor))

    for (index, neighbor), shared_vertices in zip(candidate_pairs, vertex_sets):
        if len(shared_vertices) < 6:
            continue
        if _triangles_intersect(triangles[index], triangles[neighbor]):
            return True
    return False


def _points_triangles_sq(points: np.ndarray, tris: np.ndarray) -> np.ndarray:
    a = tris[:, 0]
    b = tris[:, 1]
    c = tris[:, 2]
    ab = b - a
    ac = c - a
    ap = points - a
    d1 = np.einsum("ij,ij->i", ap, ab)
    d2 = np.einsum("ij,ij->i", ap, ac)
    bp = points - b
    d3 = np.einsum("ij,ij->i", bp, ab)
    d4 = np.einsum("ij,ij->i", bp, ac)
    cp = points - c
    d5 = np.einsum("ij,ij->i", cp, ab)
    d6 = np.einsum("ij,ij->i", cp, ac)
    va = d3 * d6 - d5 * d4
    vb = d5 * d2 - d1 * d6
    vc = d1 * d4 - d3 * d2

    region_a = (d1 <= 0) & (d2 <= 0)
    region_b = (d3 >= 0) & (d4 <= d3)
    region_c = (d6 >= 0) & (d5 <= d6)
    region_ab = (vc <= 0) & (d1 >= 0) & (d3 <= 0)
    region_ac = (vb <= 0) & (d2 >= 0) & (d6 <= 0)
    region_bc = (va <= 0) & ((d4 - d3) >= 0) & ((d5 - d6) >= 0)

    result = np.zeros(len(points), dtype=np.float64)
    result[region_a] = np.einsum("ij,ij->i", ap[region_a], ap[region_a])
    result[region_b] = np.einsum("ij,ij->i", bp[region_b], bp[region_b])
    result[region_c] = np.einsum("ij,ij->i", cp[region_c], cp[region_c])

    v_ab = np.zeros(len(points))
    v_ab[region_ab] = d1[region_ab] / (d1[region_ab] - d3[region_ab])
    closest_ab = ap - v_ab[:, None] * ab
    result[region_ab] = np.einsum("ij,ij->i", closest_ab[region_ab], closest_ab[region_ab])

    w_ac = np.zeros(len(points))
    w_ac[region_ac] = d2[region_ac] / (d2[region_ac] - d6[region_ac])
    closest_ac = ap - w_ac[:, None] * ac
    result[region_ac] = np.einsum("ij,ij->i", closest_ac[region_ac], closest_ac[region_ac])

    bc = c - b
    w_bc = np.zeros(len(points))
    denom = (d4 - d3) + (d5 - d6)
    w_bc[region_bc] = (d4[region_bc] - d3[region_bc]) / np.where(denom[region_bc] == 0, 1.0, denom[region_bc])
    closest_bc = bp - w_bc[:, None] * bc
    result[region_bc] = np.einsum("ij,ij->i", closest_bc[region_bc], closest_bc[region_bc])

    interior = ~(region_a | region_b | region_c | region_ab | region_ac | region_bc)
    denom_face = va + vb + vc
    safe_denom = np.where(denom_face == 0, 1.0, denom_face)
    v_face = vb / safe_denom
    w_face = vc / safe_denom
    closest_face = ap - v_face[:, None] * ab - w_face[:, None] * ac
    result[interior] = np.einsum("ij,ij->i", closest_face[interior], closest_face[interior])

    np.maximum(result, 0.0, out=result)
    return result


def _nearest_triangle_distances(mesh: trimesh.Trimesh, points: np.ndarray, k: int = 8) -> np.ndarray:
    triangles = np.asarray(mesh.triangles, dtype=np.float64)
    centroids = triangles.mean(axis=1)
    from scipy.spatial import cKDTree

    tree = cKDTree(centroids)
    _, indices = tree.query(points, k=min(k, len(centroids)))
    if indices.ndim == 1:
        indices = indices[:, None]
    distances = np.full(len(points), np.inf, dtype=np.float64)
    for offset in range(indices.shape[1]):
        candidate_tris = triangles[indices[:, offset]]
        candidate = _points_triangles_sq(points, candidate_tris)
        distances = np.minimum(distances, candidate)
    return np.sqrt(distances)


def compute_mesh_quality(
    mesh: trimesh.Trimesh,
    source_points: np.ndarray | None = None,
    scene_diagonal: float | None = None,
    voxel_size: float | None = None,
    max_point_samples: int = 100_000,
) -> dict[str, int | float | str | bool | None]:
    stats: dict[str, int | float | str | bool | None] = {}

    faces = np.asarray(mesh.faces)
    vertices = np.asarray(mesh.vertices)
    stats["mesh_vertices"] = int(len(vertices))
    stats["mesh_triangles"] = int(len(faces))

    stats["connected_components"] = _connected_components(mesh)
    boundary, non_manifold = _edge_classification(faces)
    stats["boundary_edges"] = boundary
    stats["non_manifold_edges"] = non_manifold
    stats["degenerate_faces"] = _degenerate_faces(faces)
    stats["valid_normal_ratio"] = _valid_normal_ratio(mesh.triangles)

    try:
        stats["watertight"] = bool(mesh.is_watertight)
    except Exception:
        stats["watertight"] = None
    try:
        stats["winding_consistent"] = bool(mesh.is_winding_consistent)
    except Exception:
        stats["winding_consistent"] = None
    try:
        stats["euler_number"] = int(mesh.euler_number)
    except Exception:
        stats["euler_number"] = None

    if scene_diagonal and np.isfinite(scene_diagonal) and scene_diagonal > 0 and len(vertices):
        mesh_diagonal = float(np.linalg.norm(vertices.max(axis=0) - vertices.min(axis=0)))
        stats["bbox_ratio"] = mesh_diagonal / scene_diagonal

    entity_candidate = (
        stats.get("watertight") is True
        and stats.get("winding_consistent") is True
        and non_manifold == 0
        and boundary == 0
    )
    if entity_candidate and len(faces) <= MAX_SELF_INTERSECTION_FACES:
        try:
            stats["self_intersecting"] = _self_intersecting(mesh)
        except Exception:
            stats["self_intersecting"] = None
    else:
        stats["self_intersecting"] = None if entity_candidate else False

    if source_points is not None and len(source_points) and voxel_size and voxel_size > 0:
        points = np.asarray(source_points, dtype=np.float64)
        if len(points) > max_point_samples:
            points = points[np.linspace(0, len(points) - 1, max_point_samples).astype(int)]
        distances = _nearest_triangle_distances(mesh, points)
        stats["point_to_surface_p50"] = float(np.percentile(distances, 50))
        stats["point_to_surface_p95"] = float(np.percentile(distances, 95))
        stats["coverage"] = float(np.count_nonzero(distances <= 2.0 * voxel_size) / len(distances))

    entity_qualified = entity_candidate and stats.get("self_intersecting") is not True
    stats["entity_qualified"] = bool(entity_qualified)
    stats["surface_type"] = "entity" if entity_qualified else "surface"
    return stats
