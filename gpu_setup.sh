#!/bin/bash
set -e
PY=/root/miniconda3/bin/python

echo "=== GPU: $(nvidia-smi --query-gpu=name --format=csv,noheader) ==="

export HF_ENDPOINT=https://hf-mirror.com
mkdir -p /root/lingbot-map/checkpoint

echo "=== Downloading model from hf-mirror.com ==="
cd /root/lingbot-map
$PY -c "
import os, sys
os.environ['HF_ENDPOINT'] = 'https://hf-mirror.com'
from huggingface_hub import snapshot_download
try:
    path = snapshot_download('robbyant/lingbot-map', local_dir='./checkpoint', local_dir_use_symlinks=False, resume_download=True)
    print('Download OK:', path)
    for name in os.listdir(path):
        size = os.path.getsize(os.path.join(path, name))
        print(name, '-', round(size/1024/1024, 1), 'MB')
except Exception as e:
    print('hf-mirror failed, trying modelscope...')
    from modelscope import snapshot_download as ms_snapshot
    path = ms_snapshot('robbyant/lingbot-map', cache_dir='./checkpoint')
    print('ModelScope OK:', path)
"
echo "=== Checkpoint ==="
ls -lh /root/lingbot-map/checkpoint/
find /root/lingbot-map/checkpoint -name "*.pt" -ls 2>/dev/null | head -5
find /root -path "*/robbyant*" -name "*.pt" -ls 2>/dev/null | head -5

# Test GPU
$PY -c "import torch; print('CUDA:', torch.cuda.is_available())"

# Start worker
pkill -9 -f gpu_server 2>/dev/null || true
sleep 1
export MODEL_PATH=/root/lingbot-map/checkpoint/lingbot-map.pt
nohup $PY /root/gpu_server.py > /root/gpu_worker.log 2>&1 &
echo "PID=$!"
sleep 12
echo "=== Worker log ==="
tail -30 /root/gpu_worker.log
echo "=== DONE ==="
