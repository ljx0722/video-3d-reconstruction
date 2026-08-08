#!/bin/bash
set -e
PY=/root/miniconda3/bin/python
PIP=/root/miniconda3/bin/pip

echo "=== GPU: $(nvidia-smi --query-gpu=name --format=csv,noheader) ==="

# Create checkpoint dir
mkdir -p /root/lingbot-map/checkpoint

# Download model
echo "=== Downloading model ==="
cd /root/lingbot-map
$PY -c "
from huggingface_hub import snapshot_download
import os, sys
try:
    path = snapshot_download('robbyant/lingbot-map', local_dir='./checkpoint', local_dir_use_symlinks=False, resume_download=True)
    print('Download OK:', path)
    for name in os.listdir(path):
        size = os.path.getsize(os.path.join(path, name))
        print(name, '-', round(size/1024/1024, 1), 'MB')
except Exception as e:
    print('ERROR:', e)
    sys.exit(1)
"
echo "=== Checkpoint ==="
ls -lh checkpoint/

# Test GPU
$PY -c "import torch; print('CUDA:', torch.cuda.is_available())"

# Start worker
pkill -9 -f gpu_server 2>/dev/null || true
sleep 1
MODEL_PATH=/root/lingbot-map/checkpoint/lingbot-map.pt nohup $PY /root/gpu_server.py > /root/gpu_worker.log 2>&1 &
echo "PID=$!"
sleep 12
echo "=== Worker log ==="
tail -30 /root/gpu_worker.log
echo "=== DONE ==="
