"""
GPU Worker inference pipeline for lingbot-map.
Mirrors demo.py but packaged as a service function.
"""
import io
import os
import time
import tempfile
import logging

import cv2
import numpy as np
import torch

logger = logging.getLogger(__name__)

# Model cache: loaded once, reused across jobs
_model = None
_device = None
_dtype = None
_checkpoint_path = None


def _load_model(checkpoint_path: str):
    """Load GCTStream model from checkpoint. Cached after first load."""
    global _model, _device, _dtype, _checkpoint_path

    if _model is not None and _checkpoint_path == checkpoint_path:
        return _model, _device, _dtype

    os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")
    _device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    if torch.cuda.is_available():
        _dtype = torch.bfloat16 if torch.cuda.get_device_capability()[0] >= 8 else torch.float16
    else:
        _dtype = torch.float32

    from lingbot_map.models.gct_stream import GCTStream

    logger.info("Building GCTStream model...")
    _model = GCTStream(
        img_size=518,
        patch_size=14,
        enable_3d_rope=True,
        max_frame_num=1024,
        kv_cache_sliding_window=64,
        kv_cache_scale_frames=8,
        kv_cache_cross_frame_special=True,
        kv_cache_include_scale_frames=True,
        use_sdpa=False,
        camera_num_iterations=4,
    )

    logger.info(f"Loading checkpoint: {checkpoint_path}")
    ckpt = torch.load(checkpoint_path, map_location=_device, weights_only=False)
    state_dict = ckpt.get("model", ckpt)
    _model.load_state_dict(state_dict, strict=False)
    _model = _model.to(_device).eval()

    if _dtype != torch.float32 and hasattr(_model, "aggregator"):
        logger.info(f"Casting aggregator to {_dtype}")
        _model.aggregator = _model.aggregator.to(dtype=_dtype)

    if torch.cuda.is_available():
        torch.cuda.empty_cache()
        logger.info(
            f"GPU mem after load: alloc={torch.cuda.memory_allocated()/1e9:.2f} GB, "
            f"reserved={torch.cuda.memory_reserved()/1e9:.2f} GB"
        )

    _checkpoint_path = checkpoint_path
    return _model, _device, _dtype


