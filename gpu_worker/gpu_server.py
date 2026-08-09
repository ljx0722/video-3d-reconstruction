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
def process_video(video_path: str, settings: dict, job_id: str) -> bytes:
    """Run lingbot-map inference and return GLB bytes. Cleans temp dirs after."""
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
    _update_status(job_id, "processing", 0.02, "正在解码视频帧...")

    cap = cv2.VideoCapture(video_path)
    src_fps = cap.get(cv2.CAP_PROP_FPS) or 30
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    # Auto-cap to ~300 frames for reasonable processing time (~60s)
    MAX_TARGET_FRAMES = 300
    desired_fps = fps
    interval = max(1, round(src_fps / desired_fps))
    estimated_frames = total_frames // interval
    if estimated_frames > MAX_TARGET_FRAMES:
        # Adjust fps up to reduce extracted frames
        desired_fps = max(1, src_fps * MAX_TARGET_FRAMES / total_frames)
        interval = max(1, round(src_fps / desired_fps))
        estimated_frames = total_frames // interval
        logger.info(f"Auto-capped frames: {total_frames} total -> ~{estimated_frames} (fps={desired_fps:.1f})")

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

    _update_status(job_id, "processing", 0.85, "导出GLB模型...")
    from lingbot_map.vis.glb_export import predictions_to_glb

    stride = 4
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

    glb_path = os.path.join(tmpdir, "output.glb")
    scene = predictions_to_glb(vis_pred_sub, conf_thres=10, show_cam=True, mask_sky=False)
    scene.export(glb_path)
    # Read GLB into memory, cleanup temp dir
    with open(glb_path, "rb") as f:
        glb_data = f.read()

    import shutil as _shutil
    _shutil.rmtree(tmpdir, ignore_errors=True)

    size_mb = len(glb_data) / (1024 * 1024)
    logger.info(f"GLB exported: {size_mb:.1f} MB, {num_frames} frames, elapsed={elapsed:.1f}s")

    return glb_data

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
                glb_data = process_video(video_tmp, settings, job_id)
                os.unlink(video_tmp)

                # Upload GLB result
                _update_status(job_id, "processing", 0.9)
                _upload_result(job_id, glb_data)

                # Final stream status
                _update_status(job_id, "completed", 1.0)

                logger.info(f"Job {job_id} completed ({len(glb_data)/1024/1024:.1f} MB)")

                # Aggressive GPU cleanup between jobs to prevent OOM
                del glb_data
                import gc; gc.collect()
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
                    torch.cuda.reset_peak_memory_stats()

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


def _update_status(job_id: str, status: str, progress: float, detail: str = ""):
    data = json.dumps({"status": status, "progress": progress, "detail": detail, "error_message": ""}).encode()
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
