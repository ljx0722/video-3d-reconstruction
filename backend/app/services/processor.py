import os
import json
import logging
import subprocess
import traceback
import tempfile
import glob

import numpy as np

logger = logging.getLogger(__name__)


def process_video_sync(job_id: str, upload_dir: str, db_url: str):
    try:
        _process_impl(job_id, upload_dir, db_url)
    except Exception as e:
        logger.error(f"Job {job_id} failed: {traceback.format_exc()}")
        _update_job(job_id, db_url, "failed", 0, error_message=str(e)[:500])


def _process_impl(job_id: str, upload_dir: str, db_url: str):
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
    t_start = __import__("time").time()

    _update_job(job_id, db_url, "processing", 0.02)

    # Extract frames using ffmpeg
    if not os.path.exists(video_path):
        mp4s = glob.glob(os.path.join(job_dir, "video.*"))
        if not mp4s:
            _update_job(job_id, db_url, "failed", 0, error_message="Video file not found")
            return
        video_path = mp4s[0]

    frames_dir = os.path.join(job_dir, "frames")
    os.makedirs(frames_dir, exist_ok=True)

    cmd = [
        "ffmpeg", "-y", "-i", video_path,
        "-vf", f"fps={fps},scale=160:120",
        "-q:v", "2",
        os.path.join(frames_dir, "%06d.jpg"),
    ]
    try:
        subprocess.run(cmd, capture_output=True, timeout=120, check=True)
    except subprocess.CalledProcessError as e:
        _update_job(job_id, db_url, "failed", 0, error_message=f"ffmpeg failed: {e.stderr.decode()[:200]}")
        return
    except FileNotFoundError:
        _update_job(job_id, db_url, "failed", 0, error_message="ffmpeg not installed on server")
        return

    frame_files = sorted(glob.glob(os.path.join(frames_dir, "*.jpg")))
    num_frames = len(frame_files)
    logger.info(f"Job {job_id}: {num_frames} frames extracted")

    if num_frames == 0:
        _update_job(job_id, db_url, "failed", 0, error_message="No frames could be extracted from video")
        return

    _update_job(job_id, db_url, "processing", 0.15)

    # Load frames as numpy arrays
    from PIL import Image
    frames_raw = [np.array(Image.open(f)) for f in frame_files]
    th, tw = frames_raw[0].shape[:2]

    # Build point cloud: arrange frames spiraling in 3D space
    all_vertices = []
    all_colors = []
    batch = max(1, num_frames // 10)

    for fi, frame in enumerate(frames_raw):
        if fi % batch == 0:
            pct = 0.15 + 0.55 * (fi / num_frames)
            _update_job(job_id, db_url, "processing", pct)

        angle = (fi / num_frames) * np.pi * 2 * 3
        radius = 3.0
        cx = radius * np.cos(angle)
        cz = radius * np.sin(angle)
        cy_off = fi * 0.01

        h, w = frame.shape[:2]
        ys = np.linspace(2, -2, h)[::3]
        xs = np.linspace(-1.5, 1.5, w)[::3]

        for yi, yv in enumerate(ys):
            for xi, xv in enumerate(xs):
                c = frame[yi * 3, xi * 3]
                if c[:3].sum() < 30:
                    continue
                all_vertices.append([cx + xv, cy_off + yv, cz])
                all_colors.append(c[:3])

    if not all_vertices:
        _update_job(job_id, db_url, "failed", 0, error_message="No valid points generated from video")
        return

    _update_job(job_id, db_url, "processing", 0.80)

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

    elapsed = __import__("time").time() - t_start
    _update_job(
        job_id, db_url, "completed", 1.0,
        num_frames=num_frames,
        num_points=len(vertices),
        processing_time_secs=elapsed,
        result_path=f"results/{job_id}/pointcloud.glb",
    )
    logger.info(f"Job {job_id} done: {len(vertices)} pts, {elapsed:.1f}s")


def _update_job(job_id, db_url, status, progress=0.0, **kwargs):
    import time as _time
    # Map column names that might differ
    field_renames = {"error_message": "error_message"}
    try:
        from sqlalchemy import create_engine, text
        url = db_url
        if "aiosqlite" in url:
            url = "sqlite:///" + url.split("///")[-1] if "///" in url else db_url.replace("sqlite+aiosqlite://", "sqlite:///")
        elif "asyncpg" in url:
            url = url.replace("+asyncpg", "")

        engine = create_engine(url)
        with engine.connect() as conn:
            fields = ["status", "progress"]
            vals = {"status": status, "progress": progress}
            for k, v in kwargs.items():
                if v is not None and k in ("num_frames", "num_points", "processing_time_secs", "result_path", "error_message"):
                    fields.append(k)
                    vals[k] = v
            sets = ", ".join(f"{f} = :{f}" for f in fields)
            sql = text(f"UPDATE jobs SET {sets} WHERE id = :job_id")
            vals["job_id"] = job_id
            conn.execute(sql, vals)
            conn.commit()
        engine.dispose()
    except Exception as e:
        logger.error(f"DB update failed for job {job_id}: {e}")
