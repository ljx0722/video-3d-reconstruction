import paramiko, os

HOST = "connect.nmb2.seetacloud.com"
PORT = 10340
USER = "root"
PASSWORD = "p4hbP7UoQzQ0"

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(HOST, port=PORT, username=USER, password=PASSWORD, timeout=30)
print("Connected!")

# Upload script
sftp = client.open_sftp()
sftp.put(os.path.join(os.path.dirname(__file__), "gpu_setup.sh"), "/root/gpu_setup.sh")
sftp.close()
print("Uploaded!")

# Install modelscope
print("\n=== Installing modelscope ===")
chan = client.get_transport().open_session()
chan.settimeout(120)
chan.exec_command("/root/miniconda3/bin/pip install modelscope 2>&1 | tail -5")
print(chan.makefile().read().decode(errors="replace"))
chan.recv_exit_status()

# Run setup
print("\n=== Running GPU setup ===\n")
chan2 = client.get_transport().open_session()
chan2.settimeout(900)
chan2.exec_command("bash /root/gpu_setup.sh 2>&1")
buf = b""
while True:
    try:
        data = chan2.recv(4096)
        if not data:
            break
        buf += data
        print(data.decode(errors="replace"), end="", flush=True)
    except Exception:
        break
exit_code = chan2.recv_exit_status()
print("\n[exit={}]".format(exit_code))

# Check worker
import time
time.sleep(5)
chan3 = client.get_transport().open_session()
chan3.settimeout(10)
chan3.exec_command("ps aux | grep gpu_server | grep -v grep; echo ---; tail -25 /root/gpu_worker.log 2>/dev/null")
print("\n=== Status ===")
print(chan3.makefile().read().decode(errors="replace"))

client.close()
print("\n=== DONE ===")
