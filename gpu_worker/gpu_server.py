"""
GPU Worker server for lingbot-map. Runs on AutoDL GPU instance.
Polls Sealos backend for pending jobs, downloads videos, runs inference,
uploads GLB results back.

Usage:
    SEALOS_BACKEND_URL=https://video2gauss.sealoshzh.site python gpu_server.py
"""

import os
import sys
import time
import json
import tempfile
import logging
import urllib.request
import urllib.error

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("gpu-worker")

BACKEND_URL = os.environ.get("SEALOS_BACKEND_URL", "https://video2gauss.sealoshzh.site").rstrip("/")
POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL", "5"))
CHECKPOINT_PATH = os.environ.get("MODEL_PATH", "./checkpoint/lingbot-map-long.pt")

# ── Model loading (lazy, loaded on first request) ──────────────────────────
_model = None
_device = None
_dtype = None


def load_model():
    global _model, _device, _dtype
    if _model is not None:
        return

    os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")
    os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
    import torch

    _device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    if torch.cuda.is_available():
        cap = torch.cuda.get_device_capability()[0]
        _dtype = torch.bfloat16 if cap >= 8 else torch.float16
    else:
        _dtype = torch.float32

    from lingbot_map.models.gct_stream import GCTStream

    logger.info("Building GCTStream model...")
    _model = GCTStream(
        img_size=518, patch_size=14,
        enable_3d_rope=True, max_frame_num=1024,
        kv_cache_sliding_window=64, kv_cache_scale_frames=8,
        kv_cache_cross_frame_special=True, kv_cache_include_scale_frames=True,
        use_sdpa=True, camera_num_iterations=4,
    )

    ckpt_path = _find_checkpoint()
    logger.info(f"Loading checkpoint: {ckpt_path}")
    ckpt = torch.load(ckpt_path, map_location=_device, weights_only=False)
    state_dict = ckpt.get("model", ckpt)
    _model.load_state_dict(state_dict, strict=False)
    _model = _model.to(_device).eval()

    if _dtype != torch.float32 and hasattr(_model, "aggregator"):
        _model.aggregator = _model.aggregator.to(dtype=_dtype)

    if torch.cuda.is_available():
        torch.cuda.empty_cache()
        logger.info(f"GPU mem: {torch.cuda.memory_allocated()/1e9:.2f} GB")


def _find_checkpoint():
    """Find the checkpoint file."""
    if os.path.isfile(CHECKPOINT_PATH):
        return CHECKPOINT_PATH
    # Check common locations
    for path in [
        "./checkpoint/lingbot-map.pt",
        "./checkpoint/model.pt",
        "./lingbot-map/checkpoint/lingbot-map.pt",
        "/root/autodl-tmp/checkpoint/lingbot-map.pt",
        "/root/autodl-fs/checkpoint/lingbot-map.pt",
    ]:
        if os.path.isfile(path):
            return path
    raise FileNotFoundError(f"Checkpoint not found at {CHECKPOINT_PATH}")