def infer_video(video_bytes: bytes, settings: dict, checkpoint_path: str) -> bytes:
    """
    Run lingbot-map inference on video and return GLB bytes.

    Args:
        video_bytes: Raw video file bytes
        settings: Dict with fps, mode, conf_threshold
        checkpoint_path: Path to model checkpoint

    Returns:
        GLB binary data
    """
    fps = settings.get("fps", 10)
    mode = settings.get("mode", "streaming")
    conf_threshold = settings.get("conf_threshold", 1.5)

    model, device, dtype = _load_model(checkpoint_path)

    # ── Extract frames from video ──────────────────────────────────────────
    with tempfile.TemporaryDirectory() as tmpdir:
        video_path = os.path.join(tmpdir, "input.mp4")
        with open(video_path, "wb") as f:
            f.write(video_bytes)

        cap = cv2.VideoCapture(video_path)
        src_fps = cap.get(cv2.CAP_PROP_FPS) or 30
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
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

        if not frames:
            raise ValueError("No frames extracted from video")

        logger.info(f"Extracted {len(frames)} frames from video ({total_frames} total, interval={interval})")

        # Save frames as images for preprocessing
        frame_dir = os.path.join(tmpdir, "frames")
        os.makedirs(frame_dir)
        frame_paths = []
        for i, frm in enumerate(frames):
            p = os.path.join(frame_dir, f"{i:06d}.jpg")
            cv2.imwrite(p, cv2.cvtColor(frm, cv2.COLOR_RGB2BGR))
            frame_paths.append(p)

        # ── Preprocess ─────────────────────────────────────────────────────
        from lingbot_map.utils.load_fn import load_and_preprocess_images

        logger.info(f"Loading and preprocessing {len(frame_paths)} images...")
        images = load_and_preprocess_images(frame_paths, mode="crop", image_size=518, patch_size=14)
        images = images.to(device)
        num_frames = images.shape[0]
        logger.info(f"Preprocessed: {num_frames} frames, shape {tuple(images.shape)}")

        # ── Inference ──────────────────────────────────────────────────────
        keyframe_interval = 1
        if mode == "streaming" and num_frames > 320:
            keyframe_interval = (num_frames + 319) // 320

        num_scale_frames = min(8, num_frames)
        if num_scale_frames >= num_frames:
            num_scale_frames = max(1, num_frames - 1)

        logger.info(f"Running {mode} inference, scale_frames={num_scale_frames}, kf_interval={keyframe_interval}...")
        t0 = time.time()

        with torch.no_grad(), torch.amp.autocast("cuda", dtype=dtype):
            if mode == "streaming":
                predictions = model.inference_streaming(
                    images, num_scale_frames=num_scale_frames, keyframe_interval=keyframe_interval
                )
            else:
                predictions = model.inference_windowed(
                    images, window_size=64, overlap_size=16, num_scale_frames=num_scale_frames
                )

        elapsed = time.time() - t0
        logger.info(f"Inference done in {elapsed:.1f}s")

        if torch.cuda.is_available():
            logger.info(
                f"GPU peak: alloc={torch.cuda.max_memory_allocated()/1e9:.2f} GB"
            )

        # ── Postprocess ────────────────────────────────────────────────────
        from lingbot_map.utils.pose_enc import pose_encoding_to_extri_intri
        from lingbot_map.utils.geometry import closed_form_inverse_se3_general

        extrinsic, intrinsic = pose_encoding_to_extri_intri(predictions["pose_enc"], images.shape[-2:])

        ext_4x4 = torch.zeros((*extrinsic.shape[:-2], 4, 4), device=extrinsic.device, dtype=extrinsic.dtype)
        ext_4x4[..., :3, :4] = extrinsic
        ext_4x4[..., 3, 3] = 1.0
        ext_4x4 = closed_form_inverse_se3_general(ext_4x4)
        extrinsic = ext_4x4[..., :3, :4]

        predictions["extrinsic"] = extrinsic
        predictions["intrinsic"] = intrinsic

        # Move to CPU
        for k in list(predictions.keys()):
            if isinstance(predictions[k], torch.Tensor):
                predictions[k] = predictions[k].to("cpu")

        images_cpu = images.to("cpu")
        if torch.cuda.is_available():
            torch.cuda.synchronize()

        # Convert to numpy
        vis_pred = {}
        for k, v in predictions.items():
            if isinstance(v, torch.Tensor):
                v_np = v.numpy()
                if v_np.ndim >= 3 and v_np.shape[0] == 1:
                    v_np = v_np[0]
                vis_pred[k] = v_np
            elif isinstance(v, np.ndarray):
                vis_pred[k] = v
            else:
                vis_pred[k] = v

        imgs_np = images_cpu.numpy()
        if imgs_np.ndim >= 4 and imgs_np.shape[0] == 1:
            imgs_np = imgs_np[0]
        vis_pred["images"] = imgs_np

        # ── Export GLB ─────────────────────────────────────────────────────
        from lingbot_map.vis.glb_export import predictions_to_glb

        conf_percentile = conf_threshold  # already in range 0-100

        # Write a temporary GLB file
        glb_path = os.path.join(tmpdir, "output.glb")
        scene = predictions_to_glb(
            vis_pred,
            conf_thres=conf_percentile,
            show_cam=True,
            mask_sky=False,
        )

        scene.export(glb_path)
        logger.info(f"GLB exported to {glb_path}")

        with open(glb_path, "rb") as f:
            glb_data = f.read()

        logger.info(f"GLB size: {len(glb_data)/1024/1024:.1f} MB")
        return glb_data
