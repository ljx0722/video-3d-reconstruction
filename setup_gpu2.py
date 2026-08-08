import paramiko, time

HOST = "connect.nmb2.seetacloud.com"
PORT = 10340
USER = "root"
PASSWORD = "p4hbP7UoQzQ0"

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(HOST, port=PORT, username=USER, password=PASSWORD, timeout=30)
print("Connected!")

def run(cmd, timeout=300):
    print(f"\n>>> {cmd[:120]}...")
    stdin, stdout, stderr = client.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode(errors='replace')
    err = stderr.read().decode(errors='replace')
    if out: print(out[-800:])
    if err and err.strip(): print(f"ERR: {err[-200:]}")
    return out + err

# Find python
which_py = run("which python 2>/dev/null; ls /root/miniconda3/bin/python* 2>/dev/null; conda run python --version 2>/dev/null || echo NO_CONDA")
# Use conda run or direct python path
if "/root/miniconda3" in which_py:
    PY = "/root/miniconda3/bin/python"
    PIP = "/root/miniconda3/bin/pip"
else:
    PY = "python"
    PIP = "pip"

print(f"\nUsing PY={PY} PIP={PIP}")

# Step 1: Install deps
print("\n=== Installing Python deps ===")
run(f"{PIP} install opencv-python-headless trimesh numpy scipy tqdm pillow einops safetensors huggingface_hub 2>&1 | tail -10", timeout=600)

# Step 2: Install lingbot-map
print("\n=== Installing lingbot-map ===")
run(f"cd /root/lingbot-map && {PIP} install -e . 2>&1 | tail -10", timeout=300)

# Step 3: Download model checkpoint
print("\n=== Downloading model checkpoint ===")
run(f"""
cd /root/lingbot-map
{PY} -c "
from huggingface_hub import snapshot_download
import os
snapshot_download('robbyant/lingbot-map', local_dir='./checkpoint', resume_download=True)
print('Download complete')
for f in os.listdir('./checkpoint'):
    size = os.path.getsize(os.path.join('./checkpoint', f))
    print(f'  {f}: {size/1024/1024:.1f} MB')
"
""", timeout=900)

# Step 4: Verify checkpoint
print("\n=== Checking checkpoint ===")
run(f"ls -lh /root/lingbot-map/checkpoint/*.pt 2>/dev/null; {PY} -c \"import torch; ck=torch.load('/root/lingbot-map/checkpoint/lingbot-map.pt', map_location='cpu', weights_only=False); print('Checkpoint loaded OK, keys:', len(ck.get('model',ck).keys()))\" 2>&1 || echo 'Checkpoint check failed'", timeout=60)

# Step 5: Test GPU
print("\n=== Testing GPU ===")
gpu_test = """import torch
print(f'CUDA: {torch.cuda.is_available()}, Device: {torch.cuda.get_device_name(0) if torch.cuda.is_available() else \"N/A\"}')
"""
escaped = gpu_test.replace('"', '\\"').replace('\n', '\\n')
run(f'{PY} -c "{escaped}"', timeout=30)

# Step 6: Start worker
print("\n=== Starting GPU Worker ===")
run("pkill -f gpu_server.py 2>/dev/null; sleep 1; echo done")
run(f"""
cd /root
export MODEL_PATH=/root/lingbot-map/checkpoint/lingbot-map.pt
nohup {PY} gpu_server.py > gpu_worker.log 2>&1 &
echo "PID=$!"
sleep 5
cat gpu_worker.log
""", timeout=30)

# Step 7: Verify worker running
print("\n=== Verifying ===")
run("sleep 10 && tail -30 /root/gpu_worker.log", timeout=30)
run("ps aux 2>/dev/null | grep gpu_server | grep -v grep || echo 'Worker not running!'")

client.close()
print("\n=== DONE ===")