# ── Inference pipeline ──────────────────────────────────────────────────────
def process_video(video_path: str, settings: dict) -> str:
    """Run lingbot-map inference and export GLB. Returns GLB file path."""
    import torch
    import cv2
    import numpy as np
    from lingbot_map.utils.load_fn import load_and_preprocess_images
    from lingbot_map.utils.pose_enc import pose_encoding_to_extri_intri
    from lingbot_map.utils.geometry import closed_form_inverse_se3_general

    load_model()

    fps = settings.get("fps", 10)
    mode = settings.get("mode", "streaming")
    conf_threshold = settings.get("conf_threshold", 1.5)

    # Extract frames
    cap = cv2.VideoCapture(video_path)
    src_fps = cap.get(cv2.CAP_PROP_FPS) or 30
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    interval = max(1, round(src_fps / fps))

    tmpdir = tempfile.mkdtemp()
    frame_paths = []
    idx = 0
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        if idx % interval == 0:
            p = os.path.join(tmpdir, f"{len(frame_paths):06d}.jpg")
            cv2.imwrite(p, frame)
            frame_paths.append(p)
        idx += 1
    cap.release()

    num_frames = len(frame_paths)
    logger.info(f"Extracted {num_frames} frames (total={total_frames}, interval={interval})")

    # Preprocess
    images = load_and_preprocess_images(frame_paths, mode="crop", image_size=518, patch_size=14)
    images = images.to(_device)

    num_scale_frames = min(8, num_frames)
    if num_scale_frames >= num_frames:
        num_scale_frames = max(1, num_frames - 1)

    kf_interval = 1
    if mode == "streaming" and num_frames > 320:
        kf_interval = (num_frames + 319) // 320

    # Inference
    logger.info(f"Inference: {num_frames} frames, scale={num_scale_frames}, kf={kf_interval}")
    t0 = time.time()

    with torch.no_grad(), torch.amp.autocast("cuda", dtype=_dtype):
        if mode == "streaming":
            predictions = _model.inference_streaming(
                images, num_scale_frames=num_scale_frames, keyframe_interval=kf_interval
            )
        else:
            predictions = _model.inference_windowed(
                images, window_size=64, overlap_size=16, num_scale_frames=num_scale_frames
            )

    elapsed = time.time() - t0
    logger.info(f"Inference done in {elapsed:.1f}s")

    if torch.cuda.is_available():
        logger.info(f"GPU peak: {torch.cuda.max_memory_allocated()/1e9:.2f} GB")

    # Postprocess
    extrinsic, intrinsic = pose_encoding_to_extri_intri(predictions["pose_enc"], images.shape[-2:])
    ext_4x4 = torch.zeros((*extrinsic.shape[:-2], 4, 4), device=extrinsic.device, dtype=extrinsic.dtype)
    ext_4x4[..., :3, :4] = extrinsic
    ext_4x4[..., 3, 3] = 1.0
    ext_4x4 = closed_form_inverse_se3_general(ext_4x4)  # c2w
    extrinsic = ext_4x4[..., :3, :4]  # (B, S, 3, 4)

    predictions["extrinsic"] = extrinsic
    predictions["intrinsic"] = intrinsic

    # Compute world_points_from_depth (needed for GLB export)
    if "world_points" not in predictions and "depth" in predictions:
        logger.info("Computing world_points_from_depth...")
        depth_t = predictions["depth"]
        if depth_t.ndim == 5:
            depth_t = depth_t[0]  # (S, H, W, 1)
        S = depth_t.shape[0]

        intr = predictions["intrinsic"]
        if intr.ndim == 4: intr = intr[0]
        ext_t = predictions["extrinsic"]
        if ext_t.ndim == 4: ext_t = ext_t[0]

        # Subsampled resolution: 2x (doubles point density vs 3x)
        skip = 2

        world_pts_dense = []
        for si in range(S):
            d = depth_t[si, ::skip, ::skip, 0]
            h_act, w_act = d.shape
            fx = intr[si, 0, 0].item()
            fy = intr[si, 1, 1].item()
            ppx = intr[si, 0, 2].item()
            ppy = intr[si, 1, 2].item()

            yy, xx = torch.meshgrid(
                torch.arange(h_act, device=depth_t.device),
                torch.arange(w_act, device=depth_t.device),
                indexing="ij",
            )
            px = xx.float() * skip + skip / 2
            py = yy.float() * skip + skip / 2

            z = d
            valid = z > 0.05
            z = torch.where(valid, z, torch.zeros_like(z))

            x = (px - ppx) * z / fx
            y = (py - ppy) * z / fy

            pts_cam = torch.stack([x, y, z], dim=-1)
            R = ext_t[si, :, :3]
            T = ext_t[si, :, 3]
            pts_w = pts_cam.reshape(-1, 3) @ R.T + T
            world_pts_dense.append(pts_w.reshape(h_act, w_act, 3))

        predictions["world_points_from_depth"] = torch.stack(world_pts_dense, dim=0).unsqueeze(0)
        predictions["depth_conf"] = depth_t[:, ::skip, ::skip, 0]
        logger.info(f"world_points_from_depth: {S}x{h_act}x{w_act}")

    # Move to CPU and convert to numpy
    vis_pred = {}
    for k, v in predictions.items():
        if isinstance(v, torch.Tensor):
            v_np = v.cpu().numpy()
            if v_np.ndim >= 3 and v_np.shape[0] == 1:
                v_np = v_np[0]
            vis_pred[k] = v_np
        elif isinstance(v, np.ndarray):
            vis_pred[k] = v
        else:
            vis_pred[k] = v

    # Keep images at full resolution for GLB color extraction
    imgs_t = images
    if imgs_t.ndim == 5 and imgs_t.shape[0] == 1:
        imgs_t = imgs_t[0]
    # images format: (S, 3, H, W) for CHW, or (S, H, W, 3) for HWC
    if imgs_t.shape[1] == 3:
        imgs_np = imgs_t.cpu().numpy()  # (S, 3, 518, 378)
        vis_pred["images"] = imgs_np  # Keep as (S, 3, H, W)
    else:
        # (S, H, W, 3) -> (S, 3, H, W)
        imgs_np = imgs_t.permute(0, 3, 1, 2).cpu().numpy()
        vis_pred["images"] = imgs_np

    del images, predictions
    if torch.cuda.is_available():
        torch.cuda.empty_cache()

    # Build GLB: voxel-merge, confidence filter, camera trail
    import trimesh

    # Downsample images to match world_points (skip=2)
    imgs_full = vis_pred["images"]  # (S, 3, 518, 378)
    imgs_ds = imgs_full[:, :, ::skip, ::skip]  # (S, 3, 259, 189)
    imgs_hwc = imgs_ds.transpose(0, 2, 3, 1)  # (S, 259, 189, 3)

    # Use depth confidence to filter (top 30% most confident pixels)
    depth_conf = vis_pred.get("depth_conf")  # (S, h_act, w_act)
    logger.info(f"depth_conf shape: {depth_conf.shape if depth_conf is not None else 'N/A'}")

    # Take ~20 well-spaced keyframes for clean reconstruction
    step = max(1, num_frames // 20)
    indices = list(range(0, num_frames, step))
    logger.info(f"Keyframes: {num_frames} -> {len(indices)} (step={step})")

    # Collect camera positions from extrinsic (S, 3, 4) = c2w
    camera_positions = []
    ext_data = vis_pred.get("extrinsic")
    if ext_data is not None and ext_data.ndim >= 2:
        for fi in range(num_frames):
            # ext is (S, 3, 4): translation in column 3
            camera_positions.append(ext_data[fi, :, 3].copy())

    # Build per-frame point cloud with confidence filtering
    all_verts = []
    all_cols = []
    for fi in indices:
        pts_w = vis_pred["world_points_from_depth"][fi]  # (h_act, w_act, 3)
        h_a, w_a = pts_w.shape[:2]
        verts = pts_w.reshape(-1, 3)
        # Get colors (match resolution)
        cols = imgs_hwc[fi].reshape(-1, 3)

        # Depth filter
        valid_z = (verts[:, 2] > 0.1) & (verts[:, 2] < 80)

        # Confidence filter (keep top 40% confident pixels)
        if depth_conf is not None:
            cf_frame = depth_conf[fi].reshape(-1)
            cf_thres = np.percentile(cf_frame[cf_frame > 0], 40) if (cf_frame > 0).any() else 0
            valid = valid_z & (cf_frame > cf_thres)
        else:
            valid = valid_z

        verts = verts[valid]
        cols = cols[valid]
        if len(verts) > 0:
            all_verts.append(verts)
            all_cols.append(cols)

    if not all_verts:
        raise ValueError("No valid points after filtering")

    vertices = np.concatenate(all_verts, axis=0)
    colors = np.concatenate(all_cols, axis=0)
    logger.info(f"Before voxel merge: {len(vertices)} points")

    # Voxel merge: average overlapping points
    voxel_size = 0.015
    if len(vertices) > 0:
        vk = np.floor(vertices / voxel_size).astype(np.int32)
        vd: dict = {}
        for i in range(len(vertices)):
            k = (vk[i, 0], vk[i, 1], vk[i, 2])
            if k not in vd:
                vd[k] = {"p": [0.0, 0.0, 0.0], "c": [0.0, 0.0, 0.0], "n": 0}
            v = vd[k]
            v["p"][0] += float(vertices[i, 0]); v["p"][1] += float(vertices[i, 1]); v["p"][2] += float(vertices[i, 2])
            v["c"][0] += float(colors[i, 0]); v["c"][1] += float(colors[i, 1]); v["c"][2] += float(colors[i, 2])
            v["n"] += 1
        nv = len(vd)
        vm = np.zeros((nv, 3), dtype=np.float32)
        cm = np.zeros((nv, 3), dtype=np.float32)
        for i, v in enumerate(vd.values()):
            vm[i] = [v["p"][0]/v["n"], v["p"][1]/v["n"], v["p"][2]/v["n"]]
            cm[i] = [v["c"][0]/v["n"], v["c"][1]/v["n"], v["c"][2]/v["n"]]
        vertices = vm
        colors = cm
        logger.info(f"After voxel merge: {len(vertices)} points")

    # Cap
    if len(vertices) > 1500000:
        idx = np.random.choice(len(vertices), 1500000, replace=False)
        vertices = vertices[idx]
        colors = colors[idx]

    # Build trimesh scene
    scene = trimesh.Scene()
    pc = trimesh.PointCloud(vertices=vertices, colors=colors)
    scene.add_geometry(pc)

    # Camera trail
    if len(camera_positions) > 0:
        cam_verts = np.array(camera_positions)
        cs = max(1, len(cam_verts) // 20)
        cvd = cam_verts[::cs]
        for i, cp in enumerate(cvd):
            s = trimesh.creation.icosphere(subdivisions=2, radius=0.015)
            t = i / max(1, len(cvd) - 1)
            s.visual.vertex_colors = np.tile([int(255*(1-t)), 50, int(255*t)], (len(s.vertices), 1)).astype(np.uint8)
            s.apply_translation(cp.tolist())
            scene.add_geometry(s)

    centroid = vertices.mean(axis=0)
    scene.apply_translation(-centroid)

    glb_path = os.path.join(tmpdir, "output.glb")
    scene.export(glb_path)

    size_mb = os.path.getsize(glb_path) / (1024 * 1024)
    logger.info(f"GLB exported: {size_mb:.1f} MB, {num_frames} frames, elapsed={elapsed:.1f}s")

    return glb_path


# ── Job polling loop ────────────────────────────────────────────────────────
def poll_and_process():
    """Main loop: poll for pending jobs, process them, upload results."""
    logger.info(f"GPU Worker starting, backend={BACKEND_URL}")

    # Check cp exists (model loaded lazily on first job)
    _find_checkpoint()
    logger.info("GPU Worker ready, polling for jobs...")

    while True:
        try:
            # Get pending jobs from backend
            req = urllib.request.Request(
                f"{BACKEND_URL}/api/v1/gpu/pending",
                headers={"User-Agent": "gpu-worker/1.0"},
            )
            resp = urllib.request.urlopen(req, timeout=10)
            jobs = json.loads(resp.read())
        except Exception as e:
            logger.warning(f"Failed to poll pending jobs: {e}")
            time.sleep(POLL_INTERVAL)
            continue

        if not jobs:
            time.sleep(POLL_INTERVAL)
            continue

        for job in jobs:
            job_id = job["id"]
            logger.info(f"Processing job {job_id}...")

            try:
                # Download video
                video_req = urllib.request.Request(
                    f"{BACKEND_URL}/api/v1/gpu/video/{job_id}",
                    headers={"User-Agent": "gpu-worker/1.0"},
                )
                video_resp = urllib.request.urlopen(video_req, timeout=60)
                video_data = video_resp.read()

                with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
                    f.write(video_data)
                    video_tmp = f.name

                # Get settings
                settings = job.get("settings", {"fps": 10, "mode": "streaming", "conf_threshold": 1.5})
                if isinstance(settings, str):
                    settings = json.loads(settings)

                # Update status to processing
                _update_status(job_id, "processing", 0.1)

                # Run inference
                glb_path = process_video(video_tmp, settings)
                os.unlink(video_tmp)

                # Upload GLB result
                with open(glb_path, "rb") as f:
                    glb_data = f.read()

                _update_status(job_id, "processing", 0.9)
                _upload_result(job_id, glb_data)

                # Clean up
                os.unlink(glb_path)
                logger.info(f"Job {job_id} completed ({len(glb_data)/1024/1024:.1f} MB)")

            except Exception as e:
                logger.exception(f"Job {job_id} failed")
                try:
                    _update_status(job_id, "failed", 0, error=str(e)[:500])
                except Exception:
                    pass

        time.sleep(POLL_INTERVAL)


def _update_status(job_id: str, status: str, progress: float, error: str = ""):
    data = json.dumps({"status": status, "progress": progress, "error_message": error}).encode()
    req = urllib.request.Request(
        f"{BACKEND_URL}/api/v1/gpu/status/{job_id}",
        data=data,
        headers={"Content-Type": "application/json", "User-Agent": "gpu-worker/1.0"},
        method="POST",
    )
    urllib.request.urlopen(req, timeout=10)


def _upload_result(job_id: str, glb_data: bytes):
    # Upload as raw binary (not multipart) for reliability with large files
    for attempt in range(3):
        try:
            req = urllib.request.Request(
                f"{BACKEND_URL}/api/v1/gpu/result/{job_id}",
                data=glb_data,
                headers={
                    "Content-Type": "application/octet-stream",
                    "User-Agent": "gpu-worker/1.0",
                },
                method="POST",
            )
            urllib.request.urlopen(req, timeout=300)
            return
        except Exception as e:
            if attempt < 2:
                logger.warning(f"Upload attempt {attempt+1} failed, retrying: {e}")
                time.sleep(5)
            else:
                raise


if __name__ == "__main__":
    poll_and_process()
