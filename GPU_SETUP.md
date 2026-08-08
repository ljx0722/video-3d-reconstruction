# GPU Worker for lingbot-map on AutoDL

## 1. Create AutoDL Instance

Go to [AutoDL](https://www.autodl.com/), create an instance:

- **GPU**: RTX 3090/4090 or A10 (8GB+ VRAM)
- **Image**: PyTorch 2.1.0 + CUDA 12.1 + Python 3.10
- **Data Disk**: at least 30GB (model checkpoint ~4GB)

After instance starts, note the **SSH connection info** and **public URL**.

## 2. SSH into instance and run setup

```bash
ssh -p <PORT> root@<HOST>

# Install dependencies
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu121
pip install opencv-python-headless trimesh flask numpy scipy tqdm pillow einops safetensors huggingface_hub redis minio

# Clone lingbot-map
git clone https://github.com/Robbyant/lingbot-map.git
cd lingbot-map
pip install -e .

# Download model checkpoint
python -c "
from huggingface_hub import snapshot_download
snapshot_download('robbyant/lingbot-map', local_dir='./checkpoint')
"

# Start GPU worker server
python gpu_server.py
```

## 3. GPU Worker API

- **POST `/process`** — Receive job_id, download video from Sealos, run inference, upload GLB back
- **GET `/health`** — Health check

## 4. Sealos Backend Integration

Backend forwards processing requests to GPU worker URL when video uploads complete.
