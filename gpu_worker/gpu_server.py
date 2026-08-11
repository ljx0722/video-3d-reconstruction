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
GPU_SECRET = os.environ.get("GPU_SECRET", "")


def _worker_headers(**extra: str) -> dict[str, str]:
    headers = {"User-Agent": "gpu-worker/1.0", **extra}
    if GPU_SECRET:
        headers["Authorization"] = f"Bearer {GPU_SECRET}"
    return headers

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
    # weights_only=False required for GCTStream custom model classes
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
    """Run lingbot-map inference and return point-cloud GLB plus Mesh inputs."""
    import torch
    import cv2
    import numpy as np
    from lingbot_map.utils.load_fn import load_and_preprocess_images
    from lingbot_map.utils.pose_enc import pose_encoding_to_extri_intri
    from lingbot_map.utils.geometry import closed_form_inverse_se3_general
    import trimesh

    load_model()

    # Update progress now that model is loaded (took ~15-20s for 7GB checkpoint)
    _update_status(job_id, "processing", 0.11, "模型已加载, 开始处理视频...")

    t_start = time.time()

    fps = settings.get("fps", 10)
    mode = settings.get("mode", "streaming")

    # ── Extract frames ─────────────────────────────────────────────────
    _update_status(job_id, "processing", 0.12, "正在解码视频帧...")

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
    # max_keyframes: strict cap on GLB frames to keep file size manageable

    if video_duration < 10:
        max_target, stride, max_keyframes, conf_pct = 300, 1, 60, 0
    elif video_duration < 20:
        max_target, stride, max_keyframes, conf_pct = 400, 1, 80, 3
    elif video_duration < 30:
        max_target, stride, max_keyframes, conf_pct = 450, 1, 100, 5
    elif video_duration < 45:
        max_target, stride, max_keyframes, conf_pct = 500, 2, 80, 8
    elif video_duration < 60:
        max_target, stride, max_keyframes, conf_pct = 500, 2, 100, 8
    elif video_duration < 90:
        max_target, stride, max_keyframes, conf_pct = 550, 2, 120, 10
    elif video_duration < 150:
        max_target, stride, max_keyframes, conf_pct = 600, 2, 150, 12
    else:
        max_target, stride, max_keyframes, conf_pct = 600, 2, 180, 12

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
    _update_status(job_id, "processing", 0.15, f"预处理 {num_frames} 帧图像...")
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

    _update_status(job_id, "processing", 0.85, "导出GLB模型...")
    from lingbot_map.vis.glb_export import predictions_to_glb

    stride = settings.get("_dynamic_stride", 2)
    max_kf = settings.get("_max_keyframes", 50)
    conf_pct_val = settings.get("_conf_pct", 20)

    # Spatial downsampling
    vis_pred_sub = {}
    for k, v in vis_pred.items():
        if k in ("world_points_from_depth", "world_points") and v.ndim >= 4:
            vis_pred_sub[k] = v[:, ::stride, ::stride, ...]
        elif k == "depth" and v.ndim >= 3:
            vis_pred_sub[k] = v[:, ::stride, ::stride, ...]
        elif k in ("depth_conf", "world_points_conf") and v is not None and v.ndim >= 3:
            vis_pred_sub[k] = v[:, ::stride, ::stride, ...]
        elif k == "images" and v.ndim >= 4:
            vis_pred_sub[k] = v[:, :, ::stride, ::stride] if v.shape[1] == 3 else v[:, ::stride, ::stride, ...]
        else:
            vis_pred_sub[k] = v

    # Temporally subsample to max_keyframes
    num_frames_full = vis_pred_sub.get("depth", vis_pred.get("depth", np.zeros(1))).shape[0]
    if num_frames_full > max_kf:
        kf_step = max(2, int(np.ceil(num_frames_full / max_kf)))
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

    import shutil as _shutil
    _shutil.rmtree(tmpdir, ignore_errors=True)

    size_mb = len(glb_data) / (1024 * 1024)
    total_elapsed = time.time() - t_start
    logger.info(f"GLB exported: {size_mb:.1f} MB, {num_frames} frames, elapsed={elapsed:.1f}s (total={total_elapsed:.0f}s)")

    settings["_num_frames"] = num_frames
    settings["_total_elapsed"] = total_elapsed
    settings["_num_points"] = total_pts

    return glb_data, vis_pred_sub, conf_pct_val

