import os
import json
import logging
import traceback
import time as time_module

import numpy as np

logger = logging.getLogger(__name__)


def process_video_sync(job_id: str, upload_dir: str, db_url: str):
    """Synchronous CPU-based video processing, runs in a background thread."""
    try:
        _process_impl(job_id, upload_dir, db_url)
    except Exception as e:
        logger.error(f"Job {job_id} failed: {traceback.format_exc()}")
        _update_job_sync(job_id, db_url, "failed", 0, error=str(e)[:500])


def _process_impl(job_id: str, upload_dir: str, db_url: str):
    import cv2
    import trimesh

    job_dir = os.path.join(upload_dir, job_id)
    video_path = os.path.join(job_dir, "video.mp4")
    settings_path = os.path.join(job_dir, "settings.json")
    glb_path = os.path.join(job_dir, "result.glb")

    settings = {"fps": 10}
    if os.path.exists(settings_path):
        with open(settings_path, "r") as f:
            settings.update(json.load(f))

    fps = settings.get("fps", 10)
    t_start = time_module.time()

    _update_job_sync(job_id, db_url, "processing", 0.02)

    # Extract frames
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        _update_job_sync(job_id, db_url, "failed", 0, error="Cannot open video file")
        return

    src_fps = cap.get(cv2.CAP_PROP_FPS) or 30
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    interval = max(1, round(src_fps / fps))
    frames = []
    idx = 0
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        if idx % interval == 0:
            frames.append(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        idx += 1
    cap.release()

    num_frames = len(frames)
    logger.info(f"Job {job_id}: {num_frames} frames at {fps} fps")
    if num_frames == 0:
        _update_job_sync(job_id, db_url, "failed", 0, error="No frames extracted from video")
        return

    _update_job_sync(job_id, db_url, "processing", 0.15)

    # Build spatial point cloud from frames
    th, tw = 120, 160
    all_vertices = []
    all_colors = []
    batch = max(1, num_frames // 10)

    for fi, frame in enumerate(frames):
        if fi % batch == 0:
            pct = 0.15 + 0.55 * (fi / num_frames)
            _update_job_sync(job_id, db_url, "processing", pct)

        small = cv2.resize(frame, (tw, th))
        h, w = small.shape[:2]

        angle = (fi / num_frames) * np.pi * 2 * 3
        radius = 3.0
        cx = radius * np.cos(angle)
        cz = radius * np.sin(angle)
        cy_off = fi * 0.01

        ys = np.linspace(2, -2, h)[::2]
        xs = np.linspace(-1.5, 1.5, w)[::2]

        for yi, yv in enumerate(ys):
            for xi, xv in enumerate(xs):
                c = small[yi * 2, xi * 2]
                if c.sum() < 30:
                    continue
                px = cx + xv
                py = cy_off + yv
                pz = cz
                all_vertices.append([px, py, pz])
                all_colors.append(c)

    if not all_vertices:
        _update_job_sync(job_id, db_url, "failed", 0, error="No valid points generated")
        return

    _update_job_sync(job_id, db_url, "processing", 0.80)

    vertices = np.array(all_vertices, dtype=np.float32)
    colors = np.array(all_colors, dtype=np.uint8)

    max_pts = 500000
    if len(vertices) > max_pts:
        idxs = np.random.choice(len(vertices), max_pts, replace=False)
        vertices = vertices[idxs]
        colors = colors[idxs]

    scene = trimesh.Scene()
    pc = trimesh.PointCloud(vertices=vertices, colors=colors)
    scene.add_geometry(pc)
    centroid = vertices.mean(axis=0)
    scene.apply_translation(-centroid)
    scene.export(glb_path)

    elapsed = time_module.time() - t_start
    _update_job_sync(
        job_id, db_url, "completed", 1.0,
        num_frames=num_frames,
        num_points=len(vertices),
        processing_time_secs=elapsed,
        result_path=f"results/{job_id}/pointcloud.glb",
    )
    logger.info(f"Job {job_id} done: {len(vertices)} pts, {elapsed:.1f}s")


def _update_job_sync(job_id: str, db_url: str, status: str, progress: float = 0.0, **kwargs):
    from sqlalchemy import create_engine, text
    import time as _time
    try:
        url = db_url
        if url.startswith("sqlite+aiosqlite"):
            url = "sqlite:///" + url.split("///")[-1] if "///" in url else url.replace("sqlite+aiosqlite://", "sqlite:///")
        elif url.startswith("postgresql+asyncpg"):
            url = url.replace("+asyncpg", "+psycopg2")
        engine = create_engine(url)
        with engine.connect() as conn:
            fields = ["status", "progress", "updated_at"]
            vals = {"status": status, "progress": progress, "updated_at": _time.strftime("%Y-%m-%d %H:%M:%S")}
            for k, v in kwargs.items():
                if v is not None:
                    fields.append(k)
                    vals[k] = v
            sets = ", ".join(f"{k} = :{k}" for k in fields)
            sql = text(f"UPDATE jobs SET {sets} WHERE id = :job_id")
            vals["job_id"] = job_id
            conn.execute(sql, vals)
            conn.commit()
        engine.dispose()
    except Exception as e:
        logger.error(f"DB update failed for job {job_id}: {e}")
