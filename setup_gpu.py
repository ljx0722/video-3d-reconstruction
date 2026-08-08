#!/usr/bin/env python3
"""
AutoDL GPU Worker setup script.
Connects via SSH, installs deps, downloads model, starts worker.
"""
import paramiko
import time
import sys
import os

HOST = "connect.nmb2.seetacloud.com"
PORT = 10340
USER = "root"
PASSWORD = "p4hbP7UoQzQ0"

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

print(f"Connecting to {HOST}:{PORT}...")
client.connect(HOST, port=PORT, username=USER, password=PASSWORD, timeout=30)
print("Connected!")


def run(cmd, timeout=120):
    """Run a command and stream output."""
    print(f"\n>>> {cmd}")
    stdin, stdout, stderr = client.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode(errors='replace')
    err = stderr.read().decode(errors='replace')
    if out:
        print(out[-500:])
    if err and "WARNING" not in err and err.strip():
        print(f"STDERR: {err[-300:]}")
    return out + err


# ── 1. Check environment ──────────────────────────────────────────────
run("nvidia-smi --query-gpu=name,memory.total --format=csv,noheader 2>/dev/null || echo 'NO_GPU'")
run("python3 --version")
run("pip3 --version")
run("ls /root/ 2>/dev/null")

# ── 2. Install Python deps ────────────────────────────────────────────
print("\n" + "="*60)
print("STEP 2: Installing Python dependencies...")
print("="*60)

deps = "opencv-python-headless trimesh fla sk numpy scipy tqdm pillow einops safetensors huggingface_hub"
# flask -> fastapi but worker doesn't need it, remove it

result = run(
    "pip3 install opencv-python-headless trimesh numpy scipy tqdm pillow einops safetensors huggingface_hub 2>&1 | tail -20",
    timeout=300
)

# ── 3. Clone lingbot-map ──────────────────────────────────────────────
print("\n" + "="*60)
print("STEP 3: Setting up lingbot-map...")
print("="*60)

run("test -d /root/lingbot-map || git clone https://github.com/Robbyant/lingbot-map.git /root/lingbot-map", timeout=60)
run("cd /root/lingbot-map && pip3 install -e . 2>&1 | tail -5", timeout=120)

# ── 4. Download model checkpoint ──────────────────────────────────────
print("\n" + "="*60)
print("STEP 4: Downloading model checkpoint (~4GB)...")
print("="*60)

run("""
cd /root/lingbot-map
test -f checkpoint/lingbot-map.pt 2>/dev/null || {
    python3 -c "
from huggingface_hub import snapshot_download
snapshot_download('robbyant/lingbot-map', local_dir='./checkpoint', resume_download=True)
"
}
ls -lh /root/lingbot-map/checkpoint/*.pt 2>/dev/null || echo "No .pt files found, searching..."
find /root/lingbot-map/checkpoint -name "*.pt" -ls 2>/dev/null || echo "checkpoint not in expected location"
find /root -name "*.pt" -ls 2>/dev/null | tail -5
""", timeout=600)

# ── 5. Download GPU worker script ────────────────────────────────────
print("\n" + "="*60)
print("STEP 5: Downloading GPU worker...")
print("="*60)

run("""
cd /root
curl -sL -o gpu_server.py https://raw.githubusercontent.com/ljx0722/video-3d-reconstruction/master/gpu_worker/gpu_server.py
ls -lh /root/gpu_server.py
""", timeout=60)

# Find the actual checkpoint path
print("\n" + "="*60)
print("STEP 6: Finding checkpoint and starting worker...")
print("="*60)

checkpoint_result = run("""
find /root -name "*.pt" -type f 2>/dev/null | head -5
""")

# Extract the checkpoint path
checkpoint_path = "/root/lingbot-map/checkpoint/lingbot-map.pt"
for line in checkpoint_result.split('\n'):
    if '.pt' in line and ('lingbot' in line.lower() or 'checkpoint' in line.lower()):
        checkpoint_path = line.strip()
        break
print(f"Using checkpoint: {checkpoint_path}")

# Stop any existing worker
run("pkill -f gpu_server.py 2>/dev/null; sleep 1; echo done")

# Start worker
run(f"""
cd /root
MODEL_PATH='{checkpoint_path}' nohup python3 gpu_server.py > gpu_worker.log 2>&1 &
echo "Worker PID: $!"
sleep 5
tail -20 gpu_worker.log
""", timeout=30)

# ── 7. Final check ────────────────────────────────────────────────────
print("\n" + "="*60)
print("STEP 7: Final verification...")
print("="*60)

run("sleep 15 && tail -30 /root/gpu_worker.log", timeout=30)
run("ps aux | grep gpu_server | grep -v grep", timeout=10)
run("curl -s http://localhost:8080/health 2>/dev/null || echo 'Worker HTTP not yet up'", timeout=10)

client.close()
print("\n" + "="*60)
print("SETUP COMPLETE")
print("="*60)
print("GPU Worker should be running. Check https://video2gauss.sealoshzh.site")
print("To monitor: tail -f /root/gpu_worker.log")
