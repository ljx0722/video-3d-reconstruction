import paramiko, time

HOST = "connect.nmb2.seetacloud.com"
PORT = 10340
USER = "root"
PASSWORD = "p4hbP7UoQzQ0"

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(HOST, port=PORT, username=USER, password=PASSWORD, timeout=30)
print("Connected!")

PY = "/root/miniconda3/bin/python"
PIP = "/root/miniconda3/bin/pip"

def run(cmd, timeout=300):
    print(f"\n>>> {cmd[:180]}")
    chan = client.get_transport().open_session()
    chan.settimeout(timeout)
    chan.exec_command(cmd)
    data = chan.makefile()
    out = data.read().decode(errors="replace")
    exit_status = chan.recv_exit_status()
    print(out[-500:])
    if exit_status != 0:
        print(f"[exit={exit_status}]")
    return out, exit_status

# First check what exists
run("ls -la /root/lingbot-map/checkpoint/ 2>&1; find /root -name '*.pt' -ls 2>/dev/null | head -10")

# Download model directly
print("\n=== Downloading model checkpoint ===")
out, code = run(f"""\
cd /root/lingbot-map
{PY} -c '
import os, sys
from huggingface_hub import snapshot_download
try:
    path = snapshot_download(
        "robbyant/lingbot-map",
        local_dir="./checkpoint",
        local_dir_use_symlinks=False,
        resume_download=True,
    )
    print("Downloaded to:", path)
    for f in os.listdir(path):
        sz = os.path.getsize(os.path.join(path, f))
        print(f"  {f}: {sz/1024/1024:.1f} MB")
except Exception as e:
    print("ERROR:", e)
    sys.exit(1)
'
""", timeout=900)

# Verify
run("ls -lh /root/lingbot-map/checkpoint/ 2>&1")
run(f"find /root/lingbot-map/checkpoint -name '*.pt' -ls 2>/dev/null || echo no-pt-files")

# Test GPU
run(f"""{PY} -c 'import torch; print("CUDA:", torch.cuda.is_available(), torch.cuda.get_device_name(0) if torch.cuda.is_available() else "N/A")' 2>&1""")

# Start worker
print("\n=== Starting GPU Worker ===")
run("pkill -9 -f gpu_server 2>/dev/null || true; sleep 1")
run("cd /root && MODEL_PATH=/root/lingbot-map/checkpoint/lingbot-map.pt nohup /root/miniconda3/bin/python gpu_server.py > gpu_worker.log 2>&1 & sleep 12; tail -30 gpu_worker.log")

time.sleep(5)
print("\n=== Final log ===")
out, _ = run("tail -40 /root/gpu_worker.log")
print(out)

client.close()
print("\n=== DONE ===")
