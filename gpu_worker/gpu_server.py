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
    """Run lingbot-map inference and export GLB following demo.py pipeline exactly."""
    import torch
    import cv2
    import numpy as np
    from lingbot_map.utils.load_fn import load_and_preprocess_images
    from lingbot_map.utils.pose_enc import pose_encoding_to_extri_intri
    from lingbot_map.utils.geometry import closed_form_inverse_se3_general
    import trimesh

    load_model()

    fps = settings.get("fps", 10)
    mode = settings.get("mode", "streaming")

    # ── Extract frames ─────────────────────────────────────────────────
    cap = cv2.VideoCapture(video_path)
    src_fps = cap.get(cv2.CAP_PROP_FPS) or 30
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    interval = max(1, round(src_fps / fps))

    tmpdir = tempfile.mkdtemp()
    frame_paths = []
    idx = 0
    while True:
        ret, frame = cap.read()
        if not ret: break
        if idx % interval == 0:
            p = os.path.join(tmpdir, f"{len(frame_paths):06d}.jpg")
            cv2.imwrite(p, frame)
            frame_paths.append(p)
        idx += 1
    cap.release()

    num_frames = len(frame_paths)
    logger.info(f"Extracted {num_frames} frames (total={total_frames}, interval={interval})")

    # ── Preprocess (exactly as demo.py) ─────────────────────────────────
    images = load_and_preprocess_images(frame_paths, mode="crop", image_size=518, patch_size=14)
    images = images.to(_device)

    num_scale_frames = min(8, num_frames)
    if num_scale_frames >= num_frames:
        num_scale_frames = max(1, num_frames - 1)

    kf_interval = 1
    if mode == "streaming" and num_frames > 320:
        kf_interval = (num_frames + 319) // 320

    # ── Inference (exactly as demo.py) ──────────────────────────────────
    logger.info(f"Inference: {num_frames} frames, scale={num_scale_frames}, kf={kf_interval}")
    t0 = time.time()

    with torch.no_grad(), torch.amp.autocast("cuda", dtype=_dtype):
        if mode == "streaming":
            predictions = _model.inference_streaming(
                images, num_scale_frames=num_scale_frames, keyframe_interval=kf_interval,
            )
        else:
            predictions = _model.inference_windowed(
                images, window_size=64, overlap_size=16, num_scale_frames=num_scale_frames,
            )

    elapsed = time.time() - t0
    logger.info(f"Inference done in {elapsed:.1f}s")
    if torch.cuda.is_available():
        logger.info(f"GPU peak: {torch.cuda.max_memory_allocated()/1e9:.2f} GB")

    # ── Postprocess (exactly as demo.py) ────────────────────────────────
    # Convert pose encoding to extrinsic/intrinsic
    extrinsic, intrinsic = pose_encoding_to_extri_intri(predictions["pose_enc"], images.shape[-2:])
    # w2c → c2w
    ext_4x4 = torch.zeros((*extrinsic.shape[:-2], 4, 4), device=extrinsic.device, dtype=extrinsic.dtype)
    ext_4x4[..., :3, :4] = extrinsic
    ext_4x4[..., 3, 3] = 1.0
    ext_4x4 = closed_form_inverse_se3_general(ext_4x4)
    extrinsic = ext_4x4[..., :3, :4]
    predictions["extrinsic"] = extrinsic
    predictions["intrinsic"] = intrinsic

    # Remove batch dimension and move to CPU (demo.py postprocess)
    _BATCHED_NDIMS = {"pose_enc": 3, "depth": 5, "depth_conf": 4, "world_points": 5, "world_points_conf": 4, "extrinsic": 4, "intrinsic": 4, "images": 5}
    def _squeeze(k, v):
        nd = _BATCHED_NDIMS.get(k)
        if nd is None or not hasattr(v, "ndim"): return v
        if v.ndim == nd and v.shape[0] == 1: return v[0]
        return v

    logger.info("Moving results to CPU...")
    for k in list(predictions.keys()):
        if isinstance(predictions[k], torch.Tensor):
            predictions[k] = _squeeze(k, predictions[k].to("cpu", non_blocking=True))
    images_cpu = images.to("cpu", non_blocking=True)
    if torch.cuda.is_available():
        torch.cuda.synchronize()

    predictions.pop("pose_enc_list", None)
    predictions.pop("images", None)
    del images
    if torch.cuda.is_available():
        torch.cuda.empty_cache()

    # ── Prepare for visualization (exactly as demo.py prepare_for_visualization) ──
    vis_pred = {}
    for k, v in predictions.items():
        if isinstance(v, torch.Tensor):
            v_np = _squeeze(k, v.detach().cpu()).numpy() if v.ndim >= 1 else v.numpy()
        elif isinstance(v, np.ndarray):
            v_np = _squeeze(k, v)
        else:
            v_np = v
        vis_pred[k] = v_np

    imgs_np = images_cpu
    if isinstance(imgs_np, torch.Tensor):
        imgs_np = imgs_np.detach().cpu().numpy()
    vis_pred["images"] = imgs_np

    # ── Compute world_points_from_depth (standard method) ───────────────
    if "world_points" not in vis_pred:
        logger.info("Computing world_points_from_depth...")
        depth = vis_pred["depth"]
        extrinsics = vis_pred["extrinsic"]
        intrinsics = vis_pred.get("intrinsic")
        depth_conf_data = vis_pred.get("depth_conf")

        S, H, W = depth.shape[0], depth.shape[1], depth.shape[2]

        # Take ~30 well-spaced keyframes
        keyframe_step = max(1, S // 30)
        keyframe_idx = list(range(0, S, keyframe_step))
        n_keyframes = len(keyframe_idx)
        logger.info(f"Keyframes: {S} -> {n_keyframes}")

        all_world_pts = []
        all_colors_list = []
        all_conf_list = []  # per-point confidence for winner-take-all voxel merge

        for fi in keyframe_idx:
            ext = extrinsics[fi]; R, T = ext[:, :3], ext[:, 3]
            d = depth[fi, :, :, 0]
            intr = intrinsics[fi] if intrinsics.ndim >= 3 else intrinsics
            fx, fy = intr[0, 0], intr[1, 1]
            cx, cy = intr[0, 2], intr[1, 2]

            yy, xx = np.mgrid[0:H, 0:W]
            z = d
            x_cam = (xx - cx) * z / fx
            y_cam = (yy - cy) * z / fy
            pts_cam = np.stack([x_cam, y_cam, z], axis=-1)
            pts_w = pts_cam @ R.T + T

            # Get colors
            img = vis_pred["images"]
            img_f = img[fi].transpose(1, 2, 0) if img.shape[1] == 3 else img[fi]

            # Depth validity
            valid = (z > 0.1) & (z < 80)

            # Confidence per-pixel (for winner-take-all, NOT hard threshold)
            if depth_conf_data is not None:
                cf = depth_conf_data[fi]
                cf_valid = cf[valid]  # (N,) confidence scores for valid pixels
            else:
                cf_valid = np.ones(int(valid.sum()), dtype=np.float32)

            all_world_pts.append(pts_w[valid])
            all_colors_list.append((img_f[valid] * 255).astype(np.uint8))
            all_conf_list.append(cf_valid)

        vertices = np.concatenate(all_world_pts, axis=0)
        colors = np.concatenate(all_colors_list, axis=0)
        confs = np.concatenate(all_conf_list, axis=0)
        logger.info(f"Raw points (keyframes only): {len(vertices)}")

        # ── Scene-adaptive deduplication (works for any video/scale) ─────
        # 1. Compute scene extent to determine adaptive merge radius
        bbox_min = vertices.min(axis=0)
        bbox_max = vertices.max(axis=0)
        scene_diagonal = float(np.linalg.norm(bbox_max - bbox_min))
        # Adaptive radius: 0.2% of scene diagonal, clamped to [2mm, 5cm]
        adaptive_radius = max(0.002, min(0.05, scene_diagonal * 0.002))
        logger.info(f"Scene diagonal: {scene_diagonal:.2f}m → merge radius: {adaptive_radius*1000:.1f}mm")

        # 2. Use KD-tree radius search: for each point, find all neighbors within
        #    adaptive_radius, then keep ONLY the most confident one among them.
        try:
            from scipy.spatial import cKDTree
            tree = cKDTree(vertices)
            # Query all neighbor indices within radius (memory-efficient batch)
            pairs = tree.query_ball_tree(tree, adaptive_radius)
            keep_mask = np.ones(len(vertices), dtype=bool)
            for i in range(len(vertices)):
                if not keep_mask[i]:
                    continue
                # Among all neighbors, keep only the one with highest confidence
                neighbors = pairs[i]
                if len(neighbors) > 1:
                    best_idx = i
                    best_conf = confs[i]
                    for j in neighbors:
                        if confs[j] > best_conf:
                            best_conf = confs[j]
                            best_idx = j
                    # Mark all others in this group for removal
                    for j in neighbors:
                        if j != best_idx:
                            keep_mask[j] = False
            before_merge = len(vertices)
            vertices = vertices[keep_mask]
            colors = colors[keep_mask]
            logger.info(f"After adaptive radius merge ({adaptive_radius*1000:.1f}mm): {before_merge} → {len(vertices)} points")
        except ImportError:
            # Fallback: simple voxel-based merge
            voxel_size = max(adaptive_radius, 0.005)
            vk = np.floor(vertices / voxel_size).astype(np.int64)
            best: dict = {}
            for i in range(len(vertices)):
                k = (vk[i, 0], vk[i, 1], vk[i, 2])
                ci = float(confs[i])
                if k not in best or ci > best[k][0]:
                    best[k] = (ci, i)
            indices = [v[1] for v in best.values()]
            vertices = vertices[indices]
            colors = colors[indices]
            logger.info(f"After voxel merge ({voxel_size*1000:.1f}mm): {len(vertices)} points")

        # Cap for browser rendering
        if len(vertices) > 800000:
            idx = np.random.choice(len(vertices), 800000, replace=False)
            vertices = vertices[idx]; colors = colors[idx]
            logger.info(f"Capped to 800K points")

    # ── Export GLB via trimesh ─────────────────────────────────────────
    glb_path = os.path.join(tmpdir, "output.glb")
    scene = trimesh.Scene()
    pc = trimesh.PointCloud(vertices=vertices, colors=colors.astype(np.uint8))
    scene.add_geometry(pc)
    centroid = vertices.mean(axis=0)
    scene.apply_translation(-centroid)

    # Camera trail as small spheres
    cam_positions = []
    for fi in keyframe_idx:
        ext = extrinsics[fi]
        cam_positions.append(ext[:, 3])
    cam_arr = np.array(cam_positions)
    cam_arr_centered = cam_arr - centroid
    for i, cp in enumerate(cam_arr_centered):
        s_t = trimesh.creation.icosphere(subdivisions=2, radius=0.01)
        t_c = i / max(1, len(cam_arr_centered) - 1)
        s_t.visual.vertex_colors = np.tile([int(255*(1-t_c)), 40, int(255*t_c)], (len(s_t.vertices), 1)).astype(np.uint8)
        s_t.apply_translation(cp.tolist())
        scene.add_geometry(s_t)

    scene.export(glb_path)
    size_mb = os.path.getsize(glb_path) / (1024 * 1024)
    logger.info(f"GLB exported: {size_mb:.1f} MB, {n_keyframes} keyframes, elapsed={elapsed:.1f}s")

    return glb_path

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
