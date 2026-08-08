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
    print(f"\n>>> {cmd[:150]}")
    chan = client.get_transport().open_session()
    chan.settimeout(timeout)
    chan.exec_command(cmd)
    all_out = b""
    while True:
        try:
            data = chan.recv(65536)
            if not data:
                break
            all_out += data
            print(data.decode(errors="replace")[-200:], end="", flush=True)
        except Exception:
            break
    exit_status = chan.recv_exit_status()
    print(f"\n[exit={exit_status}]")
    return all_out.decode(errors="replace"), exit_status

# Step 0: Find python and check connectivity
run("which python; /root/miniconda3/bin/python --version; nvidia-smi | head -8")
run("curl -sI https://pypi.org 2>&1 | head -3 || curl -sI https://pypi.tuna.tsinghua.edu.cn 2>&1 | head -3")

# Step 1: Configure pip mirror
run("/root/miniconda3/bin/pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple 2>&1 || true")

# Step 2: Install deps
run("/root/miniconda3/bin/pip install --default-timeout=120 opencv-python-headless trimesh numpy scipy tqdm Pillow einops safetensors huggingface_hub 2>&1", timeout=900)

# Step 3: Install lingbot-map
run("cd /root/lingbot-map && /root/miniconda3/bin/pip install --default-timeout=120 -e . 2>&1", timeout=600)

# Step 4: Download model
run("""
cd /root/lingbot-map
/root/miniconda3/bin/python -c "
from huggingface_hub import snapshot_download
snapshot_download('robbyant/lingbot-map', local_dir='./checkpoint', resume_download=True)
print('Download done')
import os
for f in os.listdir('./checkpoint'):
    print(f'  {f}: {os.path.getsize(os.path.join(\"./checkpoint\", f))/1024/1024:.1f} MB')
"
""", timeout=900)

# Step 5: Verify
run("/root/miniconda3/bin/python -c 'import torch; print(f\"CUDA: {torch.cuda.is_available()}, GPU: {torch.cuda.get_device_name(0) if torch.cuda.is_available() else \"N/A\"}\")' 2>&1")
run("ls -lh /root/lingbot-map/checkpoint/*.pt 2>&1")

# Step 6: Start worker
run("pkill -9 -f gpu_server 2>/dev/null || true; sleep 1; echo cleared")
run("cd /root && MODEL_PATH=/root/lingbot-map/checkpoint/lingbot-map.pt nohup /root/miniconda3/bin/python gpu_server.py > gpu_worker.log 2>&1 & sleep 1; echo started; sleep 10; tail -30 gpu_worker.log", timeout=30)

# Step 7: Final check
print("\n=== Final check ===")
time.sleep(5)
out, _ = run("tail -40 /root/gpu_worker.log 2>&1")
print(out)

client.close()
print("\n=== DONE ===")