def poll_and_process():
    """Main loop: poll for pending jobs, process them, upload results."""
    if not GPU_SECRET or GPU_SECRET == "gpu-worker-secret":
        raise RuntimeError("GPU_SECRET must be configured with a non-default value")
    logger.info(f"GPU Worker starting, backend={BACKEND_URL}")

    # Check cp exists (model loaded lazily on first job)
    _find_checkpoint()
    logger.info("GPU Worker ready, polling for jobs...")

    while True:
        try:
            # Get pending jobs from backend
            req = urllib.request.Request(
                f"{BACKEND_URL}/api/v1/gpu/pending",
                headers=_worker_headers(),
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
                point_cloud_uploaded = False
                # Download video with retry + backoff
                video_data = None
                last_err = None
                for retry in range(5):
                    try:
                        _update_status(job_id, "processing", 0.02,
                                       f"从后端下载视频{'' if retry==0 else f'重试{retry}/5'}..." if retry==0 else f"下载重试{retry}/5...")
                        video_req = urllib.request.Request(
                            f"{BACKEND_URL}/api/v1/gpu/video/{job_id}",
                            headers=_worker_headers(),
                        )
                        # Read in 32KB chunks with socket-level read timeout
                        resp = urllib.request.urlopen(video_req, timeout=120)
                        chunks = []
                        total = 0
                        while True:
                            chunk = resp.read(32768)
                            if not chunk: break
                            chunks.append(chunk)
                            total += len(chunk)
                            # Log progress for large videos
                            if retry == 0 and total % (5 * 1024 * 1024) < 32768:
                                _update_status(job_id, "processing", 0.04, f"下载视频 {total//(1024*1024)}MB...")
                        video_data = b''.join(chunks)
                        resp.close()
                        logger.info(f"Downloaded {len(video_data)/1024/1024:.1f} MB")
                        break
                    except Exception as e:
                        last_err = e
                        logger.warning(f"Download attempt {retry+1}/5 failed: {e}")
                        if retry < 4:
                            time.sleep(2 + retry * retry)  # 2s, 3s, 6s, 11s backoff
                        continue
                if video_data is None:
                    raise last_err or Exception("Video download failed after 5 retries")

                with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
                    f.write(video_data)
                    video_tmp = f.name

                # Get settings
                settings = job.get("settings", {"fps": 10, "mode": "streaming", "conf_threshold": 1.5})
                if isinstance(settings, str):
                    settings = json.loads(settings)

                # Update status to processing
                _update_status(job_id, "processing", 0.1)

                # Run inference and export the point cloud before starting Mesh reconstruction.
                glb_data, mesh_inputs, mesh_conf_pct = process_video(video_tmp, settings, job_id)
                os.unlink(video_tmp)

                _update_status(job_id, "processing", 0.9, "上传点云模型...")
                _upload_result(job_id, glb_data)
                point_cloud_uploaded = True

                _update_status(job_id, "processing", 0.92, "正在生成 Mesh 模型...")
                try:
                    from mesh_builder import build_mesh
                except ImportError:
                    from gpu_worker.mesh_builder import build_mesh
                with tempfile.TemporaryDirectory() as mesh_tmpdir:
                    mesh_result = build_mesh(mesh_inputs, mesh_conf_pct, mesh_tmpdir)
                settings["_mesh_stats"] = mesh_result.stats
                del mesh_inputs

                # Finalize independently so a valid point cloud remains viewable if Mesh fails.
                nf = settings.get("_num_frames", 0)
                te = settings.get("_total_elapsed", 0)
                np_pts = settings.get("_num_points", 0)
                mesh_stats = settings.get("_mesh_stats", {})
                if not mesh_result.success:
                    mesh_error = f"Mesh 生成失败: {mesh_result.error}"
                    _update_status(
                        job_id,
                        "partial",
                        0.9,
                        mesh_error,
                        num_frames=nf,
                        processing_time_secs=te,
                        num_points=np_pts,
                    )
                    logger.warning("Job %s completed with point cloud only: %s", job_id, mesh_error)
                    mesh_data = b""
                else:
                    mesh_data = mesh_result.data
                    _update_status(job_id, "processing", 0.95, "上传 Mesh 模型...")
                    _upload_mesh(job_id, mesh_data)
                    mesh_faces = mesh_stats.get("mesh_triangles", 0)
                    _update_status(
                        job_id,
                        "completed",
                        1.0,
                        f"重建完成，Mesh {mesh_faces} 个三角面",
                        num_frames=nf,
                        processing_time_secs=te,
                        num_points=np_pts,
                    )
                    logger.info(
                        "Job %s completed (point cloud %.1f MB, mesh %.1f MB, %s)",
                        job_id,
                        len(glb_data) / 1024 / 1024,
                        len(mesh_data) / 1024 / 1024,
                        mesh_stats,
                    )

                # Aggressive GPU cleanup between jobs to prevent OOM
                del glb_data
                del mesh_data
                import gc; gc.collect()
                try:
                    import torch as _torch
                    _torch.cuda.empty_cache()
                    _torch.cuda.reset_peak_memory_stats()
                except: pass

            except Exception as e:
                logger.exception(f"Job {job_id} failed")
                try:
                    partial_stats = settings if point_cloud_uploaded else {}
                    _update_status(
                        job_id,
                        "partial" if point_cloud_uploaded else "failed",
                        0.9 if point_cloud_uploaded else 0,
                        str(e)[:500],
                        num_frames=partial_stats.get("_num_frames", 0),
                        num_points=partial_stats.get("_num_points", 0),
                        processing_time_secs=partial_stats.get("_total_elapsed", 0),
                    )
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
    payload = {"status": status, "progress": progress, "detail": detail,
               "error_message": detail if status in ("failed", "partial") else "",
               "num_frames": int(num_frames), "num_points": int(num_points),
               "processing_time_secs": float(processing_time_secs)}
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        f"{BACKEND_URL}/api/v1/gpu/status/{job_id}",
        data=data,
        headers=_worker_headers(**{"Content-Type": "application/json"}),
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
                headers=_worker_headers(**{"Content-Type": "application/octet-stream"}),
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

def _upload_mesh(job_id: str, mesh_data: bytes):
    for attempt in range(3):
        try:
            req = urllib.request.Request(
                f"{BACKEND_URL}/api/v1/gpu/result_mesh/{job_id}",
                data=mesh_data,
                headers=_worker_headers(**{"Content-Type": "application/octet-stream"}),
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

if __name__ == "__main__":
    poll_and_process()
