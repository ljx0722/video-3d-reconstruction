import os
import logging
import json
import asyncio

import cv2
import numpy as np

logger = logging.getLogger(__name__)


async def process_video(job_id: str, upload_dir: str, db_session_factory):
    """Process a video file into a GLB point cloud (CPU-based).

    Extracts frames, creates a spatial point cloud from video pixels,
    exports as GLB, and updates job status in DB.
    """
    try:
        await _process_video_impl(job_id, upload_dir, db_session_factory)
    except Exception as e:
        logger.exception(f"Job {job_id} failed")
        await _update_job(db_session_factory, job_id, "failed", 0, error=str(e))


async def _process_video_impl(job_id: str, upload_dir: str, db_session_factory):
    import trimesh


async def _process_video_impl(job_id: str, upload_dir: str, db_session_factory):
    job_dir = os.path.join(upload_dir, job_id)
    video_path = os.path.join(job_dir, "video.mp4")
    settings_path = os.path.join(job_dir, "settings.json")
    glb_path = os.path.join(job_dir, "result.glb")

    # Read settings
    settings = {"fps": 10, "mode": "streaming", "conf_threshold": 1.5}
    if os.path.exists(settings_path):
        with open(settings_path) as f:
            settings.update(json.load(f))

    fps = settings.get("fps", 10)

    # Update job: processing
    await _update_job(db_session_factory, job_id, "processing", 0.05)

    # Extract frames
    cap = cv2.VideoCapture(video_path)
    src_fps = cap.get(cv2.CAP_PROP_FPS) or 30
    interval = max(1, round(src_fps / fps))
    frames = []
    idx = 0
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        if idx % interval == 0:
            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            frames.append(frame_rgb)
        idx += 1
    cap.release()

    if not frames:
        await _update_job(db_session_factory, job_id, "failed", 0, error="Video has no readable frames")
        return

    num_frames = len(frames)
    logger.info(f"Processing job {job_id}: {num_frames} frames at {fps} fps")

    await _update_job(db_session_factory, job_id, "processing", 0.15)

    # Downscale frames and build spatial point cloud
    target_h, target_w = 120, 160  # Small for reasonable point count
    scale_x, scale_y = 0.05, 0.05  # Spatial scaling per pixel

    all_colors = []
    all_points = []

    await _update_job(db_session_factory, job_id, "processing", 0.25)

    # Process frames in batches for progress
    batch_size = max(1, num_frames // 10)
    for fi, frame in enumerate(frames):
        if fi % batch_size == 0:
            pct = 0.25 + 0.50 * (fi / num_frames)
            await _update_job(db_session_factory, job_id, "processing", pct)

        small = cv2.resize(frame, (target_w, target_h))
        h, w = small.shape[:2]

        # Arrange each frame as a vertical "slice" in 3D space
        # Create a cylindrical layout: frames go around in a circle
        angle = (fi / num_frames) * 2 * np.pi * 3  # 3 full rotations
        radius = 3.0
        cx = radius * np.cos(angle)
        cz = radius * np.sin(angle)
        cy_offset = fi * 0.01  # Slight upward progression

        # Generate yx grid
        y_coords = np.linspace(2, -2, h)
        x_coords = np.linspace(-1.5, 1.5, w)

        # Create points for this frame: spread outward from the frame center
        for y_i in range(0, h, 2):  # Skip every other row for density control
            for x_i in range(0, w, 2):
                color = small[y_i, x_i]
                # Skip very dark pixels (background)
                if color.sum() < 30:
                    continue
                # Point position relative to frame center
                px = cx + x_coords[x_i]
                py = cy_offset + y_coords[y_i]
                pz = cz + x_coords[x_i] * 0.3
                all_points.append([px, py, pz])
                all_colors.append(color)

    if not all_points:
        await _update_job(db_session_factory, job_id, "failed", 0, error="No valid points generated")
        return

    await _update_job(db_session_factory, job_id, "processing", 0.80)

    # Build GLB
    vertices = np.array(all_points, dtype=np.float32)
    colors = np.array(all_colors, dtype=np.uint8)

    # Sample to keep point count reasonable (~500K max)
    max_points = 500000
    if len(vertices) > max_points:
        indices = np.random.choice(len(vertices), max_points, replace=False)
        vertices = vertices[indices]
        colors = colors[indices]

    scene = trimesh.Scene()
    pc = trimesh.PointCloud(vertices=vertices, colors=colors)
    scene.add_geometry(pc)

    # Align: center the cloud
    centroid = vertices.mean(axis=0)
    scene.apply_translation(-centroid)

    scene.export(glb_path)
    glb_size = os.path.getsize(glb_path) / (1024 * 1024)

    await _update_job(db_session_factory, job_id, "processing", 0.95)

    # Update job to completed
    await _update_job(
        db_session_factory,
        job_id,
        "completed",
        1.0,
        num_frames=num_frames,
        num_points=len(vertices),
        result_path=f"results/{job_id}/pointcloud.glb",
    )

    logger.info(f"Job {job_id} completed: {len(vertices)} points, GLB {glb_size:.1f} MB")


async def _update_job(db_session_factory, job_id, status, progress=0.0, **kwargs):
    """Update job record in the database."""
    from app.models.job import Job
    from sqlalchemy import select
    import time

    try:
        async with db_session_factory() as session:
            result = await session.execute(select(Job).where(Job.id == job_id))
            job = result.scalar_one_or_none()
            if job:
                job.status = status
                job.progress = progress
                for k, v in kwargs.items():
                    if v is not None and hasattr(job, k):
                        setattr(job, k, v)
                await session.commit()
    except Exception as e:
        logger.error(f"Failed to update job {job_id}: {e}")
