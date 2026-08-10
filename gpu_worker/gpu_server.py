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
CHECKPOINT_PATH = os.environ.get("MODEL_PATH") or os.environ.get("CHECKPOINT_PATH") or "/root/autodl-tmp/lingbot-map.pt"

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
        enable_3d_rope=True, max_frame_num=512,
        kv_cache_sliding_window=64, kv_cache_scale_frames=4,
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
def process_video(video_path: str, settings: dict, job_id: str):
    """Run lingbot-map inference and return (glb_bytes, mesh_bytes_or_None). Cleans temp dirs after."""
    import torch
    import cv2
    import numpy as np
    from lingbot_map.utils.load_fn import load_and_preprocess_images
    from lingbot_map.utils.pose_enc import pose_encoding_to_extri_intri
    from lingbot_map.utils.geometry import closed_form_inverse_se3_general
    import trimesh

    load_model()

    t_start = time.time()

    fps = settings.get("fps", 10)
    mode = settings.get("mode", "streaming")

    # ── Extract frames ─────────────────────────────────────────────────
    _update_status(job_id, "processing", 0.02, "正在解码视频帧...")

    cap = cv2.VideoCapture(video_path)
    src_fps = cap.get(cv2.CAP_PROP_FPS) or 30
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    video_duration = total_frames / src_fps if src_fps > 0 else 0

    # ── Adaptive quality strategy ──────────────────────────────────────
    # Goal: approach "manual frame selection" quality — extract frames close to
    # user-requested FPS, use stride=1 for short scenes, keep most confidence points.
    #
    # Point budget per keyframe: stride=1→268K, stride=2→67K, stride=3→30K
    # GLB winner-take-all dedup removes ~40-60% overlap, so actual ~half.
    #
    # max_target: frames fed to GPU (capped at ~500 to stay under 24GB VRAM)
    # max_keyframes: frames kept in final GLB after temporal subsampling
    # conf_pct: confidence percentile cutoff (0=keep all, 10=drop bottom 10%)

    if video_duration < 10:
        # Very short clip — full resolution, keep everything
        max_target, stride, max_keyframes, conf_pct = 300, 1, 200, 0
    elif video_duration < 20:
        max_target, stride, max_keyframes, conf_pct = 400, 1, 250, 0
    elif video_duration < 30:
        max_target, stride, max_keyframes, conf_pct = 450, 1, 300, 3
    elif video_duration < 45:
        # Medium — stride 2 for GLB size, but generous keyframes
        max_target, stride, max_keyframes, conf_pct = 500, 2, 200, 5
    elif video_duration < 60:
        max_target, stride, max_keyframes, conf_pct = 500, 2, 250, 5
    elif video_duration < 90:
        max_target, stride, max_keyframes, conf_pct = 550, 2, 300, 5
    elif video_duration < 150:
        max_target, stride, max_keyframes, conf_pct = 600, 2, 350, 8
    else:
        # Very long scene — lower spatial res but maximal temporal coverage
        max_target, stride, max_keyframes, conf_pct = 600, 2, 400, 8

    desired_fps = fps
    interval = max(1, round(src_fps / desired_fps))
    estimated_frames = total_frames // interval
    if estimated_frames > max_target:
        desired_fps = max(1, src_fps * max_target / total_frames)
        interval = max(1, round(src_fps / desired_fps))
        estimated_frames = total_frames // interval
        logger.info(f"Video {video_duration:.0f}s: {total_frames} total → ~{estimated_frames} frames (dynamic cap)")
    else:
        logger.info(f"Video {video_duration:.0f}s: {total_frames} total → ~{estimated_frames} frames")

    # Store for GLB export
    settings["_dynamic_stride"] = stride
    settings["_max_keyframes"] = max_keyframes
    settings["_conf_pct"] = conf_pct

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
    _update_status(job_id, "processing", 0.08, f"预处理 {num_frames} 帧图像...")
    images = load_and_preprocess_images(frame_paths, mode="crop", image_size=518, patch_size=14)
    images = images.to(_device)

    num_scale_frames = min(4, num_frames)
    if num_scale_frames >= num_frames:
        num_scale_frames = max(1, num_frames - 1)

    kf_interval = 1
    if mode == "streaming" and num_frames > 320:
        kf_interval = (num_frames + 319) // 320

    # ── Inference (exactly as demo.py) ──────────────────────────────────
    logger.info(f"Inference: {num_frames} frames, scale={num_scale_frames}, kf={kf_interval}")
    est_time = num_frames / 5.0  # ~5 FPS estimate
    _update_status(job_id, "processing", 0.12, f"GPU 推理 {num_frames} 帧中, 预计 {est_time:.0f}s...")
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
        torch.cuda.reset_peak_memory_stats()

    # Free GPU images after extracting shape info for postprocess
    img_h, img_w = images.shape[-2], images.shape[-1]
    del images
    if torch.cuda.is_available():
        torch.cuda.empty_cache()

    # ── Postprocess (exactly as demo.py) ────────────────────────────────
    # Convert pose encoding to extrinsic/intrinsic
    extrinsic, intrinsic = pose_encoding_to_extri_intri(predictions["pose_enc"], (img_h, img_w))
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
    if torch.cuda.is_available():
        torch.cuda.synchronize()

    predictions.pop("pose_enc_list", None)
    # Images are already moved to CPU in predictions, keep them there
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

    # images are in predictions dict, already moved to CPU
    imgs_np = vis_pred.get("images")
    if imgs_np is not None:
        vis_pred["images"] = imgs_np

    # ── Compute world points AND stream per-batch to frontend ──────────
    if "world_points" not in vis_pred:
        logger.info("Computing world_points_from_depth...")
        from lingbot_map.utils.geometry import unproject_depth_map_to_point_map
        depth_t = vis_pred["depth"]; extrinsics = vis_pred["extrinsic"]; intrinsics = vis_pred["intrinsic"]
        world_pts = unproject_depth_map_to_point_map(depth_t, extrinsics, intrinsics)
        vis_pred["world_points_from_depth"] = world_pts

    # ── Stream point cloud batches to frontend during processing ───────
    _update_status(job_id, "processing", 0.30, "流式推送点云到浏览器...")
    world_pts_arr = vis_pred["world_points_from_depth"]  # (F, H, W, 3)
    images_arr = vis_pred.get("images")                    # (F, H, W, 3) or (F, 3, H, W)
    depth_conf_arr = vis_pred.get("depth_conf")            # (F, H, W)
    num_stream_frames = world_pts_arr.shape[0]
    stream_stride = settings.get("_dynamic_stride", 2)
    stream_conf_pct = settings.get("_conf_pct", 20)

    # Confidence threshold for per-batch streaming
    if depth_conf_arr is not None:
        all_conf = depth_conf_arr.ravel()
        conf_cutoff = np.percentile(all_conf, stream_conf_pct) if all_conf.size > 0 else 0
    else:
        conf_cutoff = 0

    batch_size = max(1, min(10, num_stream_frames // 5))
    total_streamed = 0
    for batch_start in range(0, num_stream_frames, batch_size):
        batch_end = min(batch_start + batch_size, num_stream_frames)
        batch_points = []
        for fi in range(batch_start, batch_end):
            pts = world_pts_arr[fi, ::stream_stride, ::stream_stride].reshape(-1, 3).astype(np.float32)
            if depth_conf_arr is not None:
                conf = depth_conf_arr[fi, ::stream_stride, ::stream_stride].ravel()
                mask = conf > conf_cutoff
                pts = pts[mask]
            if images_arr is not None:
                img = images_arr[fi]
                if img.ndim == 3 and img.shape[0] == 3:  # (C,H,W) → (H,W,C)
                    img = np.transpose(img, (1, 2, 0))
                if img.shape[:2] == (world_pts_arr.shape[1], world_pts_arr.shape[2]):
                    img_ds = img[::stream_stride, ::stream_stride]
                    colors = img_ds.reshape(-1, 3).astype(np.float32)
                    if depth_conf_arr is not None:
                        colors = colors[mask]
                else:
                    colors = np.full_like(pts, 0.6, dtype=np.float32)
            else:
                colors = np.full_like(pts, 0.6, dtype=np.float32)
            interleaved = np.empty((pts.shape[0], 6), dtype=np.float32)
            interleaved[:, :3] = pts
            interleaved[:, 3:] = colors
            batch_points.append(interleaved)
        if not batch_points:
            continue
        packed = np.concatenate(batch_points, axis=0).tobytes()
        batch_idx = batch_start // batch_size
        _push_stream_batch(job_id, packed, batch_idx, len(batch_points))
        total_streamed += sum(b.shape[0] for b in batch_points)

    logger.info(f"Streamed {total_streamed} points over {max(1, (num_stream_frames + batch_size - 1) // batch_size)} batches")

    _update_status(job_id, "processing", 0.85, "导出GLB模型...")
    from lingbot_map.vis.glb_export import predictions_to_glb

    stride = settings.get("_dynamic_stride", 2)
    max_kf = settings.get("_max_keyframes", 50)
    conf_pct_val = settings.get("_conf_pct", 20)

    # Spatial downsampling
    vis_pred_sub = {}
    for k, v in vis_pred.items():
        if k in ("world_points_from_depth","depth") and v.ndim >= 4:
            vis_pred_sub[k] = v[:, ::stride, ::stride]
        elif k == "depth_conf" and v is not None and v.ndim >= 3:
            vis_pred_sub[k] = v[:, ::stride, ::stride]
        elif k == "images" and v.ndim >= 4:
            vis_pred_sub[k] = v[:, :, ::stride, ::stride] if v.shape[1]==3 else v[:, ::stride, ::stride]
        else:
            vis_pred_sub[k] = v

    # Temporally subsample to max_keyframes
    num_frames_full = vis_pred_sub.get("depth", vis_pred.get("depth", np.zeros(1))).shape[0]
    if num_frames_full > max_kf:
        kf_step = max(1, num_frames_full // max_kf)
        for key in list(vis_pred_sub.keys()):
            v = vis_pred_sub[key]
            if isinstance(v, np.ndarray) and v.ndim >= 3 and v.shape[0] == num_frames_full:
                vis_pred_sub[key] = v[::kf_step]
        nf = vis_pred_sub.get("depth", vis_pred.get("depth", np.zeros(1))).shape[0]
        logger.info(f"Temporal subsample: {num_frames_full} keyframes → {nf} (step={kf_step})")

    glb_path = os.path.join(tmpdir, "output.glb")
    scene = predictions_to_glb(vis_pred_sub, conf_thres=conf_pct_val, show_cam=True, mask_sky=False)
    scene.export(glb_path)
    with open(glb_path, "rb") as f:
        glb_data = f.read()

    # Count points for reporting (ensure Python int, not numpy)
    total_pts = 0
    for name in scene.geometry:
        if hasattr(scene.geometry[name], 'vertices'):
            total_pts += int(scene.geometry[name].vertices.shape[0])

    # ── Mesh reconstruction (Open3D Poisson) ───────────────────────────
    mesh_data = _build_mesh(vis_pred_sub, conf_pct_val, tmpdir)

    import shutil as _shutil
    _shutil.rmtree(tmpdir, ignore_errors=True)

    size_mb = len(glb_data) / (1024 * 1024)
    total_elapsed = time.time() - t_start
    logger.info(f"GLB exported: {size_mb:.1f} MB, {num_frames} frames, elapsed={elapsed:.1f}s (total={total_elapsed:.0f}s)")

    settings["_num_frames"] = num_frames
    settings["_total_elapsed"] = total_elapsed
    settings["_num_points"] = total_pts

    return glb_data, mesh_data

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
                glb_data, mesh_data = process_video(video_tmp, settings, job_id)
                os.unlink(video_tmp)

                # Upload GLB result
                _update_status(job_id, "processing", 0.9)
                _upload_result(job_id, glb_data)

                # Upload mesh result if available
                if mesh_data:
                    _update_status(job_id, "processing", 0.95, "上传Mesh模型...")
                    _upload_mesh(job_id, mesh_data)

                # Final stream status with stats
                nf = settings.get("_num_frames", 0)
                te = settings.get("_total_elapsed", 0)
                np_pts = settings.get("_num_points", 0)
                _update_status(job_id, "completed", 1.0, num_frames=nf, processing_time_secs=te, num_points=np_pts)

                logger.info(f"Job {job_id} completed ({len(glb_data)/1024/1024:.1f} MB, mesh {len(mesh_data)/1024/1024:.1f} MB)" if mesh_data else f"Job {job_id} completed ({len(glb_data)/1024/1024:.1f} MB)")

                # Aggressive GPU cleanup between jobs to prevent OOM
                del glb_data
                if mesh_data: del mesh_data
                import gc; gc.collect()
                try:
                    import torch as _torch
                    _torch.cuda.empty_cache()
                    _torch.cuda.reset_peak_memory_stats()
                except: pass

            except Exception as e:
                logger.exception(f"Job {job_id} failed")
                try:
                    _update_status(job_id, "failed", 0, str(e)[:500])
                except Exception:
                    pass
                # Also cleanup GPU after failures
                import gc; gc.collect()
                try:
                    import torch as _torch
                    if _torch.cuda.is_available():
                        _torch.cuda.empty_cache()
                except: pass

        time.sleep(POLL_INTERVAL)


def _update_status(job_id: str, status: str, progress: float, detail: str = "",
                   num_frames: int = 0, num_points: int = 0, processing_time_secs: float = 0):
    payload = {"status": status, "progress": progress, "detail": detail, "error_message": "",
               "num_frames": int(num_frames), "num_points": int(num_points),
               "processing_time_secs": float(processing_time_secs)}
    data = json.dumps(payload).encode()
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

def _build_mesh(vis_pred: dict, conf_pct: float, tmpdir: str) -> bytes | None:
    """Build triangle mesh from world points using Open3D Poisson reconstruction.
    Returns GLB bytes or None if reconstruction failed."""
    try:
        import open3d as o3d
    except ImportError:
        logger.warning("open3d not available, skipping mesh reconstruction")
        return None

    try:
        import numpy as np  # already imported by caller but be safe

        xyz = vis_pred.get("world_points_from_depth")
        if xyz is None:
            xyz = vis_pred.get("world_points")
        if xyz is None:
            logger.warning("No world_points for mesh")
            return None

        images_arr = vis_pred.get("images")
        depth_conf_arr = vis_pred.get("depth_conf")

        # Flatten world points: (F, H, W, 3) → (M, 3)
        xyz_flat = xyz.reshape(-1, 3).astype(np.float64)

        # Confidence filtering
        if depth_conf_arr is not None:
            conf_flat = depth_conf_arr.ravel()
            cutoff = np.percentile(conf_flat, max(0, conf_pct)) if conf_flat.size > 0 else 0
            mask = conf_flat > cutoff
            xyz_flat = xyz_flat[mask]
            logger.info(f"Mesh input: {xyz_flat.shape[0]} pts after conf > {conf_pct}%")
        else:
            logger.info(f"Mesh input: {xyz_flat.shape[0]} pts (no conf filter)")

        if xyz_flat.shape[0] < 1000:
            return None

        # ── Color handling ──────────────────────────────────────────────
        if images_arr is not None:
            # images: (F, C, H, W) or (F, H, W, C)
            if images_arr.ndim == 4 and images_arr.shape[1] == 3:
                images_arr = np.transpose(images_arr, (0, 2, 3, 1))  # → (F, H, W, 3)
            rgb_flat = images_arr.reshape(-1, 3).astype(np.float64)
            if depth_conf_arr is not None:
                rgb_flat = rgb_flat[mask]
        else:
            rgb_flat = np.full_like(xyz_flat, 0.6, dtype=np.float64)

        # ── Build Open3D point cloud ────────────────────────────────────
        pcd = o3d.geometry.PointCloud()
        pcd.points = o3d.utility.Vector3dVector(xyz_flat)
        if rgb_flat is not None:
            pcd.colors = o3d.utility.Vector3dVector(np.clip(rgb_flat, 0, 1))

        # ── Downsample ──────────────────────────────────────────────────
        bbox_diag = np.linalg.norm(pcd.get_max_bound() - pcd.get_min_bound())
        voxel_size = max(0.005, bbox_diag * 0.003)
        pcd = pcd.voxel_down_sample(voxel_size)
        logger.info(f"Mesh downsample: {len(pcd.points)} pts (voxel={voxel_size:.4f})")

        if len(pcd.points) < 100:
            return None

        # ── Normal estimation ───────────────────────────────────────────
        radius = max(voxel_size * 3, bbox_diag * 0.01)
        pcd.estimate_normals(o3d.geometry.KDTreeSearchParamHybrid(radius=radius, max_nn=30))
        pcd.orient_normals_towards_camera_location()

        # ── Poisson reconstruction ──────────────────────────────────────
        depth = 8 if len(pcd.points) < 200000 else 9
        mesh, densities = o3d.geometry.TriangleMesh.create_from_point_cloud_poisson(pcd, depth=depth)

        # Remove low-density triangles (bottom 5%)
        if densities is not None and len(densities) > 0:
            thresh = np.quantile(densities, 0.05)
            vertices_to_remove = densities < thresh
            mesh.remove_vertices_by_mask(vertices_to_remove)

        logger.info(f"Poisson mesh: {len(mesh.vertices)} verts, {len(mesh.triangles)} faces (depth={depth})")

        if len(mesh.triangles) < 10:
            return None

        # ── Vertex color transfer (KDTree nearest-neighbor) ─────────────
        pcd_tree = o3d.geometry.KDTreeFlann(pcd)
        mesh_verts = np.asarray(mesh.vertices, dtype=np.float64)
        mesh_colors = np.zeros_like(mesh_verts)
        pcd_pts = np.asarray(pcd.points)
        pcd_cols = np.asarray(pcd.colors)
        for i in range(len(mesh_verts)):
            _, idx, _ = pcd_tree.search_knn_vector_3d(mesh_verts[i], 1)
            mesh_colors[i] = pcd_cols[idx[0]]
        mesh.vertex_colors = o3d.utility.Vector3dVector(np.clip(mesh_colors, 0, 1))

        # Export GLB
        mesh_path = os.path.join(tmpdir, "mesh.glb")
        o3d.io.write_triangle_mesh(mesh_path, mesh)
        with open(mesh_path, "rb") as f:
            return f.read()

    except Exception:
        logger.exception("Mesh reconstruction failed")
        return None

def _upload_mesh(job_id: str, mesh_data: bytes):
    for attempt in range(3):
        try:
            req = urllib.request.Request(
                f"{BACKEND_URL}/api/v1/gpu/result_mesh/{job_id}",
                data=mesh_data,
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
                logger.warning(f"Mesh upload attempt {attempt+1} failed, retrying: {e}")
                time.sleep(5)
            else:
                raise

def _push_stream_batch(job_id: str, data: bytes, batch: int, frame_count: int):
    """Push a point cloud batch to the backend for live streaming to WebSocket clients."""
    try:
        req = urllib.request.Request(
            f"{BACKEND_URL}/api/v1/gpu/stream/{job_id}?batch={batch}&count={frame_count}",
            data=data,
            headers={
                "Content-Type": "application/octet-stream",
                "User-Agent": "gpu-worker/1.0",
            },
            method="POST",
        )
        urllib.request.urlopen(req, timeout=30)
    except Exception as e:
        logger.warning(f"Stream batch {batch} failed: {e}")

if __name__ == "__main__":
    poll_and_process()
